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
from models import QuickBooksToken, User
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
