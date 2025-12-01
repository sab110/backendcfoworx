from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import User, Subscription, Plan
import stripe
from datetime import datetime
from config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, FRONTEND_URL



router = APIRouter()
stripe.api_key = STRIPE_SECRET_KEY


# --------------------------------------------------------------------
#  POST /api/stripe/create-checkout-session
# --------------------------------------------------------------------
@router.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    data = await request.json()
    price_id = data.get("priceId")
    email = data.get("email")

    if not price_id or not email:
        raise HTTPException(status_code=400, detail="Missing required fields")

    try:
        session = stripe.checkout.Session.create(
            success_url=f"{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/cancel",
            mode="subscription",
            payment_method_types=["card"],
            customer_email=email,
            line_items=[{"price": price_id, "quantity": 1}],
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------
#  POST /api/stripe/create-customer-portal
# --------------------------------------------------------------------
@router.post("/create-customer-portal")
async def create_customer_portal(request: Request):
    data = await request.json()
    customer_id = data.get("customerId")

    if not customer_id:
        raise HTTPException(status_code=400, detail="Missing customerId")

    try:
        # Load the portal configuration ID from environment
        # portal_config_id = os.getenv("STRIPE_PORTAL_CONFIGURATION_ID")

        # Create a billing portal session
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{FRONTEND_URL}/dashboard",
            # configuration=portal_config_id  
        )
        return {"url": portal_session.url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --------------------------------------------------------------------
#  POST /api/stripe/webhooks — listen to billing events
# --------------------------------------------------------------------
# @router.post("/webhooks")
# async def stripe_webhook(request: Request):
#     payload = await request.body()
#     sig_header = request.headers.get("stripe-signature")
#     event = None

#     try:
#         event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
#     except ValueError:
#         raise HTTPException(status_code=400, detail="Invalid payload")
#     except stripe.error.SignatureVerificationError:
#         raise HTTPException(status_code=400, detail="Invalid signature")

#     # Extract event details
#     event_type = event["type"]
#     data = event["data"]["object"]

#     print(f"📦 Received event: {event_type}")

#     # ---- Event Listeners ----
#     if event_type == "checkout.session.completed":
#         print(f"Checkout completed for customer: {data.get('customer_email')}")
#         # TODO: Create new customer record in DB

#     elif event_type == "customer.subscription.created":
#         print(f"Subscription created: {data['id']}")
#         print(f"Status: {data['status']} | Plan: {data['items']['data'][0]['price']['nickname']}")
#         # TODO: Save subscription to DB

#     elif event_type == "customer.subscription.updated":
#         print(f"Subscription updated: {data['id']} | Status: {data['status']}")
#         # TODO: Update local DB subscription

#     elif event_type == "customer.subscription.deleted":
#         print(f"Subscription canceled: {data['id']}")
#         # TODO:

#     elif event_type == "invoice.payment_failed":
#         print(f"Payment failed for subscription: {data.get('subscription')}")

#     elif event_type == "invoice.payment_succeeded":
#         print(f"Payment succeeded for invoice: {data['id']}")

#     return {"status": "success"}

@router.post("/webhooks")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    print(f"📦 Received event: {event_type}")

    # --- CHECKOUT COMPLETED ---
    if event_type == "checkout.session.completed":
        customer_email = data.get("customer_email")
        stripe_subscription_id = data.get("subscription")  # This is the Stripe subscription ID
        stripe_customer_id = data.get("customer")
        print(f"✅ Checkout completed for: {customer_email}")

        user = db.query(User).filter(User.email == customer_email).first()
        if user and stripe_subscription_id:
            # Fetch the full subscription object from Stripe
            sub = stripe.Subscription.retrieve(stripe_subscription_id)
            stripe_price_id = sub["items"]["data"][0]["price"]["id"]
            status = sub.get("status", "unknown")

            start_date = datetime.utcfromtimestamp(sub.get("start_date", datetime.utcnow().timestamp()))
            end_date = datetime.utcfromtimestamp(sub.get("current_period_end", datetime.utcnow().timestamp()))

            # Find the plan in our database by stripe_price_id
            plan = db.query(Plan).filter(Plan.stripe_price_id == stripe_price_id).first()
            plan_id = plan.id if plan else None

            # Create or update the subscription record
            db_subscription = (
                db.query(Subscription).filter(Subscription.user_id == user.id).first()
            )
            if db_subscription:
                db_subscription.plan_id = plan_id
                db_subscription.stripe_subscription_id = stripe_subscription_id
                db_subscription.stripe_customer_id = stripe_customer_id
                db_subscription.status = status
                db_subscription.start_date = start_date
                db_subscription.end_date = end_date
            else:
                db_subscription = Subscription(
                    user_id=user.id,
                    plan_id=plan_id,
                    stripe_subscription_id=stripe_subscription_id,
                    stripe_customer_id=stripe_customer_id,
                    status=status,
                    start_date=start_date,
                    end_date=end_date,
                )
                db.add(db_subscription)

            db.commit()
            print(f"💾 Subscription saved for {customer_email} - Plan: {plan.name if plan else 'Unknown'} ({plan.billing_cycle if plan else 'N/A'})")


    elif event_type == "customer.subscription.updated":
        stripe_sub_id = data["id"]
        status = data["status"]
        stripe_price_id = data["items"]["data"][0]["price"]["id"]

        print(f"🔁 Subscription updated: {stripe_sub_id} → {status}")

        # Find plan by stripe_price_id
        plan = db.query(Plan).filter(Plan.stripe_price_id == stripe_price_id).first()

        # Update DB entry
        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_sub_id
        ).first()
        if db_subscription:
            db_subscription.status = status
            if plan:
                db_subscription.plan_id = plan.id
            db_subscription.updated_at = datetime.utcnow()
            db.commit()
            print(f"✅ Updated subscription status to {status}")

    elif event_type == "customer.subscription.deleted":
        stripe_sub_id = data["id"]
        print(f"❌ Subscription canceled: {stripe_sub_id}")
        
        # Mark as canceled
        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_sub_id
        ).first()
        if db_subscription:
            db_subscription.status = "canceled"
            db.commit()
            print(f"✅ Marked subscription as canceled")

    elif event_type == "invoice.payment_failed":
        print(f"⚠️ Payment failed for subscription: {data.get('subscription')}")

    elif event_type == "invoice.payment_succeeded":
        print(f"💰 Payment succeeded for invoice: {data['id']}")

    return {"status": "success"}
