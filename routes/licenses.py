from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from db import get_db
from models import License, CompanyLicenseMapping, CompanyInfo, QuickBooksToken
from datetime import datetime, timedelta
import requests
import re
from config import ENVIRONMENT

router = APIRouter()


@router.get("/all")
async def get_all_licenses(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Get all licenses with pagination
    """
    total = db.query(License).count()
    licenses = db.query(License).offset(skip).limit(limit).all()
    
    results = []
    for lic in licenses:
        results.append({
            "id": lic.id,
            "franchise_number": lic.franchise_number,
            "name": lic.name,
            "owner": lic.owner,
            "address": lic.address,
            "city": lic.city,
            "state": lic.state,
            "zip_code": lic.zip_code,
            "created_at": lic.created_at.isoformat() if lic.created_at else None,
            "updated_at": lic.updated_at.isoformat() if lic.updated_at else None
        })
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "licenses": results
    }


@router.get("/search")
async def search_licenses(
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db)
):
    """
    Search licenses by franchise number, name, owner, city, or state
    """
    search_pattern = f"%{query}%"
    
    licenses = db.query(License).filter(
        (License.franchise_number.ilike(search_pattern)) |
        (License.name.ilike(search_pattern)) |
        (License.owner.ilike(search_pattern)) |
        (License.city.ilike(search_pattern)) |
        (License.state.ilike(search_pattern))
    ).limit(50).all()
    
    results = []
    for lic in licenses:
        results.append({
            "id": lic.id,
            "franchise_number": lic.franchise_number,
            "name": lic.name,
            "owner": lic.owner,
            "address": lic.address,
            "city": lic.city,
            "state": lic.state,
            "zip_code": lic.zip_code
        })
    
    return {
        "query": query,
        "count": len(results),
        "licenses": results
    }


@router.get("/{franchise_number}")
async def get_license_by_number(
    franchise_number: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific license by franchise number
    """
    license = db.query(License).filter(
        License.franchise_number == franchise_number
    ).first()
    
    if not license:
        raise HTTPException(
            status_code=404,
            detail=f"License not found for franchise number: {franchise_number}"
        )
    
    return {
        "id": license.id,
        "franchise_number": license.franchise_number,
        "name": license.name,
        "owner": license.owner,
        "address": license.address,
        "city": license.city,
        "state": license.state,
        "zip_code": license.zip_code,
        "created_at": license.created_at.isoformat() if license.created_at else None,
        "updated_at": license.updated_at.isoformat() if license.updated_at else None
    }


@router.get("/state/{state_code}")
async def get_licenses_by_state(
    state_code: str,
    db: Session = Depends(get_db)
):
    """
    Get all licenses for a specific state
    """
    licenses = db.query(License).filter(
        License.state == state_code.upper()
    ).all()
    
    results = []
    for lic in licenses:
        results.append({
            "id": lic.id,
            "franchise_number": lic.franchise_number,
            "name": lic.name,
            "owner": lic.owner,
            "city": lic.city,
            "state": lic.state
        })
    
    return {
        "state": state_code.upper(),
        "count": len(results),
        "licenses": results
    }


# ------------------------------------------------------
# Save Selected Licenses for User
# ------------------------------------------------------
@router.post("/company/{realm_id}/select-licenses")
async def save_selected_licenses(
    realm_id: str,
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Save the user's selected licenses (franchise numbers).
    This is used during onboarding when users choose which licenses to work with.
    Also marks company onboarding as completed.
    """
    selected_franchise_numbers = payload.get("franchise_numbers", [])
    
    if not selected_franchise_numbers:
        raise HTTPException(status_code=400, detail="No franchise numbers provided")
    
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Get all mappings for this company
    all_mappings = db.query(CompanyLicenseMapping).filter_by(realm_id=realm_id).all()
    
    # Update is_active status based on selection
    updated_count = 0
    for mapping in all_mappings:
        if mapping.franchise_number in selected_franchise_numbers:
            mapping.is_active = "true"
            updated_count += 1
        else:
            mapping.is_active = "false"
    
    # Mark onboarding as completed for this company
    onboarding_just_completed = False
    if company.onboarding_completed != "true":
        company.onboarding_completed = "true"
        company.onboarding_completed_at = datetime.utcnow()
        onboarding_just_completed = True
        print(f"✅ Onboarding completed for company: {company.company_name} (realm_id: {realm_id})")
    
    db.commit()
    
    # Send onboarding completion email
    if onboarding_just_completed:
        try:
            from services.email_service import email_service
            from models import EmailPreference
            
            # Get email recipients
            email_prefs = db.query(EmailPreference).filter(
                EmailPreference.realm_id == realm_id,
                EmailPreference.receive_notifications == "true"
            ).all()
            
            recipients = [pref.email for pref in email_prefs]
            if not recipients:
                if company.email:
                    recipients = [company.email]
                elif company.customer_communication_email:
                    recipients = [company.customer_communication_email]
            
            if recipients:
                from config import FRONTEND_URL
                company_name = company.company_name or "Your Company"
                
                html = f"""
                <!DOCTYPE html>
                <html>
                <head><meta charset="utf-8"></head>
                <body style="margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; background-color: #f4f7fa;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                        <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                            <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 700;">
                                🎉 Onboarding Complete!
                            </h1>
                            <p style="color: #a7f3d0; margin: 10px 0 0 0; font-size: 16px;">
                                You're all set up and ready to go
                            </p>
                        </div>
                        <div style="background-color: #ffffff; padding: 40px 30px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                            <p style="color: #334155; font-size: 16px; line-height: 1.6;">
                                Hi <strong>{company_name}</strong>,
                            </p>
                            <p style="color: #334155; font-size: 16px; line-height: 1.6;">
                                Congratulations! Your onboarding is now complete. You've successfully:
                            </p>
                            <ul style="color: #334155; font-size: 15px; line-height: 1.8;">
                                <li>Connected your QuickBooks account</li>
                                <li>Selected {updated_count} franchise location(s)</li>
                                <li>Configured your department mappings</li>
                            </ul>
                            <p style="color: #334155; font-size: 16px; line-height: 1.6;">
                                You can now start generating royalty reports from your dashboard.
                            </p>
                            <div style="text-align: center; margin: 30px 0;">
                                <a href="{FRONTEND_URL}/dashboard" 
                                   style="display: inline-block; background: linear-gradient(135deg, #1a365d 0%, #2d5a87 100%); color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 16px;">
                                    Go to Dashboard →
                                </a>
                            </div>
                        </div>
                    </div>
                </body>
                </html>
                """
                
                result = email_service.send_email(
                    to=recipients,
                    subject=f"🎉 Onboarding Complete - {company_name}",
                    html=html,
                    db=db,
                    realm_id=realm_id,
                    email_type="notification",
                )
                if result.get("success"):
                    print(f"✅ Onboarding completion email sent to {recipients}")
                else:
                    print(f"⚠️ Failed to send onboarding email: {result.get('error')}")
        except Exception as e:
            print(f"⚠️ Error sending onboarding completion email: {str(e)}")
    
    return {
        "message": "License selection saved successfully",
        "realm_id": realm_id,
        "total_licenses": len(all_mappings),
        "selected_count": updated_count,
        "selected_franchise_numbers": selected_franchise_numbers,
        "onboarding_completed": True
    }


@router.get("/company/{realm_id}/selected")
async def get_selected_licenses(realm_id: str, db: Session = Depends(get_db)):
    """
    Get only the selected (active) licenses for a company.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Get active mappings
    mappings = db.query(CompanyLicenseMapping).filter_by(
        realm_id=realm_id,
        is_active="true"
    ).all()
    
    # Build response
    licenses_data = []
    for mapping in mappings:
        license_entry = db.query(License).filter_by(
            franchise_number=mapping.franchise_number
        ).first()
        
        if license_entry:
            licenses_data.append({
                "franchise_number": license_entry.franchise_number,
                "name": license_entry.name,
                "owner": license_entry.owner,
                "city": license_entry.city,
                "state": license_entry.state,
                "quickbooks": {
                    "department_name": mapping.qbo_department_name,
                    "is_active": mapping.is_active
                }
            })
    
    return {
        "realm_id": realm_id,
        "company_name": company.company_name,
        "count": len(licenses_data),
        "licenses": licenses_data
    }


# ------------------------------------------------------
# COMPANY LICENSE MAPPING ENDPOINTS
# ------------------------------------------------------

def extract_franchise_number(department_name: str):
    """
    Extract franchise number from department name.
    Examples:
    - "Sooland 10516" -> "10516"
    - "Grand Island & Hastings 11024" -> "11024"
    - "Lincoln East 10861" -> "10861"
    """
    # Look for 4-5 digit numbers at the end of the string
    match = re.search(r'\b(\d{4,5})\b', department_name)
    if match:
        return match.group(1)
    return None


@router.post("/map-company-licenses/{realm_id}")
async def map_company_licenses(realm_id: str, db: Session = Depends(get_db)):
    """
    Fetch departments from QuickBooks, extract franchise numbers,
    and create mappings to licenses in the database.
    """
    # --- 1. Get QuickBooks token ---
    token_entry = db.query(QuickBooksToken).filter_by(realm_id=realm_id).first()
    if not token_entry:
        raise HTTPException(status_code=404, detail="No QuickBooks token found for this realm ID")

    # --- 2. Refresh token if expired ---
    if token_entry.is_expired():
        print(f"🔄 Token expired for {realm_id}, refreshing...")
        from routes.quickbooks_auth import get_auth_client
        try:
            auth_client = get_auth_client()
            auth_client.refresh(refresh_token=token_entry.refresh_token)
            token_entry.access_token = auth_client.access_token
            token_entry.refresh_token = auth_client.refresh_token
            token_entry.expires_at = datetime.utcnow() + timedelta(seconds=3600)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=401, detail=f"Token refresh failed: {e}")

    # --- 3. Determine API base URL ---
    base_url = (
        "https://sandbox-quickbooks.api.intuit.com"
        if ENVIRONMENT == "sandbox"
        else "https://quickbooks.api.intuit.com"
    )

    # --- 4. Query Departments from QuickBooks ---
    departments_url = f"{base_url}/v3/company/{realm_id}/query"
    headers = {
        "Authorization": f"Bearer {token_entry.access_token}",
        "Accept": "application/json"
    }
    params = {
        "query": "select * from Department",
        "minorversion": "75"
    }

    try:
        print(f"🔍 Fetching departments for realm_id: {realm_id}")
        response = requests.get(departments_url, headers=headers, params=params)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"QuickBooks API error: {response.text}"
            )

        data = response.json()
        print("✅ QuickBooks Departments Response received")

        # --- 5. Extract departments from response ---
        departments = data.get("QueryResponse", {}).get("Department", [])
        if not departments:
            return {
                "message": "No departments found in QuickBooks",
                "mapped": 0,
                "skipped": 0,
                "details": []
            }

        # --- 6. Process each department and create mappings ---
        mapped_count = 0
        skipped_count = 0
        mapping_details = []

        for dept in departments:
            dept_name = dept.get("Name", "")
            dept_id = dept.get("Id", "")
            is_active = dept.get("Active", True)
            
            # Extract franchise number from department name
            franchise_number = extract_franchise_number(dept_name)
            
            if not franchise_number:
                skipped_count += 1
                mapping_details.append({
                    "department_name": dept_name,
                    "status": "skipped",
                    "reason": "No franchise number found in name"
                })
                continue
            
            # Check if license exists in database
            license_entry = db.query(License).filter_by(franchise_number=franchise_number).first()
            
            if not license_entry:
                skipped_count += 1
                mapping_details.append({
                    "department_name": dept_name,
                    "franchise_number": franchise_number,
                    "status": "skipped",
                    "reason": "License not found in database"
                })
                continue
            
            # Create or update mapping
            mapping = db.query(CompanyLicenseMapping).filter_by(
                realm_id=realm_id,
                franchise_number=franchise_number
            ).first()
            
            if mapping:
                # Update existing mapping
                mapping.qbo_department_id = dept_id
                mapping.qbo_department_name = dept_name
                mapping.is_active = str(is_active).lower()
                mapping.last_synced_at = datetime.utcnow()
                mapping.updated_at = datetime.utcnow()
                status = "updated"
            else:
                # Create new mapping
                mapping = CompanyLicenseMapping(
                    realm_id=realm_id,
                    franchise_number=franchise_number,
                    qbo_department_id=dept_id,
                    qbo_department_name=dept_name,
                    is_active=str(is_active).lower(),
                    last_synced_at=datetime.utcnow()
                )
                db.add(mapping)
                status = "created"
            
            mapped_count += 1
            mapping_details.append({
                "department_name": dept_name,
                "franchise_number": franchise_number,
                "license_name": license_entry.name,
                "status": status
            })

        # Commit all mappings
        db.commit()

        return {
            "message": "License mapping completed",
            "realm_id": realm_id,
            "total_departments": len(departments),
            "mapped": mapped_count,
            "skipped": skipped_count,
            "details": mapping_details
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print("❌ Error mapping licenses:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/company/{realm_id}")
async def get_company_licenses(realm_id: str, db: Session = Depends(get_db)):
    """
    Get all licenses mapped to a specific company (realm_id) with metadata.
    Automatically fetches and maps departments if no mappings exist.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(
            status_code=404,
            detail="Company not found. Please fetch company info first."
        )

    # Get all mappings for this company
    mappings = db.query(CompanyLicenseMapping).filter_by(realm_id=realm_id).all()
    
    # If no mappings exist, automatically fetch and map departments
    if not mappings:
        print(f"🔄 No mappings found for {realm_id}. Auto-fetching departments...")
        
        try:
            # Call the mapping function to fetch and create mappings
            mapping_result = await map_company_licenses(realm_id, db)
            
            # If mapping was successful, fetch the mappings again
            if mapping_result.get("mapped", 0) > 0:
                mappings = db.query(CompanyLicenseMapping).filter_by(realm_id=realm_id).all()
                print(f"✅ Auto-mapped {mapping_result['mapped']} licenses")
            else:
                # No departments found or mapped
                return {
                    "realm_id": realm_id,
                    "company_name": company.company_name,
                    "company_email": company.email,
                    "auto_mapped": True,
                    "mapping_result": mapping_result,
                    "count": 0,
                    "licenses": []
                }
        except Exception as e:
            print(f"❌ Auto-mapping failed: {str(e)}")
            # Return empty result with error info
            return {
                "realm_id": realm_id,
                "company_name": company.company_name,
                "company_email": company.email,
                "auto_mapped": False,
                "error": f"Failed to auto-map licenses: {str(e)}",
                "count": 0,
                "licenses": []
            }

    # Build response with license details and metadata
    licenses_data = []
    for mapping in mappings:
        license_entry = db.query(License).filter_by(
            franchise_number=mapping.franchise_number
        ).first()
        
        if license_entry:
            licenses_data.append({
                "franchise_number": license_entry.franchise_number,
                "name": license_entry.name,
                "owner": license_entry.owner,
                "address": license_entry.address,
                "city": license_entry.city,
                "state": license_entry.state,
                "zip_code": license_entry.zip_code,
                "quickbooks": {
                    "department_id": mapping.qbo_department_id,
                    "department_name": mapping.qbo_department_name,
                    "is_active": mapping.is_active,
                    "last_synced_at": mapping.last_synced_at.isoformat() if mapping.last_synced_at else None
                },
                "mapping_created_at": mapping.created_at.isoformat() if mapping.created_at else None,
                "mapping_updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None
            })

    return {
        "realm_id": realm_id,
        "company_name": company.company_name,
        "company_email": company.email,
        "count": len(licenses_data),
        "licenses": licenses_data
    }

