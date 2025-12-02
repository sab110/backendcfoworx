from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db import get_db
from models import Subscription, Plan, CompanyInfo

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
        print(f"📋 Stripe subscription data:")
        print(f"   ID: {stripe_sub.get('id')}")
        print(f"   Status: {stripe_sub.get('status')}")
        print(f"   start_date: {stripe_sub.get('start_date')}")
        print(f"   created: {stripe_sub.get('created')}")
        print(f"   current_period_end: {stripe_sub.get('current_period_end')}")
        print(f"   current_period_start: {stripe_sub.get('current_period_start')}")
        
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
            print(f"⚠️  current_period_end missing, calculating from billing interval...")
            
            # Get billing interval from price
            price = stripe_sub["items"]["data"][0]["price"]
            if price.get("recurring"):
                interval = price["recurring"]["interval"]  # 'month', 'year', 'week', 'day'
                interval_count = price["recurring"].get("interval_count", 1)
                
                print(f"   Billing: {interval_count} {interval}(s)")
                
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
                
                print(f"   Calculated end_date: {end_date}")
            else:
                raise HTTPException(
                    status_code=500,
                    detail="Not a recurring subscription - cannot determine end date"
                )
        else:
            end_date = datetime.utcfromtimestamp(end_timestamp)
        
        print(f"📅 Parsed dates:")
        print(f"   Start: {start_date} (timestamp: {start_timestamp})")
        print(f"   End: {end_date} (timestamp: {end_timestamp})")
        
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

