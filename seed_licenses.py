"""
Script to seed licenses table from data.csv
"""

import csv
from db import SessionLocal
from models import License

def seed_licenses():
    db = SessionLocal()
    
    try:
        print("🔄 Loading licenses from data.csv...\n")
        
        # Check if licenses already exist
        existing_count = db.query(License).count()
        if existing_count > 0:
            print(f"⚠️  Found {existing_count} existing licenses in database")
            response = input("Do you want to clear and re-import? (yes/no): ")
            if response.lower() == 'yes':
                print("🗑️  Clearing existing licenses...")
                db.query(License).delete()
                db.commit()
                print("✅ Existing licenses cleared")
            else:
                print("✅ Keeping existing licenses, skipping import")
                return
        
        # Read and import licenses from CSV
        licenses_added = 0
        licenses_skipped = 0
        
        with open('data.csv', 'r', encoding='utf-8-sig') as file:  # utf-8-sig handles BOM
            csv_reader = csv.DictReader(file)
            
            for row in csv_reader:
                # Try both with and without BOM
                franchise_number = row.get('Franchise Number', row.get('\ufeffFranchise Number', '')).strip()
                
                # Skip if no franchise number
                if not franchise_number:
                    licenses_skipped += 1
                    continue
                
                # Create license entry
                license_entry = License(
                    franchise_number=franchise_number,
                    name=row.get('Name', '').strip() or None,
                    owner=row.get('Owner', '').strip() or None,
                    address=row.get('Address', '').strip() or None,
                    city=row.get('City', '').strip() or None,
                    state=row.get('State', '').strip() or None,
                    zip_code=row.get('Zip', '').strip() or None
                )
                
                db.add(license_entry)
                licenses_added += 1
                
                # Commit in batches of 100
                if licenses_added % 100 == 0:
                    db.commit()
                    print(f"   Imported {licenses_added} licenses...")
        
        # Final commit
        db.commit()
        
        print(f"\n✅ License import complete!")
        print(f"   - Added: {licenses_added} licenses")
        if licenses_skipped > 0:
            print(f"   - Skipped: {licenses_skipped} (missing franchise number)")
        
        # Show sample
        print("\n📋 Sample licenses:")
        sample_licenses = db.query(License).limit(5).all()
        for lic in sample_licenses:
            print(f"   {lic.franchise_number}: {lic.name} ({lic.city}, {lic.state})")
        
    except FileNotFoundError:
        print("❌ Error: data.csv file not found!")
        print("   Please ensure data.csv is in the same directory as this script")
    except Exception as e:
        db.rollback()
        print(f"❌ Error importing licenses: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_licenses()

