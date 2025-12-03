from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import CompanyInfo, Subscription, Plan, User, QuickBooksToken, FailedPaymentLog, EmailPreference
import stripe
from datetime import datetime
from config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, FRONTEND_URL


router = APIRouter()
stripe.api_key = STRIPE_SECRET_KEY


def send_subscription_email(db: Session, realm_id: str, email_type: str, extra_data: dict = None):
    """
    Helper to send subscription-related emails.
    email_type: 'subscription_created', 'subscription_renewed', 'subscription_canceled', 'payment_failed'
    
    Sends to USER email (the person who logged in), not company email.
    """
    try:
        from services.email_service import email_service
        
        # Get company info
        company = db.query(CompanyInfo).filter(CompanyInfo.realm_id == realm_id).first()
        if not company:
            print(f"⚠️ Cannot send email: Company not found for realm_id {realm_id}")
            return False
        
        company_name = company.company_name or "Your Company"
        
        # First, try to get the USER email (the person who signed in)
        qb_token = db.query(QuickBooksToken).filter(QuickBooksToken.realm_id == realm_id).first()
        user_email = None
        if qb_token:
            user = db.query(User).filter(User.id == qb_token.user_id).first()
            if user and user.email:
                user_email = user.email
                print(f"📧 Found user email: {user_email}")
        
        # Get email preference recipients (for those who want billing emails)
        email_prefs = db.query(EmailPreference).filter(
            EmailPreference.realm_id == realm_id,
            EmailPreference.receive_billing == "true"
        ).all()
        
        recipients = [pref.email for pref in email_prefs]
        
        # Add user email if not already in recipients
        if user_email and user_email not in recipients:
            recipients.insert(0, user_email)  # Put user email first
        
        # Fallback to company email if no recipients found
        if not recipients:
            if company.email:
                recipients = [company.email]
            elif company.customer_communication_email:
                recipients = [company.customer_communication_email]
        
        if not recipients:
            print(f"⚠️ No email recipients found for realm_id {realm_id}")
            return False
        
        print(f"📧 Sending {email_type} email to: {recipients}")
        
        # Send appropriate email based on type
        if email_type == "subscription_created":
            result = email_service.send_billing_notification(
                to=recipients,
                company_name=company_name,
                notification_type="subscription_renewed",  # Using "renewed" template for new subscriptions too
                details=extra_data or {},
                db=db,
                realm_id=realm_id,
            )
        elif email_type == "subscription_canceled":
            # Custom cancellation email
            subject = "⚠️ Your CFO Worx Subscription Has Been Canceled"
            html = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"></head>
            <body style="margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; background-color: #f4f7fa;">
                <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                    <div style="background: #dc2626; border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                        <h1 style="color: #fff; margin: 0; font-size: 28px;">⚠️ Subscription Canceled</h1>
                    </div>
                    <div style="background: #fff; padding: 40px 30px; border-radius: 0 0 16px 16px;">
                        <p style="color: #334155; font-size: 16px;">Hi <strong>{company_name}</strong>,</p>
                        <p style="color: #334155; font-size: 16px;">Your CFO Worx subscription has been canceled. You will lose access to premium features at the end of your current billing period.</p>
                        <p style="color: #334155; font-size: 16px;">If this was a mistake or you'd like to resubscribe, you can do so from your dashboard.</p>
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{FRONTEND_URL}/subscribe" style="display: inline-block; background: #2563eb; color: #fff; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 600;">Resubscribe Now</a>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
            result = email_service.send_email(
                to=recipients,
                subject=subject,
                html=html,
                db=db,
                realm_id=realm_id,
                email_type="billing",
            )
        elif email_type == "payment_failed":
            result = email_service.send_billing_notification(
                to=recipients,
                company_name=company_name,
                notification_type="payment_failed",
                details=extra_data or {},
                db=db,
                realm_id=realm_id,
            )
        elif email_type == "payment_succeeded":
            result = email_service.send_billing_notification(
                to=recipients,
                company_name=company_name,
                notification_type="subscription_renewed",
                details=extra_data or {},
                db=db,
                realm_id=realm_id,
            )
        elif email_type == "subscription_updated":
            # Custom subscription updated email
            details = extra_data or {}
            subject = "📋 Your CFO Worx Subscription Has Been Updated"
            html = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"></head>
            <body style="margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; background-color: #f4f7fa;">
                <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                    <div style="background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                        <h1 style="color: #fff; margin: 0; font-size: 28px;">📋 Subscription Updated</h1>
                    </div>
                    <div style="background: #fff; padding: 40px 30px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                        <p style="color: #334155; font-size: 16px;">Hi <strong>{company_name}</strong>,</p>
                        <p style="color: #334155; font-size: 16px;">Your CFO Worx subscription has been updated. Here are the details:</p>
                        <div style="background: #f8fafc; border-radius: 8px; padding: 20px; margin: 20px 0;">
                            <p style="margin: 8px 0; color: #334155;"><strong>Plan:</strong> {details.get('plan', 'N/A')}</p>
                            <p style="margin: 8px 0; color: #334155;"><strong>Licenses:</strong> {details.get('quantity', 1)}</p>
                            <p style="margin: 8px 0; color: #334155;"><strong>Status:</strong> <span style="color: {'#16a34a' if details.get('status') == 'active' else '#d97706'};">{details.get('status', 'N/A').upper()}</span></p>
                        </div>
                        <p style="color: #64748b; font-size: 14px;">You can view and manage your subscription from your dashboard.</p>
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{FRONTEND_URL}/dashboard" style="display: inline-block; background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: #fff; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 600;">Go to Dashboard</a>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
            result = email_service.send_email(
                to=recipients,
                subject=subject,
                html=html,
                db=db,
                realm_id=realm_id,
                email_type="billing",
            )
        else:
            print(f"⚠️ Unknown email type: {email_type}")
            return False
        
        if result.get("success"):
            print(f"✅ {email_type} email sent successfully")
            return True
        else:
            print(f"❌ Failed to send {email_type} email: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error sending {email_type} email: {str(e)}")
        return False


# --------------------------------------------------------------------
#  POST /api/stripe/create-checkout-session
# --------------------------------------------------------------------
@router.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    data = await request.json()
    price_id = data.get("priceId")
    email = data.get("email")
    realm_id = data.get("realm_id")  # Company identifier
    quantity = data.get("quantity", 1)  # Number of licenses (default to 1)

    if not price_id or not email or not realm_id:
        raise HTTPException(status_code=400, detail="Missing required fields: priceId, email, realm_id")
    
    # Validate quantity
    if quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")
    
    print(f"🛒 Creating checkout session:")
    print(f"   Price ID: {price_id}")
    print(f"   Email: {email}")
    print(f"   Realm ID: {realm_id}")
    print(f"   Quantity (licenses): {quantity}")
    print(f"   Quantity type: {type(quantity)}")

    try:
        # Ensure quantity is an integer
        quantity = int(quantity) if quantity else 1
        print(f"   Quantity after conversion: {quantity} (type: {type(quantity)})")
        
        session = stripe.checkout.Session.create(
            success_url=f"{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/cancel",
            mode="subscription",
            payment_method_types=["card"],
            customer_email=email,
            line_items=[{"price": price_id, "quantity": quantity}],
            metadata={
                "realm_id": realm_id,  # Store company identifier
                "quantity": str(quantity)  # Store quantity for reference
            }
        )
        print(f"✅ Checkout session created: {session.id}")
        print(f"   Session URL: {session.url}")
        print(f"   Line items: {session.line_items if hasattr(session, 'line_items') else 'Not available in response'}")
        
        # Log what we're sending to verify
        print(f"📦 Stripe checkout configured with:")
        print(f"   - Price: {price_id}")
        print(f"   - Quantity: {quantity}")
        print(f"   - Total: ${quantity} × price")
        
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        print(f"❌ Error creating checkout session: {str(e)}")
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
        realm_id = data.get("metadata", {}).get("realm_id")  # Get company realm_id from metadata
        
        print(f"✅ Checkout completed for: {customer_email} (Company realm_id: {realm_id})")

        # If no realm_id in metadata, try to find it from the user's QuickBooks token
        if not realm_id:
            print("⚠️  No realm_id in checkout session metadata. Attempting to find via email...")
            
            # Try to find user by email and get their realm_id from QuickBooks tokens
            user = db.query(User).filter(User.email == customer_email).first()
            if user:
                # Find any QuickBooks token for this user
                qb_token = db.query(QuickBooksToken).filter(QuickBooksToken.user_id == user.id).first()
                if qb_token:
                    realm_id = qb_token.realm_id
                    print(f"✅ Found realm_id via user email: {realm_id}")
            
            # If still no realm_id, log warning and skip subscription creation
            if not realm_id:
                print(f"⚠️  Could not find realm_id for customer: {customer_email}")
                print(f"   Subscription created in Stripe: {stripe_subscription_id}")
                print(f"   Manual intervention required - assign subscription to company manually")
                
                # Don't fail the webhook, just log it
                return {
                    "status": "warning",
                    "message": "Subscription created but not linked to company - missing realm_id",
                    "stripe_subscription_id": stripe_subscription_id,
                    "customer_email": customer_email
                }

        # Verify company exists
        company = db.query(CompanyInfo).filter(CompanyInfo.realm_id == realm_id).first()
        if not company:
            print(f"⚠️  Company not found for realm_id: {realm_id}")
            print(f"   Creating placeholder - admin should verify")
            # Don't fail, just log
            return {
                "status": "warning", 
                "message": "Company not found in database",
                "realm_id": realm_id
            }

        if stripe_subscription_id:
            # Fetch the full subscription object from Stripe
            sub = stripe.Subscription.retrieve(stripe_subscription_id)
            stripe_price_id = sub["items"]["data"][0]["price"]["id"]
            status = sub.get("status", "unknown")

            # Parse dates from Stripe subscription
            print(f"📋 Stripe subscription dates:")
            print(f"   start_date: {sub.get('start_date')}")
            print(f"   created: {sub.get('created')}")
            print(f"   current_period_start: {sub.get('current_period_start')}")
            print(f"   current_period_end: {sub.get('current_period_end')}")
            
            start_timestamp = sub.get("start_date") or sub.get("created")
            end_timestamp = sub.get("current_period_end")
            
            if not start_timestamp:
                print(f"⚠️  Critical: Missing start_date in Stripe subscription")
                return {"status": "error", "message": "Missing start_date"}
            
            start_date = datetime.utcfromtimestamp(start_timestamp)
            
            # If current_period_end is missing, calculate from billing interval
            if not end_timestamp:
                print(f"⚠️  current_period_end missing, calculating from billing interval...")
                
                try:
                    # Get billing interval from price
                    price = sub["items"]["data"][0]["price"]
                    if price.get("recurring"):
                        interval = price["recurring"]["interval"]
                        interval_count = price["recurring"].get("interval_count", 1)
                        
                        print(f"   Billing: {interval_count} {interval}(s)")
                        
                        # Calculate end date
                        from dateutil.relativedelta import relativedelta
                        from datetime import timedelta as td
                        
                        if interval == 'month':
                            end_date = start_date + relativedelta(months=interval_count)
                        elif interval == 'year':
                            end_date = start_date + relativedelta(years=interval_count)
                        elif interval == 'week':
                            end_date = start_date + td(weeks=interval_count)
                        elif interval == 'day':
                            end_date = start_date + td(days=interval_count)
                        else:
                            print(f"❌ Unknown interval: {interval}")
                            return {"status": "error", "message": f"Unknown billing interval: {interval}"}
                        
                        print(f"   Calculated end_date: {end_date}")
                    else:
                        print(f"❌ Not a recurring subscription")
                        return {"status": "error", "message": "Not a recurring subscription"}
                except Exception as calc_error:
                    print(f"❌ Error calculating end_date: {str(calc_error)}")
                    return {"status": "error", "message": f"Cannot calculate end_date: {str(calc_error)}"}
            else:
                end_date = datetime.utcfromtimestamp(end_timestamp)
            
            print(f"📅 Subscription dates: Start={start_date}, End={end_date}")

            # Get quantity from subscription
            quantity = sub["items"]["data"][0]["quantity"] if sub.get("items") and sub["items"].get("data") else 1
            print(f"   Quantity: {quantity} licenses")
            
            # Find the plan in our database by stripe_price_id
            plan = db.query(Plan).filter(Plan.stripe_price_id == stripe_price_id).first()
            plan_id = plan.id if plan else None

            # Create or update the subscription record (company-level)
            db_subscription = (
                db.query(Subscription).filter(Subscription.realm_id == realm_id).first()
            )
            if db_subscription:
                db_subscription.plan_id = plan_id
                db_subscription.stripe_subscription_id = stripe_subscription_id
                db_subscription.stripe_customer_id = stripe_customer_id
                db_subscription.status = status
                db_subscription.quantity = quantity
                db_subscription.start_date = start_date
                db_subscription.end_date = end_date
            else:
                db_subscription = Subscription(
                    realm_id=realm_id,
                    plan_id=plan_id,
                    stripe_subscription_id=stripe_subscription_id,
                    stripe_customer_id=stripe_customer_id,
                    status=status,
                    quantity=quantity,
                    start_date=start_date,
                    end_date=end_date,
                )
                db.add(db_subscription)

            db.commit()
            print(f"💾 Subscription saved for company {company.company_name} (realm_id: {realm_id}) - Plan: {plan.name if plan else 'Unknown'} ({plan.billing_cycle if plan else 'N/A'}) × {quantity} licenses")
            
            # Send subscription confirmation email
            send_subscription_email(
                db=db,
                realm_id=realm_id,
                email_type="subscription_created",
                extra_data={
                    "plan": plan.name if plan else "Unknown",
                    "quantity": quantity,
                }
            )


    elif event_type == "customer.subscription.updated":
        stripe_sub_id = data["id"]
        status = data["status"]
        stripe_price_id = data["items"]["data"][0]["price"]["id"]

        print(f"🔁 Subscription updated: {stripe_sub_id} → {status}")
        print(f"   New price: {stripe_price_id}")

        # Fetch full subscription object to get updated dates
        sub = stripe.Subscription.retrieve(stripe_sub_id)
        
        # Parse dates (same logic as checkout)
        start_timestamp = sub.get("start_date") or sub.get("created")
        end_timestamp = sub.get("current_period_end")
        
        start_date = datetime.utcfromtimestamp(start_timestamp) if start_timestamp else None
        
        # Calculate end_date if missing
        if not end_timestamp:
            print(f"⚠️  current_period_end missing, calculating from billing interval...")
            try:
                price = sub["items"]["data"][0]["price"]
                if price.get("recurring"):
                    interval = price["recurring"]["interval"]
                    interval_count = price["recurring"].get("interval_count", 1)
                    
                    from dateutil.relativedelta import relativedelta
                    from datetime import timedelta as td
                    
                    if interval == 'month':
                        end_date = start_date + relativedelta(months=interval_count)
                    elif interval == 'year':
                        end_date = start_date + relativedelta(years=interval_count)
                    elif interval == 'week':
                        end_date = start_date + td(weeks=interval_count)
                    elif interval == 'day':
                        end_date = start_date + td(days=interval_count)
                    else:
                        end_date = None
                        print(f"❌ Unknown interval: {interval}")
                else:
                    end_date = None
            except Exception as calc_error:
                print(f"❌ Error calculating end_date: {str(calc_error)}")
                end_date = None
        else:
            end_date = datetime.utcfromtimestamp(end_timestamp)
        
        print(f"📅 Updated dates: Start={start_date}, End={end_date}")
        
        # Get quantity from subscription
        quantity = sub["items"]["data"][0]["quantity"] if sub.get("items") and sub["items"].get("data") else 1
        print(f"   Quantity: {quantity} licenses")

        # Find plan by stripe_price_id
        plan = db.query(Plan).filter(Plan.stripe_price_id == stripe_price_id).first()

        # Update DB entry
        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_sub_id
        ).first()
        if db_subscription:
            old_status = db_subscription.status
            old_quantity = db_subscription.quantity
            
            db_subscription.status = status
            if plan:
                db_subscription.plan_id = plan.id
            if start_date:
                db_subscription.start_date = start_date
            if end_date:
                db_subscription.end_date = end_date
            db_subscription.quantity = quantity
            db_subscription.updated_at = datetime.utcnow()
            db.commit()
            print(f"✅ Updated subscription: status={status}, plan={plan.name if plan else 'Unknown'}, quantity={quantity}, next_billing={end_date}")
            
            # Send subscription updated email
            send_subscription_email(
                db=db,
                realm_id=db_subscription.realm_id,
                email_type="subscription_updated",
                extra_data={
                    "plan": plan.name if plan else "Unknown",
                    "quantity": quantity,
                    "status": status,
                    "old_status": old_status,
                    "old_quantity": old_quantity,
                }
            )
        else:
            print(f"⚠️  Subscription not found in database: {stripe_sub_id}")

    elif event_type == "customer.subscription.deleted":
        stripe_sub_id = data["id"]
        print(f"❌ Subscription canceled: {stripe_sub_id}")
        
        # Mark as canceled
        db_subscription = db.query(Subscription).filter(
            Subscription.stripe_subscription_id == stripe_sub_id
        ).first()
        if db_subscription:
            realm_id = db_subscription.realm_id
            db_subscription.status = "canceled"
            db.commit()
            print(f"✅ Marked subscription as canceled")
            
            # Send cancellation email
            send_subscription_email(
                db=db,
                realm_id=realm_id,
                email_type="subscription_canceled",
            )

    elif event_type == "invoice.payment_failed":
        print(f"⚠️ Payment failed for subscription: {data.get('subscription')}")
        
        # Log the failed payment
        try:
            invoice_id = data.get("id")
            subscription_id = data.get("subscription")
            customer_id = data.get("customer")
            amount = data.get("amount_due", 0)
            currency = data.get("currency", "usd")
            
            # Get failure details
            charge = data.get("charge")
            failure_code = None
            failure_message = "Payment failed"
            
            if charge:
                try:
                    charge_obj = stripe.Charge.retrieve(charge)
                    failure_code = charge_obj.get("failure_code")
                    failure_message = charge_obj.get("failure_message") or "Payment failed"
                except:
                    pass
            
            # Get customer email
            customer_email = data.get("customer_email")
            if not customer_email and customer_id:
                try:
                    customer = stripe.Customer.retrieve(customer_id)
                    customer_email = customer.email
                except:
                    pass
            
            # Find realm_id and company name
            realm_id = None
            company_name = None
            if subscription_id:
                sub = db.query(Subscription).filter(
                    Subscription.stripe_subscription_id == subscription_id
                ).first()
                if sub:
                    realm_id = sub.realm_id
                    company = db.query(CompanyInfo).filter(
                        CompanyInfo.realm_id == realm_id
                    ).first()
                    if company:
                        company_name = company.company_name
            
            # Create failed payment log
            failed_log = FailedPaymentLog(
                realm_id=realm_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                stripe_invoice_id=invoice_id,
                amount=amount,
                currency=currency,
                failure_code=failure_code,
                failure_message=failure_message,
                customer_email=customer_email,
                company_name=company_name,
                failed_at=datetime.utcnow()
            )
            db.add(failed_log)
            db.commit()
            print(f"📝 Logged failed payment: {invoice_id}")
            
            # Send payment failed email
            if realm_id:
                send_subscription_email(
                    db=db,
                    realm_id=realm_id,
                    email_type="payment_failed",
                    extra_data={
                        "failure_message": failure_message,
                        "amount": amount,
                    }
                )
            
        except Exception as log_error:
            print(f"❌ Error logging failed payment: {str(log_error)}")

    elif event_type == "invoice.payment_succeeded":
        print(f"💰 Payment succeeded for invoice: {data['id']}")
        
        # Send payment success email for renewal (not for first payment which is handled by checkout.session.completed)
        subscription_id = data.get("subscription")
        if subscription_id:
            # Check if this is a renewal (subscription already exists in our DB)
            db_subscription = db.query(Subscription).filter(
                Subscription.stripe_subscription_id == subscription_id
            ).first()
            
            # Only send renewal email if subscription exists and this isn't the first payment
            billing_reason = data.get("billing_reason")
            if db_subscription and billing_reason in ["subscription_cycle", "subscription_update"]:
                send_subscription_email(
                    db=db,
                    realm_id=db_subscription.realm_id,
                    email_type="payment_succeeded",
                )

    return {"status": "success"}
