"""
Complete Database Reset Script
================================
This script will:
1. Drop ALL existing tables
2. Recreate tables from current models
3. Seed plans data
4. Optionally seed licenses data

⚠️  WARNING: This will DELETE ALL DATA in the database!
"""

from db import engine, Base
from models import (
    User, QuickBooksToken, Plan, Subscription, 
    CompanyInfo, License, CompanyLicenseMapping
)
from seed_plans import seed_plans
from seed_licenses import seed_licenses
import sys

def confirm_reset():
    """Ask user to confirm database reset"""
    print("⚠️  WARNING: This will DELETE ALL DATA in your database!")
    print("\nTables that will be dropped:")
    print("  - users")
    print("  - quickbooks_tokens")
    print("  - plans")
    print("  - subscriptions")
    print("  - company_info")
    print("  - licenses")
    print("  - company_license_mappings")
    print("\n" + "="*60)
    
    response = input("\nAre you sure you want to continue? Type 'YES' to confirm: ")
    return response == "YES"

def reset_database():
    """Drop all tables and recreate them"""
    
    if not confirm_reset():
        print("\n❌ Database reset cancelled.")
        sys.exit(0)
    
    print("\n" + "="*60)
    print("🔄 Starting database reset...")
    print("="*60)
    
    try:
        # Step 1: Drop all tables
        print("\n1️⃣  Dropping all existing tables...")
        Base.metadata.drop_all(bind=engine)
        print("   ✅ All tables dropped successfully")
        
        # Step 2: Create all tables
        print("\n2️⃣  Creating tables from models...")
        Base.metadata.create_all(bind=engine)
        print("   ✅ All tables created successfully")
        
        print("\n   Tables created:")
        print("   ✓ users")
        print("   ✓ quickbooks_tokens")
        print("   ✓ plans")
        print("   ✓ subscriptions (company-level)")
        print("   ✓ company_info")
        print("   ✓ licenses")
        print("   ✓ company_license_mappings")
        
        # Step 3: Seed plans
        print("\n3️⃣  Seeding plans data...")
        seed_plans()
        
        # Step 4: Ask about licenses
        print("\n4️⃣  License data import")
        seed_license_response = input("   Do you want to import license data from data.csv? (yes/no): ")
        if seed_license_response.lower() in ['yes', 'y']:
            print("\n   Importing licenses...")
            seed_licenses()
        else:
            print("   ⏭️  Skipping license import (you can run 'python seed_licenses.py' later)")
        
        print("\n" + "="*60)
        print("✅ Database reset completed successfully!")
        print("="*60)
        
        print("\n📋 Next Steps:")
        print("   1. Start your API server: uvicorn app:app --reload")
        print("   2. Test QuickBooks OAuth: /api/quickbooks/connect")
        print("   3. Fetch company info: POST /api/quickbooks/fetch-company-info/{realm_id}")
        print("   4. Map licenses: POST /api/licenses/map-company-licenses/{realm_id}")
        print("   5. Get company licenses: GET /api/licenses/company/{realm_id}")
        
    except Exception as e:
        print(f"\n❌ Error during database reset: {e}")
        print("\nThe database may be in an inconsistent state.")
        print("Please check the error and try again.")
        sys.exit(1)

if __name__ == "__main__":
    reset_database()

