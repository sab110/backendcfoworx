from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes
from datetime import datetime, timedelta
from config import (
    QUICKBOOKS_CLIENT_ID,
    QUICKBOOKS_CLIENT_SECRET,
    QUICKBOOKS_REDIRECT_URI,
    ENVIRONMENT,
)
from db import get_db
from models import QuickBooksToken, User, CompanyInfo
import requests

router = APIRouter()

# ------------------------------------------------------
# Helper to initialize the Intuit AuthClient
# ------------------------------------------------------
def get_auth_client():
    return AuthClient(
        client_id=QUICKBOOKS_CLIENT_ID,
        client_secret=QUICKBOOKS_CLIENT_SECRET,
        redirect_uri=QUICKBOOKS_REDIRECT_URI,
        environment=ENVIRONMENT,  # "sandbox" or "production"
    )


# ------------------------------------------------------
# Step 1: Redirect user to QuickBooks authorization page
# ------------------------------------------------------
@router.get("/connect")
async def connect_to_quickbooks():
    auth_client = get_auth_client()
    scopes = [Scopes.ACCOUNTING, Scopes.OPENID, Scopes.EMAIL, Scopes.PROFILE]
    return RedirectResponse(auth_client.get_authorization_url(scopes))


# ------------------------------------------------------
# Step 1.5: Handle OAuth callback from QuickBooks and redirect to frontend
# ------------------------------------------------------
@router.get("/oauth-callback")
async def oauth_callback(code: str, realmId: str, state: str = None):
    """
    QuickBooks redirects here after user authorizes.
    We forward the code and realmId to the frontend for token exchange.
    """
    from config import FRONTEND_URL
    
    # Redirect to frontend with the authorization code and realmId
    # frontend_callback_url = f"{FRONTEND_URL}/callback?code={code}&realmId={realmId}"
    frontend_callback_url = (
        f"{FRONTEND_URL}/quickbooks-oauth-callback?code={code}&realmId={realmId}"
    )
    if state:
        frontend_callback_url += f"&state={state}"
    
    return RedirectResponse(frontend_callback_url)


# ------------------------------------------------------
# Step 2: Exchange authCode → access + refresh tokens, and store
# ------------------------------------------------------
@router.post("/store-qbo-oauth")
async def store_qbo_oauth(payload: dict, db: Session = Depends(get_db)):
    code = payload.get("authCode")
    realm_id = payload.get("realm_id")
    user_id = payload.get("user_id")

    if not code or not realm_id or not user_id:
        raise HTTPException(status_code=400, detail="Missing authCode, realm_id, or user_id")

    auth_client = get_auth_client()

    try:
        print(f"🔍 Exchanging code: {code} for realm_id: {realm_id}")
        auth_client.get_bearer_token(code, realm_id=realm_id)

        # --- 1️⃣ Fetch user info from QuickBooks ---
        userinfo_endpoint = (
            "https://sandbox-accounts.platform.intuit.com/v1/openid_connect/userinfo"
            if ENVIRONMENT == "sandbox"
            else "https://accounts.platform.intuit.com/v1/openid_connect/userinfo"
        )

        headers = {"Authorization": f"Bearer {auth_client.access_token}"}
        response = requests.get(userinfo_endpoint, headers=headers)

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get user info: {response.text}",
            )

        user_data = response.json()
        print("✅ QuickBooks User Info:", user_data)

        # --- 2️⃣ Create or update user in your local DB ---
        user = db.query(User).filter_by(id=user_id).first()

        full_name = f"{user_data.get('givenName', '')} {user_data.get('familyName', '')}".strip()
        email = user_data.get("email")
        phone = user_data.get("phoneNumber")

        if not user:
            user = User(id=user_id, email=email, full_name=full_name, role="QuickBooks User")
            db.add(user)
        else:
            user.email = email
            user.full_name = full_name
            if hasattr(user, "phone"):
                user.phone = phone

        # --- 3️⃣ Create or update QuickBooksToken ---
        token_entry = db.query(QuickBooksToken).filter_by(realm_id=realm_id).first()
        if token_entry:
            token_entry.access_token = auth_client.access_token
            token_entry.refresh_token = auth_client.refresh_token
            token_entry.expires_at = datetime.utcnow() + timedelta(seconds=3600)
        else:
            token_entry = QuickBooksToken.create_from_auth_client(
                user_id=user_id, realm_id=realm_id, auth_client=auth_client
            )
            db.add(token_entry)

        db.commit()

        return {
            "message": "QuickBooks connection successful",
            "access_token": auth_client.access_token,
            "realm_id": realm_id,
            "user_id": user_id,
        }

    except Exception as e:
        db.rollback()
        print("❌ OAuth processing error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------
# Step 3: Refresh tokens automatically when expired
# ------------------------------------------------------
@router.post("/refresh-token/{realm_id}")
async def refresh_qbo_token(realm_id: str, db: Session = Depends(get_db)):
    token_entry = db.query(QuickBooksToken).filter_by(realm_id=realm_id).first()
    if not token_entry:
        raise HTTPException(status_code=404, detail="Token not found")

    auth_client = get_auth_client()
    try:
        auth_client.refresh(refresh_token=token_entry.refresh_token)
        token_entry.access_token = auth_client.access_token
        token_entry.refresh_token = auth_client.refresh_token
        token_entry.expires_at = datetime.utcnow() + timedelta(seconds=3600)
        db.commit()

        print(f"✅ Token refreshed for realm_id: {realm_id}")
        return {"access_token": auth_client.access_token}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------
# Step 4: Get QuickBooks user info dynamically (for Dashboard)
# ------------------------------------------------------
@router.get("/qbo-user/{realm_id}")
async def get_qbo_user(
    realm_id: str,
    db: Session = Depends(get_db),
    authorization: str = Header(None),
):
    token_entry = db.query(QuickBooksToken).filter_by(realm_id=realm_id).first()
    if not token_entry:
        raise HTTPException(status_code=404, detail="No QuickBooks token found for this realm ID")

    # --- Refresh if expired ---
    if token_entry.is_expired():
        print(f"🔄 Token expired for {realm_id}, refreshing...")
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

    # --- Determine token source (Header or DB) ---
    access_token = authorization.replace("Bearer ", "") if authorization else token_entry.access_token

    # --- Call QuickBooks UserInfo API ---
    userinfo_endpoint = (
        "https://sandbox-accounts.platform.intuit.com/v1/openid_connect/userinfo"
        if ENVIRONMENT == "sandbox"
        else "https://accounts.platform.intuit.com/v1/openid_connect/userinfo"
    )

    try:
        response = requests.get(userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"})
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"QuickBooks API error: {response.text}")

        data = response.json()

        return {
            "full_name": f"{data.get('givenName', '')} {data.get('familyName', '')}".strip(),
            "email": data.get("email"),
            "role": "QuickBooks User",
            "quickbooks": {
                "realm_id": realm_id,
                "access_token": access_token,
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------
# Step 5: Fetch and Store Company Info from QuickBooks
# ------------------------------------------------------
@router.post("/fetch-company-info/{realm_id}")
async def fetch_company_info(realm_id: str, db: Session = Depends(get_db)):
    """
    Fetches company information from QuickBooks and stores it in the database.
    """
    token_entry = db.query(QuickBooksToken).filter_by(realm_id=realm_id).first()
    if not token_entry:
        raise HTTPException(status_code=404, detail="No QuickBooks token found for this realm ID")

    # --- Refresh if expired ---
    if token_entry.is_expired():
        print(f"🔄 Token expired for {realm_id}, refreshing...")
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

    # --- Determine API base URL ---
    base_url = (
        "https://sandbox-quickbooks.api.intuit.com"
        if ENVIRONMENT == "sandbox"
        else "https://quickbooks.api.intuit.com"
    )

    # --- Query CompanyInfo from QuickBooks ---
    company_info_url = f"{base_url}/v3/company/{realm_id}/query"
    headers = {
        "Authorization": f"Bearer {token_entry.access_token}",
        "Accept": "application/json"
    }
    params = {
        "query": "select * from CompanyInfo",
        "minorversion": "75"
    }

    try:
        print(f"🔍 Fetching company info for realm_id: {realm_id}")
        response = requests.get(company_info_url, headers=headers, params=params)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"QuickBooks API error: {response.text}"
            )

        data = response.json()
        print("✅ QuickBooks Company Info Response:", data)

        # --- Extract CompanyInfo from response ---
        company_data = data.get("QueryResponse", {}).get("CompanyInfo", [])
        if not company_data:
            raise HTTPException(status_code=404, detail="No company info found in QuickBooks response")

        company = company_data[0]  # Get first (and typically only) result

        # --- Parse and store company info ---
        company_info = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()

        # Helper function to extract address
        def parse_address(addr_data):
            if not addr_data:
                return None
            return {
                "id": addr_data.get("Id"),
                "line1": addr_data.get("Line1"),
                "line2": addr_data.get("Line2"),
                "city": addr_data.get("City"),
                "country": addr_data.get("Country"),
                "country_sub_division_code": addr_data.get("CountrySubDivisionCode"),
                "postal_code": addr_data.get("PostalCode")
            }

        # --- Create or update company info ---
        if company_info:
            # Update existing record
            company_info.company_name = company.get("CompanyName")
            company_info.legal_name = company.get("LegalName")
            company_info.employer_id = company.get("EmployerId")
            company_info.company_addr = parse_address(company.get("CompanyAddr"))
            company_info.legal_addr = parse_address(company.get("LegalAddr"))
            company_info.customer_communication_addr = parse_address(company.get("CustomerCommunicationAddr"))
            company_info.email = company.get("Email", {}).get("Address")
            company_info.customer_communication_email = company.get("CustomerCommunicationEmailAddr", {}).get("Address")
            company_info.primary_phone = company.get("PrimaryPhone", {}).get("FreeFormNumber")
            company_info.web_addr = company.get("WebAddr", {}).get("URI")
            company_info.company_start_date = company.get("CompanyStartDate")
            company_info.fiscal_year_start_month = company.get("FiscalYearStartMonth")
            company_info.country = company.get("Country")
            company_info.supported_languages = company.get("SupportedLanguages")
            company_info.default_timezone = company.get("DefaultTimeZone")
            company_info.qbo_id = company.get("Id")
            company_info.sync_token = company.get("SyncToken")
            company_info.domain = company.get("domain")
            company_info.metadata = {
                "name_value": company.get("NameValue", []),
                "meta_data": company.get("MetaData", {}),
                "sparse": company.get("sparse")
            }
            company_info.last_synced_at = datetime.utcnow()
            company_info.updated_at = datetime.utcnow()
        else:
            # Create new record
            company_info = CompanyInfo(
                realm_id=realm_id,
                company_name=company.get("CompanyName"),
                legal_name=company.get("LegalName"),
                employer_id=company.get("EmployerId"),
                company_addr=parse_address(company.get("CompanyAddr")),
                legal_addr=parse_address(company.get("LegalAddr")),
                customer_communication_addr=parse_address(company.get("CustomerCommunicationAddr")),
                email=company.get("Email", {}).get("Address"),
                customer_communication_email=company.get("CustomerCommunicationEmailAddr", {}).get("Address"),
                primary_phone=company.get("PrimaryPhone", {}).get("FreeFormNumber"),
                web_addr=company.get("WebAddr", {}).get("URI"),
                company_start_date=company.get("CompanyStartDate"),
                fiscal_year_start_month=company.get("FiscalYearStartMonth"),
                country=company.get("Country"),
                supported_languages=company.get("SupportedLanguages"),
                default_timezone=company.get("DefaultTimeZone"),
                qbo_id=company.get("Id"),
                sync_token=company.get("SyncToken"),
                domain=company.get("domain"),
                metadata={
                    "name_value": company.get("NameValue", []),
                    "meta_data": company.get("MetaData", {}),
                    "sparse": company.get("sparse")
                },
                last_synced_at=datetime.utcnow()
            )
            db.add(company_info)

        db.commit()
        db.refresh(company_info) if company_info.id else None

        return {
            "message": "Company info fetched and stored successfully",
            "company_info": {
                "company_name": company_info.company_name,
                "legal_name": company_info.legal_name,
                "email": company_info.email,
                "phone": company_info.primary_phone,
                "realm_id": realm_id
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print("❌ Error fetching/storing company info:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------
# Step 6: Get Stored Company Info from DB
# ------------------------------------------------------
@router.get("/company-info/{realm_id}")
async def get_company_info(realm_id: str, db: Session = Depends(get_db)):
    """
    Retrieves stored company information from the database.
    """
    company_info = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    
    if not company_info:
        raise HTTPException(
            status_code=404,
            detail="Company info not found. Please fetch it first using /fetch-company-info endpoint"
        )

    return {
        "realm_id": company_info.realm_id,
        "company_name": company_info.company_name,
        "legal_name": company_info.legal_name,
        "employer_id": company_info.employer_id,
        "company_addr": company_info.company_addr,
        "legal_addr": company_info.legal_addr,
        "customer_communication_addr": company_info.customer_communication_addr,
        "email": company_info.email,
        "customer_communication_email": company_info.customer_communication_email,
        "primary_phone": company_info.primary_phone,
        "web_addr": company_info.web_addr,
        "company_start_date": company_info.company_start_date,
        "fiscal_year_start_month": company_info.fiscal_year_start_month,
        "country": company_info.country,
        "supported_languages": company_info.supported_languages,
        "default_timezone": company_info.default_timezone,
        "qbo_id": company_info.qbo_id,
        "sync_token": company_info.sync_token,
        "domain": company_info.domain,
        "metadata": company_info.metadata,
        "last_synced_at": company_info.last_synced_at.isoformat() if company_info.last_synced_at else None,
        "created_at": company_info.created_at.isoformat() if company_info.created_at else None,
        "updated_at": company_info.updated_at.isoformat() if company_info.updated_at else None
    }
