from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db import get_db
from models import Subscription, Plan, User

router = APIRouter()


@router.get("/user/{user_id}")
async def get_user_subscription(user_id: int, db: Session = Depends(get_db)):
    """
    Get the active subscription for a user
    """
    subscription = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .first()
    )
    
    if not subscription:
        return {
            "status": "no_subscription",
            "message": "No active subscription found"
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
    
    return {
        "id": subscription.id,
        "user_id": subscription.user_id,
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

