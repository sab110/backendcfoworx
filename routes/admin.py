"""
Admin Service Routes
====================
Provides admin-only endpoints for managing the platform including:
- Admin authentication (login with credentials from .env)
- View all client/company information
- View all subscriptions summary
- View all submissions
- View failed payments log
- View historic data and activity logs
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from db import get_db
from models import (
    CompanyInfo, Subscription, Plan, User, QuickBooksToken,
    License, CompanyLicenseMapping, FailedPaymentLog, Submission, AdminActivityLog
)
from config import (
    ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_JWT_SECRET, ADMIN_JWT_EXPIRY_HOURS,
    STRIPE_SECRET_KEY
)
from datetime import datetime, timedelta
from typing import Optional
import jwt
import stripe

router = APIRouter()
security = HTTPBearer()
stripe.api_key = STRIPE_SECRET_KEY


# ------------------------------------------------------
# JWT HELPER FUNCTIONS
# ------------------------------------------------------
def create_admin_token(username: str) -> str:
    """Create a JWT token for admin authentication"""
    payload = {
        "sub": username,
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=ADMIN_JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, ADMIN_JWT_SECRET, algorithm="HS256")


def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Verify JWT token and return payload"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, ADMIN_JWT_SECRET, algorithms=["HS256"])
        
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Not authorized as admin")
        
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def log_admin_activity(
    db: Session,
    username: str,
    action: str,
    resource_type: str = None,
    resource_id: str = None,
    details: dict = None,
    request: Request = None
):
    """Log admin activity for audit trail"""
    log = AdminActivityLog(
        admin_username=username,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=request.client.host if request else None,
        user_agent=request.headers.get("user-agent") if request else None
    )
    db.add(log)
    db.commit()


# ------------------------------------------------------
# AUTHENTICATION ROUTES
# ------------------------------------------------------
@router.post("/login")
async def admin_login(request: Request, db: Session = Depends(get_db)):
    """
    Admin login with username and password from .env
    Returns a JWT token for authenticated requests
    """
    data = await request.json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    # Verify credentials against .env values
    if username != ADMIN_USERNAME or password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create JWT token
    token = create_admin_token(username)
    
    # Log the login
    log_admin_activity(
        db, username, "login",
        details={"ip": request.client.host},
        request=request
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ADMIN_JWT_EXPIRY_HOURS * 3600,
        "admin_username": username
    }


@router.get("/verify")
async def verify_admin_session(admin: dict = Depends(verify_admin_token)):
    """Verify if the current admin session is valid"""
    return {
        "valid": True,
        "admin_username": admin.get("sub"),
        "expires_at": datetime.utcfromtimestamp(admin.get("exp")).isoformat()
    }


# ------------------------------------------------------
# CLIENT INFORMATION ROUTES
# ------------------------------------------------------
@router.get("/clients")
async def get_all_clients(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
    status: Optional[str] = None  # "active", "inactive", "all"
):
    """
    Get all franchisee client information with pagination and filters
    """
    query = db.query(CompanyInfo)
    
    # Apply search filter
    if search:
        query = query.filter(
            (CompanyInfo.company_name.ilike(f"%{search}%")) |
            (CompanyInfo.email.ilike(f"%{search}%")) |
            (CompanyInfo.realm_id.ilike(f"%{search}%"))
        )
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    companies = query.order_by(desc(CompanyInfo.created_at)).offset(offset).limit(limit).all()
    
    # Build response with subscription status
    clients = []
    for company in companies:
        subscription = db.query(Subscription).filter(
            Subscription.realm_id == company.realm_id
        ).first()
        
        # Get license count
        license_count = db.query(CompanyLicenseMapping).filter(
            CompanyLicenseMapping.realm_id == company.realm_id,
            CompanyLicenseMapping.is_active == "true"
        ).count()
        
        # Get user info
        qb_token = db.query(QuickBooksToken).filter(
            QuickBooksToken.realm_id == company.realm_id
        ).first()
        user = None
        if qb_token:
            user = db.query(User).filter(User.id == qb_token.user_id).first()
        
        clients.append({
            "realm_id": company.realm_id,
            "company_name": company.company_name,
            "legal_name": company.legal_name,
            "email": company.email,
            "primary_phone": company.primary_phone,
            "company_addr": company.company_addr,
            "country": company.country,
            "onboarding_completed": company.onboarding_completed,
            "created_at": company.created_at.isoformat() if company.created_at else None,
            "license_count": license_count,
            "subscription": {
                "status": subscription.status if subscription else "no_subscription",
                "plan_id": subscription.plan_id if subscription else None,
                "quantity": subscription.quantity if subscription else 0,
                "end_date": subscription.end_date.isoformat() if subscription and subscription.end_date else None
            } if subscription else None,
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name
            } if user else None
        })
    
    # Filter by subscription status if specified
    if status and status != "all":
        if status == "active":
            clients = [c for c in clients if c.get("subscription") and c["subscription"]["status"] == "active"]
        elif status == "inactive":
            clients = [c for c in clients if not c.get("subscription") or c["subscription"]["status"] != "active"]
    
    # Log activity
    log_admin_activity(
        db, admin.get("sub"), "view_clients",
        details={"page": page, "search": search, "count": len(clients)},
        request=request
    )

    return {
        "clients": clients,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@router.get("/clients/{realm_id}")
async def get_client_detail(
    realm_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token)
):
    """Get detailed information for a specific client"""
    company = db.query(CompanyInfo).filter(CompanyInfo.realm_id == realm_id).first()
    
    if not company:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Get subscription
    subscription = db.query(Subscription).filter(
        Subscription.realm_id == realm_id
    ).first()
    
    plan = None
    if subscription and subscription.plan_id:
        plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
    
    # Get licenses
    licenses = db.query(CompanyLicenseMapping).filter(
        CompanyLicenseMapping.realm_id == realm_id
    ).all()
    
    license_details = []
    for mapping in licenses:
        license_info = db.query(License).filter(
            License.franchise_number == mapping.franchise_number
        ).first()
        license_details.append({
            "franchise_number": mapping.franchise_number,
            "name": license_info.name if license_info else None,
            "owner": license_info.owner if license_info else None,
            "city": license_info.city if license_info else None,
            "state": license_info.state if license_info else None,
            "qbo_department_id": mapping.qbo_department_id,
            "qbo_department_name": mapping.qbo_department_name,
            "is_active": mapping.is_active
        })
    
    # Get user info
    qb_token = db.query(QuickBooksToken).filter(
        QuickBooksToken.realm_id == realm_id
    ).first()
    user = None
    if qb_token:
        user = db.query(User).filter(User.id == qb_token.user_id).first()
    
    # Get submissions
    submissions = db.query(Submission).filter(
        Submission.realm_id == realm_id
    ).order_by(desc(Submission.submitted_at)).limit(10).all()
    
    # Get failed payments
    failed_payments = db.query(FailedPaymentLog).filter(
        FailedPaymentLog.realm_id == realm_id
    ).order_by(desc(FailedPaymentLog.failed_at)).limit(5).all()
    
    log_admin_activity(
        db, admin.get("sub"), "view_client_detail",
        resource_type="client", resource_id=realm_id,
        request=request
    )

    return {
        "company": {
            "realm_id": company.realm_id,
            "company_name": company.company_name,
            "legal_name": company.legal_name,
            "employer_id": company.employer_id,
            "email": company.email,
            "primary_phone": company.primary_phone,
            "company_addr": company.company_addr,
            "legal_addr": company.legal_addr,
            "web_addr": company.web_addr,
            "country": company.country,
            "company_start_date": company.company_start_date,
            "fiscal_year_start_month": company.fiscal_year_start_month,
            "onboarding_completed": company.onboarding_completed,
            "onboarding_completed_at": company.onboarding_completed_at.isoformat() if company.onboarding_completed_at else None,
            "created_at": company.created_at.isoformat() if company.created_at else None,
            "last_synced_at": company.last_synced_at.isoformat() if company.last_synced_at else None
        },
        "subscription": {
            "id": subscription.id,
            "status": subscription.status,
            "quantity": subscription.quantity,
            "start_date": subscription.start_date.isoformat() if subscription.start_date else None,
            "end_date": subscription.end_date.isoformat() if subscription.end_date else None,
            "stripe_subscription_id": subscription.stripe_subscription_id,
            "stripe_customer_id": subscription.stripe_customer_id,
            "plan": {
                "name": plan.name,
                "billing_cycle": plan.billing_cycle,
                "price": plan.price
            } if plan else None
        } if subscription else None,
        "licenses": license_details,
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "phone": user.phone,
            "created_at": user.created_at.isoformat() if user.created_at else None
        } if user else None,
        "recent_submissions": [{
            "id": s.id,
            "type": s.submission_type,
            "status": s.status,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None
        } for s in submissions],
        "recent_failed_payments": [{
            "id": fp.id,
            "amount": fp.amount,
            "failure_message": fp.failure_message,
            "status": fp.status,
            "failed_at": fp.failed_at.isoformat() if fp.failed_at else None
        } for fp in failed_payments]
    }


# ------------------------------------------------------
# SUBSCRIPTION SUMMARY ROUTES
# ------------------------------------------------------
@router.get("/subscriptions/summary")
async def get_subscription_summary(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token)
):
    """
    Get summary of all active subscriptions including:
    - Billing cycles, renewals, upgrades/downgrades
    """
    # Get all subscriptions with plan info
    subscriptions = db.query(Subscription).all()
    
    # Calculate summary stats
    total_subscriptions = len(subscriptions)
    active_count = sum(1 for s in subscriptions if s.status == "active")
    canceled_count = sum(1 for s in subscriptions if s.status == "canceled")
    past_due_count = sum(1 for s in subscriptions if s.status == "past_due")
    trialing_count = sum(1 for s in subscriptions if s.status == "trialing")
    
    # Group by plan
    plan_breakdown = {}
    total_licenses = 0
    total_mrr = 0  # Monthly Recurring Revenue estimate
    
    for sub in subscriptions:
        if sub.status != "active":
            continue
            
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first() if sub.plan_id else None
        plan_key = f"{plan.name} - {plan.billing_cycle}" if plan else "Unknown"
        
        if plan_key not in plan_breakdown:
            plan_breakdown[plan_key] = {
                "count": 0,
                "total_licenses": 0,
                "plan_name": plan.name if plan else "Unknown",
                "billing_cycle": plan.billing_cycle if plan else "Unknown",
                "price_per_license": plan.price if plan else "N/A"
            }
        
        plan_breakdown[plan_key]["count"] += 1
        plan_breakdown[plan_key]["total_licenses"] += sub.quantity or 1
        total_licenses += sub.quantity or 1
        
        # Estimate MRR (convert all to monthly)
        if plan:
            try:
                price_match = plan.price.replace("$", "").split("/")[0]
                base_price = float(price_match)
                license_qty = sub.quantity or 1
                
                if plan.billing_cycle == "monthly":
                    total_mrr += base_price * license_qty
                elif plan.billing_cycle == "6-month":
                    total_mrr += (base_price / 6) * license_qty
                elif plan.billing_cycle == "annual":
                    total_mrr += (base_price / 12) * license_qty
            except:
                pass
    
    # Get upcoming renewals (next 30 days)
    thirty_days_from_now = datetime.utcnow() + timedelta(days=30)
    upcoming_renewals = db.query(Subscription).filter(
        and_(
            Subscription.status == "active",
            Subscription.end_date <= thirty_days_from_now,
            Subscription.end_date >= datetime.utcnow()
        )
    ).count()
    
    log_admin_activity(
        db, admin.get("sub"), "view_subscription_summary",
        request=request
    )

    return {
        "summary": {
            "total_subscriptions": total_subscriptions,
            "active": active_count,
            "canceled": canceled_count,
            "past_due": past_due_count,
            "trialing": trialing_count,
            "total_licenses": total_licenses,
            "estimated_mrr": f"${total_mrr:.2f}",
            "upcoming_renewals_30_days": upcoming_renewals
        },
        "plan_breakdown": list(plan_breakdown.values())
    }


@router.get("/subscriptions")
async def get_all_subscriptions(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    page: int = 1,
    limit: int = 50,
    status: Optional[str] = None
):
    """Get all subscriptions with detailed information"""
    query = db.query(Subscription)
    
    if status:
        query = query.filter(Subscription.status == status)
    
    total = query.count()
    offset = (page - 1) * limit
    
    subscriptions = query.order_by(desc(Subscription.created_at)).offset(offset).limit(limit).all()
    
    result = []
    for sub in subscriptions:
        company = db.query(CompanyInfo).filter(
            CompanyInfo.realm_id == sub.realm_id
        ).first()
        
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first() if sub.plan_id else None
        
        result.append({
            "id": sub.id,
            "realm_id": sub.realm_id,
            "company_name": company.company_name if company else "Unknown",
            "company_email": company.email if company else None,
            "plan": {
                "name": plan.name,
                "billing_cycle": plan.billing_cycle,
                "price": plan.price
            } if plan else None,
            "status": sub.status,
            "quantity": sub.quantity,
            "start_date": sub.start_date.isoformat() if sub.start_date else None,
            "end_date": sub.end_date.isoformat() if sub.end_date else None,
            "stripe_subscription_id": sub.stripe_subscription_id,
            "stripe_customer_id": sub.stripe_customer_id,
            "created_at": sub.created_at.isoformat() if sub.created_at else None
        })
    
    log_admin_activity(
        db, admin.get("sub"), "view_subscriptions",
        details={"page": page, "status": status},
        request=request
    )

    return {
        "subscriptions": result,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


# ------------------------------------------------------
# SUBMISSIONS ROUTES
# ------------------------------------------------------
@router.get("/submissions")
async def get_all_submissions(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    page: int = 1,
    limit: int = 50,
    status: Optional[str] = None,
    realm_id: Optional[str] = None
):
    """Get all franchisee submissions"""
    query = db.query(Submission)
    
    if status:
        query = query.filter(Submission.status == status)
    if realm_id:
        query = query.filter(Submission.realm_id == realm_id)
    
    total = query.count()
    offset = (page - 1) * limit
    
    submissions = query.order_by(desc(Submission.submitted_at)).offset(offset).limit(limit).all()
    
    result = []
    for sub in submissions:
        company = db.query(CompanyInfo).filter(
            CompanyInfo.realm_id == sub.realm_id
        ).first()
        
        result.append({
            "id": sub.id,
            "realm_id": sub.realm_id,
            "company_name": company.company_name if company else "Unknown",
            "franchise_number": sub.franchise_number,
            "submission_type": sub.submission_type,
            "period_start": sub.period_start.isoformat() if sub.period_start else None,
            "period_end": sub.period_end.isoformat() if sub.period_end else None,
            "gross_sales": sub.gross_sales,
            "royalty_amount": sub.royalty_amount,
            "advertising_fee": sub.advertising_fee,
            "status": sub.status,
            "notes": sub.notes,
            "reviewed_by": sub.reviewed_by,
            "reviewed_at": sub.reviewed_at.isoformat() if sub.reviewed_at else None,
            "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
            "attachments": sub.attachments
        })
    
    log_admin_activity(
        db, admin.get("sub"), "view_submissions",
        details={"page": page, "status": status, "realm_id": realm_id},
        request=request
    )

    return {
        "submissions": result,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@router.patch("/submissions/{submission_id}")
async def update_submission_status(
    submission_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token)
):
    """Update submission status (approve/reject)"""
    data = await request.json()
    new_status = data.get("status")
    notes = data.get("notes")
    
    if new_status not in ["approved", "rejected", "pending_review"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    
    submission.status = new_status
    submission.reviewed_by = admin.get("sub")
    submission.reviewed_at = datetime.utcnow()
    if notes:
        submission.notes = notes
    
    db.commit()
    
    log_admin_activity(
        db, admin.get("sub"), "update_submission",
        resource_type="submission", resource_id=str(submission_id),
        details={"new_status": new_status},
        request=request
    )

    return {"message": "Submission updated", "status": new_status}


# ------------------------------------------------------
# FAILED PAYMENTS ROUTES
# ------------------------------------------------------
@router.get("/failed-payments")
async def get_failed_payments(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    page: int = 1,
    limit: int = 50,
    status: Optional[str] = None  # "unresolved", "resolved", "all"
):
    """Get failed payments log"""
    query = db.query(FailedPaymentLog)
    
    if status and status != "all":
        query = query.filter(FailedPaymentLog.status == status)
    
    total = query.count()
    offset = (page - 1) * limit
    
    failed_payments = query.order_by(desc(FailedPaymentLog.failed_at)).offset(offset).limit(limit).all()
    
    result = []
    for fp in failed_payments:
        result.append({
            "id": fp.id,
            "realm_id": fp.realm_id,
            "company_name": fp.company_name,
            "customer_email": fp.customer_email,
            "stripe_customer_id": fp.stripe_customer_id,
            "stripe_subscription_id": fp.stripe_subscription_id,
            "stripe_invoice_id": fp.stripe_invoice_id,
            "amount": fp.amount,
            "currency": fp.currency,
            "failure_code": fp.failure_code,
            "failure_message": fp.failure_message,
            "status": fp.status,
            "resolution_notes": fp.resolution_notes,
            "resolved_at": fp.resolved_at.isoformat() if fp.resolved_at else None,
            "failed_at": fp.failed_at.isoformat() if fp.failed_at else None
        })
    
    log_admin_activity(
        db, admin.get("sub"), "view_failed_payments",
        details={"page": page, "status": status},
        request=request
    )

    return {
        "failed_payments": result,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@router.patch("/failed-payments/{payment_id}/resolve")
async def resolve_failed_payment(
    payment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token)
):
    """Mark a failed payment as resolved"""
    data = await request.json()
    notes = data.get("notes", "")
    
    failed_payment = db.query(FailedPaymentLog).filter(
        FailedPaymentLog.id == payment_id
    ).first()
    
    if not failed_payment:
        raise HTTPException(status_code=404, detail="Failed payment record not found")
    
    failed_payment.status = "resolved"
    failed_payment.resolved_at = datetime.utcnow()
    failed_payment.resolution_notes = notes
    
    db.commit()
    
    log_admin_activity(
        db, admin.get("sub"), "resolve_failed_payment",
        resource_type="failed_payment", resource_id=str(payment_id),
        request=request
    )

    return {"message": "Failed payment marked as resolved"}


@router.get("/failed-payments/sync-from-stripe")
async def sync_failed_payments_from_stripe(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    days: int = 30
):
    """
    Sync failed payments from Stripe for the last N days
    """
    try:
        # Calculate timestamp for N days ago
        start_timestamp = int((datetime.utcnow() - timedelta(days=days)).timestamp())
        
        # Fetch failed invoices from Stripe
        invoices = stripe.Invoice.list(
            status="open",
            created={"gte": start_timestamp},
            limit=100
        )
        
        synced_count = 0
        for invoice in invoices.auto_paging_iter():
            # Check if payment was attempted and failed
            if invoice.attempted and not invoice.paid:
                # Check if already logged
                existing = db.query(FailedPaymentLog).filter(
                    FailedPaymentLog.stripe_invoice_id == invoice.id
                ).first()
                
                if not existing:
                    # Get customer info
                    customer = stripe.Customer.retrieve(invoice.customer) if invoice.customer else None
                    
                    # Find realm_id from subscription
                    realm_id = None
                    company_name = None
                    if invoice.subscription:
                        sub = db.query(Subscription).filter(
                            Subscription.stripe_subscription_id == invoice.subscription
                        ).first()
                        if sub:
                            realm_id = sub.realm_id
                            company = db.query(CompanyInfo).filter(
                                CompanyInfo.realm_id == realm_id
                            ).first()
                            if company:
                                company_name = company.company_name
                    
                    # Create failed payment log
                    log = FailedPaymentLog(
                        realm_id=realm_id,
                        stripe_customer_id=invoice.customer,
                        stripe_subscription_id=invoice.subscription,
                        stripe_invoice_id=invoice.id,
                        amount=invoice.amount_due,
                        currency=invoice.currency,
                        failure_code=invoice.last_finalization_error.code if invoice.last_finalization_error else None,
                        failure_message=invoice.last_finalization_error.message if invoice.last_finalization_error else "Payment failed",
                        customer_email=customer.email if customer else None,
                        company_name=company_name,
                        failed_at=datetime.utcfromtimestamp(invoice.created)
                    )
                    db.add(log)
                    synced_count += 1
        
        db.commit()
        
        log_admin_activity(
            db, admin.get("sub"), "sync_failed_payments",
            details={"days": days, "synced_count": synced_count},
            request=request
        )

        return {
            "message": f"Synced {synced_count} failed payment records from Stripe",
            "synced_count": synced_count
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error syncing from Stripe: {str(e)}")


# ------------------------------------------------------
# HISTORIC DATA / ACTIVITY LOG ROUTES
# ------------------------------------------------------
@router.get("/activity-logs")
async def get_activity_logs(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    page: int = 1,
    limit: int = 100,
    action: Optional[str] = None,
    admin_username: Optional[str] = None
):
    """Get admin activity logs for audit trail"""
    query = db.query(AdminActivityLog)
    
    if action:
        query = query.filter(AdminActivityLog.action == action)
    if admin_username:
        query = query.filter(AdminActivityLog.admin_username == admin_username)
    
    total = query.count()
    offset = (page - 1) * limit
    
    logs = query.order_by(desc(AdminActivityLog.created_at)).offset(offset).limit(limit).all()
    
    result = [{
        "id": log.id,
        "admin_username": log.admin_username,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "details": log.details,
        "ip_address": log.ip_address,
        "created_at": log.created_at.isoformat() if log.created_at else None
    } for log in logs]

    return {
        "activity_logs": result,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@router.get("/historic/companies")
async def get_historic_company_data(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
):
    """Get historic company registration data"""
    query = db.query(CompanyInfo)
    
    if from_date:
        query = query.filter(CompanyInfo.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.filter(CompanyInfo.created_at <= datetime.fromisoformat(to_date))
    
    companies = query.order_by(CompanyInfo.created_at).all()
    
    # Group by month for trend analysis
    monthly_data = {}
    for company in companies:
        if company.created_at:
            month_key = company.created_at.strftime("%Y-%m")
            if month_key not in monthly_data:
                monthly_data[month_key] = 0
            monthly_data[month_key] += 1
    
    log_admin_activity(
        db, admin.get("sub"), "view_historic_companies",
        details={"from_date": from_date, "to_date": to_date},
        request=request
    )

    return {
        "total_companies": len(companies),
        "monthly_registrations": [
            {"month": k, "count": v} for k, v in sorted(monthly_data.items())
        ]
    }


@router.get("/historic/subscriptions")
async def get_historic_subscription_data(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token),
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
):
    """Get historic subscription data for trend analysis"""
    query = db.query(Subscription)
    
    if from_date:
        query = query.filter(Subscription.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.filter(Subscription.created_at <= datetime.fromisoformat(to_date))
    
    subscriptions = query.order_by(Subscription.created_at).all()
    
    # Calculate metrics
    total = len(subscriptions)
    active = sum(1 for s in subscriptions if s.status == "active")
    canceled = sum(1 for s in subscriptions if s.status == "canceled")
    
    # Monthly trend
    monthly_data = {}
    for sub in subscriptions:
        if sub.created_at:
            month_key = sub.created_at.strftime("%Y-%m")
            if month_key not in monthly_data:
                monthly_data[month_key] = {"new": 0, "active": 0, "canceled": 0}
            monthly_data[month_key]["new"] += 1
            if sub.status == "active":
                monthly_data[month_key]["active"] += 1
            elif sub.status == "canceled":
                monthly_data[month_key]["canceled"] += 1
    
    log_admin_activity(
        db, admin.get("sub"), "view_historic_subscriptions",
        details={"from_date": from_date, "to_date": to_date},
        request=request
    )

    return {
        "total_subscriptions": total,
        "active_subscriptions": active,
        "canceled_subscriptions": canceled,
        "churn_rate": f"{(canceled / total * 100):.1f}%" if total > 0 else "0%",
        "monthly_trends": [
            {"month": k, **v} for k, v in sorted(monthly_data.items())
        ]
    }


# ------------------------------------------------------
# DASHBOARD OVERVIEW
# ------------------------------------------------------
@router.get("/dashboard")
async def get_admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(verify_admin_token)
):
    """Get admin dashboard overview with key metrics"""
    
    # Company stats
    total_companies = db.query(CompanyInfo).count()
    companies_this_month = db.query(CompanyInfo).filter(
        CompanyInfo.created_at >= datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    ).count()
    
    # Subscription stats
    total_subscriptions = db.query(Subscription).count()
    active_subscriptions = db.query(Subscription).filter(Subscription.status == "active").count()
    past_due_subscriptions = db.query(Subscription).filter(Subscription.status == "past_due").count()
    
    # Total licenses
    total_licenses = db.query(func.sum(Subscription.quantity)).filter(
        Subscription.status == "active"
    ).scalar() or 0
    
    # Failed payments
    unresolved_failed_payments = db.query(FailedPaymentLog).filter(
        FailedPaymentLog.status == "unresolved"
    ).count()
    
    # Pending submissions
    pending_submissions = db.query(Submission).filter(
        Submission.status.in_(["submitted", "pending_review"])
    ).count()
    
    # Revenue estimate (MRR)
    mrr = 0
    active_subs = db.query(Subscription).filter(Subscription.status == "active").all()
    for sub in active_subs:
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first() if sub.plan_id else None
        if plan:
            try:
                price_str = plan.price.replace("$", "").split("/")[0]
                base_price = float(price_str)
                qty = sub.quantity or 1
                
                if plan.billing_cycle == "monthly":
                    mrr += base_price * qty
                elif plan.billing_cycle == "6-month":
                    mrr += (base_price / 6) * qty
                elif plan.billing_cycle == "annual":
                    mrr += (base_price / 12) * qty
            except:
                pass
    
    # Upcoming renewals (next 7 days)
    seven_days = datetime.utcnow() + timedelta(days=7)
    upcoming_renewals = db.query(Subscription).filter(
        and_(
            Subscription.status == "active",
            Subscription.end_date <= seven_days,
            Subscription.end_date >= datetime.utcnow()
        )
    ).count()
    
    log_admin_activity(
        db, admin.get("sub"), "view_dashboard",
        request=request
    )

    return {
        "overview": {
            "total_companies": total_companies,
            "new_companies_this_month": companies_this_month,
            "total_subscriptions": total_subscriptions,
            "active_subscriptions": active_subscriptions,
            "past_due_subscriptions": past_due_subscriptions,
            "total_active_licenses": total_licenses,
            "estimated_mrr": f"${mrr:.2f}",
            "unresolved_failed_payments": unresolved_failed_payments,
            "pending_submissions": pending_submissions,
            "upcoming_renewals_7_days": upcoming_renewals
        },
        "alerts": {
            "has_failed_payments": unresolved_failed_payments > 0,
            "has_past_due": past_due_subscriptions > 0,
            "has_pending_submissions": pending_submissions > 0
        }
    }

