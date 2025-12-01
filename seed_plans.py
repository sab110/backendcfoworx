# seed_plans.py
from db import SessionLocal
from models import Plan

def seed_plans():
    db = SessionLocal()
    
    # Check if plans already exist
    existing_plans = db.query(Plan).count()
    if existing_plans > 0:
        print(f"✅ Plans already exist ({existing_plans} plans found). Skipping seed.")
        db.close()
        return
    
    plans_data = [
        # Standard Plans
        {
            "name": "Standard",
            "billing_cycle": "monthly",
            "price": "$39/mo",
            "stripe_price_id": "price_1SHskmLByti58Oj8nuGBedKQ"
        },
        {
            "name": "Standard",
            "billing_cycle": "6-month",
            "price": "$222/6mo",
            "stripe_price_id": "price_1SHslKLByti58Oj83fqBaoFZ"
        },
        {
            "name": "Standard",
            "billing_cycle": "annual",
            "price": "$408/yr",
            "stripe_price_id": "price_1SHslhLByti58Oj8LrGoCKbd"
        },
        # Pro Plans
        {
            "name": "Pro",
            "billing_cycle": "monthly",
            "price": "$45/mo",
            "stripe_price_id": "price_1SHsmhLByti58Oj8lHK4IN1A"
        },
        {
            "name": "Pro",
            "billing_cycle": "6-month",
            "price": "$258/6mo",
            "stripe_price_id": "price_1SHsmzLByti58Oj8giCRcZBl"
        },
        {
            "name": "Pro",
            "billing_cycle": "annual",
            "price": "$480/yr",
            "stripe_price_id": "price_1SHsnRLByti58Oj8tssO47kg"
        },
    ]
    
    try:
        for plan_data in plans_data:
            plan = Plan(**plan_data)
            db.add(plan)
        
        db.commit()
        print(f"✅ Successfully seeded {len(plans_data)} plans!")
        
        # Display created plans
        all_plans = db.query(Plan).all()
        for plan in all_plans:
            print(f"   - {plan.name} ({plan.billing_cycle}): {plan.price} [ID: {plan.id}]")
    
    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding plans: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_plans()

