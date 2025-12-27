from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract
from datetime import datetime, timedelta
from db import get_db
from models import Subscription, Plan, CompanyInfo, QuickBooksToken, User, EmailPreference, EmailLog, CompanyLicenseMapping, GeneratedReport

router = APIRouter()


@router.get("/company/{realm_id}")
async def get_company_subscription(realm_id: str, db: Session = Depends(get_db)):
    """
    Get the active subscription for a company (realm_id)
    """
    subscription = (
        db.query(Subscription)
        .filter(Subscription.realm_id == realm_id)
        .first()
    )

    if not subscription:
        return {
            "status": "no_subscription",
            "message": "No active subscription found for this company"
        }

    # Get plan details if plan_id exists
    plan_details = None
    if subscription.plan_id:
        plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()
        if plan:
            plan_details = {
                "id": plan.id,
                "name": plan.name,
                "billing_cycle": plan.billing_cycle,
                "price": plan.price,
                "stripe_price_id": plan.stripe_price_id
            }

    # Get company details
    company = db.query(CompanyInfo).filter(CompanyInfo.realm_id == realm_id).first()
    company_details = None
    if company:
        company_details = {
            "realm_id": company.realm_id,
            "company_name": company.company_name,
            "email": company.email
        }

    return {
        "id": subscription.id,
        "realm_id": subscription.realm_id,
        "company": company_details,
        "plan": plan_details,
        "status": subscription.status,
        "quantity": subscription.quantity if hasattr(subscription, 'quantity') else 1,
        "start_date": subscription.start_date.isoformat() if subscription.start_date else None,
        "end_date": subscription.end_date.isoformat() if subscription.end_date else None,
        "stripe_subscription_id": subscription.stripe_subscription_id,
        "stripe_customer_id": subscription.stripe_customer_id,
        "created_at": subscription.created_at.isoformat() if subscription.created_at else None
    }


@router.get("/all-plans")
async def get_all_plans(db: Session = Depends(get_db)):
    """
    Get all available pricing plans
    """
    plans = db.query(Plan).all()

    result = []
    for plan in plans:
        result.append({
            "id": plan.id,
            "name": plan.name,
            "billing_cycle": plan.billing_cycle,
            "price": plan.price,
            "stripe_price_id": plan.stripe_price_id
        })

    return {"plans": result}


@router.post("/link-stripe-subscription")
async def link_stripe_subscription(
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Manually link a Stripe subscription to a company.
    Useful when webhook fails to create the subscription automatically.

    Payload:
    {
        "stripe_subscription_id": "sub_xxx",
        "realm_id": "123456789"
    }
    """
    import stripe
    from config import STRIPE_SECRET_KEY
    from datetime import datetime

    stripe.api_key = STRIPE_SECRET_KEY

    stripe_subscription_id = payload.get("stripe_subscription_id")
    realm_id = payload.get("realm_id")

    if not stripe_subscription_id or not realm_id:
        raise HTTPException(
            status_code=400,
            detail="Both stripe_subscription_id and realm_id are required"
        )

    # Verify company exists
    company = db.query(CompanyInfo).filter(CompanyInfo.realm_id == realm_id).first()
    if not company:
        raise HTTPException(
            status_code=404,
            detail=f"Company not found for realm_id: {realm_id}"
        )

    try:
        # Fetch subscription from Stripe
        stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)

        stripe_price_id = stripe_sub["items"]["data"][0]["price"]["id"]
        status = stripe_sub.get("status", "unknown")
        stripe_customer_id = stripe_sub.get("customer")

        # Parse dates correctly from Stripe
        print(f"Stripe subscription data:")
        print(f"  ID: {stripe_sub.get('id')}")
        print(f"  Status: {stripe_sub.get('status')}")
        print(f"  start_date: {stripe_sub.get('start_date')}")
        print(f"  created: {stripe_sub.get('created')}")
        print(f"  current_period_end: {stripe_sub.get('current_period_end')}")
        print(f"  current_period_start: {stripe_sub.get('current_period_start')}")

        start_timestamp = stripe_sub.get("start_date") or stripe_sub.get("created")
        end_timestamp = stripe_sub.get("current_period_end")

        if not start_timestamp:
            raise HTTPException(
                status_code=500,
                detail="Stripe subscription missing start_date and created timestamp"
            )

        start_date = datetime.utcfromtimestamp(start_timestamp)

        # If current_period_end is missing, calculate it from billing interval
        if not end_timestamp:
            print(f"  current_period_end missing, calculating from billing interval...")

            # Get billing interval from price
            price = stripe_sub["items"]["data"][0]["price"]
            if price.get("recurring"):
                interval = price["recurring"]["interval"]  # 'month', 'year', 'week', 'day'
                interval_count = price["recurring"].get("interval_count", 1)

                print(f"  Billing: {interval_count} {interval}(s)")

                # Calculate end date
                from dateutil.relativedelta import relativedelta
                from datetime import timedelta

                if interval == 'month':
                    end_date = start_date + relativedelta(months=interval_count)
                elif interval == 'year':
                    end_date = start_date + relativedelta(years=interval_count)
                elif interval == 'week':
                    end_date = start_date + timedelta(weeks=interval_count)
                elif interval == 'day':
                    end_date = start_date + timedelta(days=interval_count)
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Unknown billing interval: {interval}"
                    )

                print(f"  Calculated end_date: {end_date}")
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Not a recurring subscription - cannot determine end date"
                )
        else:
            end_date = datetime.utcfromtimestamp(end_timestamp)

        print(f"Parsed dates:")
        print(f"  Start: {start_date} (timestamp: {start_timestamp})")
        print(f"  End: {end_date} (timestamp: {end_timestamp})")

        # Get quantity from subscription
        quantity = stripe_sub["items"]["data"][0]["quantity"] if stripe_sub.get("items") and stripe_sub["items"].get("data") else 1
        print(f"  Quantity: {quantity} licenses")

        # Find plan by stripe_price_id
        plan = db.query(Plan).filter(Plan.stripe_price_id == stripe_price_id).first()
        plan_id = plan.id if plan else None

        # Check if subscription already exists
        existing = db.query(Subscription).filter(
            Subscription.realm_id == realm_id
        ).first()

        if existing:
            # Update existing
            existing.stripe_subscription_id = stripe_subscription_id
            existing.stripe_customer_id = stripe_customer_id
            existing.plan_id = plan_id
            existing.status = status
            existing.quantity = quantity
            existing.start_date = start_date
            existing.end_date = end_date
            message = "Subscription updated"
        else:
            # Create new
            new_subscription = Subscription(
                realm_id=realm_id,
                plan_id=plan_id,
                stripe_subscription_id=stripe_subscription_id,
                stripe_customer_id=stripe_customer_id,
                status=status,
                quantity=quantity,
                start_date=start_date,
                end_date=end_date
            )
            db.add(new_subscription)
            message = "Subscription created"

        db.commit()

        return {
            "message": f"{message} and linked to company successfully",
            "realm_id": realm_id,
            "company_name": company.company_name,
            "stripe_subscription_id": stripe_subscription_id,
            "plan": plan.name if plan else "Unknown",
            "status": status,
            "quantity": quantity,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None
        }

    except Exception as e:
        db.rollback()
        # Check if it's a Stripe error
        if 'stripe' in str(type(e).__module__):
            raise HTTPException(
                status_code=400,
                detail=f"Stripe error: {str(e)}"
            )
        raise HTTPException(
            status_code=500,
            detail=f"Error linking subscription: {str(e)}"
        )


@router.delete("/account/{realm_id}")
async def delete_account(realm_id: str, db: Session = Depends(get_db)):
    """
    Delete a company account and all associated data.
    This will:
    - Cancel the Stripe subscription (if active)
    - Delete email preferences
    - Delete email logs
    - Delete license mappings
    - Delete subscription
    - Delete company info
    - Delete QuickBooks token
    - Delete user
    """
    import stripe
    from config import STRIPE_SECRET_KEY

    stripe.api_key = STRIPE_SECRET_KEY

    # 1. Check if company exists
    company = db.query(CompanyInfo).filter(CompanyInfo.realm_id == realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Get the QuickBooks token to find the user
    token = db.query(QuickBooksToken).filter(QuickBooksToken.realm_id == realm_id).first()
    user_id = token.user_id if token else None

    deleted_items = {
        "stripe_subscription_cancelled": False,
        "email_preferences": 0,
        "email_logs": 0,
        "license_mappings": 0,
        "subscription": False,
        "company": False,
        "token": False,
        "user": False,
    }

    try:
        # 2. Cancel Stripe subscription if exists
        subscription = db.query(Subscription).filter(Subscription.realm_id == realm_id).first()
        if subscription and subscription.stripe_subscription_id:
            try:
                stripe.Subscription.cancel(subscription.stripe_subscription_id)
                deleted_items["stripe_subscription_cancelled"] = True
                print(f"Cancelled Stripe subscription: {subscription.stripe_subscription_id}")
            except stripe.error.InvalidRequestError as e:
                # Subscription might already be cancelled
                print(f"Stripe subscription already cancelled or invalid: {e}")
                deleted_items["stripe_subscription_cancelled"] = True
            except Exception as e:
                print(f"Error cancelling Stripe subscription: {e}")

        # 3. Delete email preferences
        email_prefs = db.query(EmailPreference).filter(EmailPreference.realm_id == realm_id).all()
        deleted_items["email_preferences"] = len(email_prefs)
        for pref in email_prefs:
            db.delete(pref)

        # 4. Delete email logs
        email_logs = db.query(EmailLog).filter(EmailLog.realm_id == realm_id).all()
        deleted_items["email_logs"] = len(email_logs)
        for log in email_logs:
            db.delete(log)

        # 5. Delete license mappings
        mappings = db.query(CompanyLicenseMapping).filter(CompanyLicenseMapping.realm_id == realm_id).all()
        deleted_items["license_mappings"] = len(mappings)
        for mapping in mappings:
            db.delete(mapping)

        # 6. Delete subscription
        if subscription:
            db.delete(subscription)
            deleted_items["subscription"] = True

        # 7. Delete company info
        db.delete(company)
        deleted_items["company"] = True

        # 8. Delete QuickBooks token
        if token:
            db.delete(token)
            deleted_items["token"] = True

        # 9. Delete user (if no other tokens exist for this user)
        if user_id:
            other_tokens = db.query(QuickBooksToken).filter(
                QuickBooksToken.user_id == user_id,
                QuickBooksToken.realm_id != realm_id
            ).first()

            if not other_tokens:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    db.delete(user)
                    deleted_items["user"] = True

        db.commit()

        return {
            "success": True,
            "message": "Account deleted successfully",
            "realm_id": realm_id,
            "deleted_items": deleted_items,
        }

    except Exception as e:
        db.rollback()
        print(f"Error deleting account: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting account: {str(e)}"
        )


@router.get("/dashboard-analytics/{realm_id}")
async def get_dashboard_analytics(realm_id: str, db: Session = Depends(get_db)):
    """
    Get comprehensive dashboard analytics for real-time KPIs.
    Returns franchise stats, report counts, subscription details, and activity history.
    """
    try:
        now = datetime.utcnow()
        current_month_start = datetime(now.year, now.month, 1)
        
        # Get franchise/license counts
        total_licenses = db.query(CompanyLicenseMapping).filter(
            CompanyLicenseMapping.realm_id == realm_id
        ).count()
        
        active_licenses = db.query(CompanyLicenseMapping).filter(
            CompanyLicenseMapping.realm_id == realm_id,
            CompanyLicenseMapping.is_active == "true"
        ).count()
        
        inactive_licenses = total_licenses - active_licenses
        
        # Get report statistics
        total_rvcr_reports = db.query(GeneratedReport).filter(
            GeneratedReport.realm_id == realm_id,
            GeneratedReport.report_type == "RVCR"
        ).count()
        
        total_payment_reports = db.query(GeneratedReport).filter(
            GeneratedReport.realm_id == realm_id,
            GeneratedReport.report_type == "PaymentSummary"
        ).count()
        
        # Reports generated this month
        reports_this_month = db.query(GeneratedReport).filter(
            GeneratedReport.realm_id == realm_id,
            GeneratedReport.generated_at >= current_month_start
        ).count()
        
        # Get last report generated
        last_report = db.query(GeneratedReport).filter(
            GeneratedReport.realm_id == realm_id
        ).order_by(GeneratedReport.generated_at.desc()).first()
        
        # Get subscription details
        subscription = db.query(Subscription).filter(
            Subscription.realm_id == realm_id
        ).first()
        
        subscription_data = None
        if subscription:
            subscription_data = {
                "status": subscription.status,
                "quantity": subscription.quantity if hasattr(subscription, 'quantity') else 1,
                "start_date": subscription.start_date.isoformat() if subscription.start_date else None,
                "end_date": subscription.end_date.isoformat() if subscription.end_date else None,
            }
        
        # Get company info
        company = db.query(CompanyInfo).filter(CompanyInfo.realm_id == realm_id).first()
        
        # Get QuickBooks connection status
        qb_token = db.query(QuickBooksToken).filter(QuickBooksToken.realm_id == realm_id).first()
        qb_connected = qb_token is not None
        qb_last_sync = qb_token.updated_at.isoformat() if qb_token and qb_token.updated_at else None
        
        # Get monthly franchise activity (last 6 months)
        monthly_activity = []
        for i in range(5, -1, -1):
            month_date = now - timedelta(days=i*30)
            month_name = month_date.strftime('%b')
            
            # Count reports generated in that month
            month_start = datetime(month_date.year, month_date.month, 1)
            if month_date.month == 12:
                month_end = datetime(month_date.year + 1, 1, 1)
            else:
                month_end = datetime(month_date.year, month_date.month + 1, 1)
            
            month_reports = db.query(GeneratedReport).filter(
                GeneratedReport.realm_id == realm_id,
                GeneratedReport.generated_at >= month_start,
                GeneratedReport.generated_at < month_end
            ).count()
            
            monthly_activity.append({
                "month": month_name,
                "reports": month_reports,
                "active_franchises": active_licenses  # Could track historical data
            })
        
        # Calculate trends (compare to last month)
        last_month_start = datetime(now.year, now.month - 1 if now.month > 1 else 12, 1)
        if now.month == 1:
            last_month_start = datetime(now.year - 1, 12, 1)
        
        last_month_reports = db.query(GeneratedReport).filter(
            GeneratedReport.realm_id == realm_id,
            GeneratedReport.generated_at >= last_month_start,
            GeneratedReport.generated_at < current_month_start
        ).count()
        
        reports_trend = 0
        if last_month_reports > 0:
            reports_trend = round(((reports_this_month - last_month_reports) / last_month_reports) * 100)
        elif reports_this_month > 0:
            reports_trend = 100
        
        # Get recent activity logs
        recent_reports = db.query(GeneratedReport).filter(
            GeneratedReport.realm_id == realm_id
        ).order_by(GeneratedReport.generated_at.desc()).limit(5).all()
        
        recent_activity = []
        for report in recent_reports:
            time_diff = now - report.generated_at
            if time_diff.days > 0:
                time_str = f"{time_diff.days} day{'s' if time_diff.days > 1 else ''} ago"
            elif time_diff.seconds > 3600:
                hours = time_diff.seconds // 3600
                time_str = f"{hours} hour{'s' if hours > 1 else ''} ago"
            elif time_diff.seconds > 60:
                minutes = time_diff.seconds // 60
                time_str = f"{minutes} minute{'s' if minutes > 1 else ''} ago"
            else:
                time_str = "Just now"
            
            recent_activity.append({
                "type": "report",
                "title": f"{report.report_type} Report Generated",
                "subtitle": report.report_name or f"Franchise {report.franchise_number}",
                "time": time_str,
                "timestamp": report.generated_at.isoformat(),
            })
        
        return {
            "success": True,
            "data": {
                "franchises": {
                    "total": total_licenses,
                    "active": active_licenses,
                    "inactive": inactive_licenses,
                },
                "reports": {
                    "total_rvcr": total_rvcr_reports,
                    "total_payment_summary": total_payment_reports,
                    "total": total_rvcr_reports + total_payment_reports,
                    "this_month": reports_this_month,
                    "trend_percent": reports_trend,
                    "last_generated": last_report.generated_at.isoformat() if last_report else None,
                },
                "subscription": subscription_data,
                "quickbooks": {
                    "connected": qb_connected,
                    "last_sync": qb_last_sync,
                },
                "company": {
                    "name": company.company_name if company else None,
                    "email": company.email if company else None,
                },
                "monthly_activity": monthly_activity,
                "recent_activity": recent_activity,
            }
        }
        
    except Exception as e:
        print(f"Error fetching dashboard analytics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching dashboard analytics: {str(e)}"
        )
