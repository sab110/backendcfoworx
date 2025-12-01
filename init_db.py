# init_db.py
from db import engine
from models import Base
from seed_plans import seed_plans

print("🔄 Creating database tables...")
Base.metadata.create_all(bind=engine)
print("✅ Tables created successfully!")

print("\n🔄 Seeding plans...")
seed_plans()

print("\n✅ Database initialization complete!")
