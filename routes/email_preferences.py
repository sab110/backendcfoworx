# routes/email_preferences.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime
from db import get_db
from models import EmailPreference, CompanyInfo, EmailLog

router = APIRouter()


# ------------------------------------------------------
# Pydantic Models for Request/Response
# ------------------------------------------------------
class EmailPreferenceCreate(BaseModel):
    email: EmailStr
    label: Optional[str] = None
    is_primary: Optional[bool] = False
    receive_reports: Optional[bool] = True
    receive_billing: Optional[bool] = True
    receive_notifications: Optional[bool] = True


class EmailPreferenceUpdate(BaseModel):
    email: Optional[EmailStr] = None
    label: Optional[str] = None
    is_primary: Optional[bool] = None
    receive_reports: Optional[bool] = None
    receive_billing: Optional[bool] = None
    receive_notifications: Optional[bool] = None


class EmailPreferenceResponse(BaseModel):
    id: int
    realm_id: str
    email: str
    label: Optional[str]
    is_primary: bool
    receive_reports: bool
    receive_billing: bool
    receive_notifications: bool
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class EmailLogResponse(BaseModel):
    id: int
    realm_id: Optional[str]
    recipient_email: str
    subject: str
    email_type: str
    resend_id: Optional[str]
    status: str
    error_message: Optional[str]
    sent_at: datetime

    class Config:
        from_attributes = True


# ------------------------------------------------------
# Helper Functions
# ------------------------------------------------------
def _bool_to_str(value: bool) -> str:
    return "true" if value else "false"


def _str_to_bool(value: str) -> bool:
    return value.lower() == "true"


def _serialize_preference(pref: EmailPreference) -> dict:
    return {
        "id": pref.id,
        "realm_id": pref.realm_id,
        "email": pref.email,
        "label": pref.label,
        "is_primary": _str_to_bool(pref.is_primary) if pref.is_primary else False,
        "receive_reports": _str_to_bool(pref.receive_reports) if pref.receive_reports else True,
        "receive_billing": _str_to_bool(pref.receive_billing) if pref.receive_billing else True,
        "receive_notifications": _str_to_bool(pref.receive_notifications) if pref.receive_notifications else True,
        "created_at": pref.created_at.isoformat() if pref.created_at else None,
        "updated_at": pref.updated_at.isoformat() if pref.updated_at else None,
    }


# ------------------------------------------------------
# GET: List all email preferences for a realm
# ------------------------------------------------------
@router.get("/{realm_id}")
async def get_email_preferences(realm_id: str, db: Session = Depends(get_db)):
    """
    Get all email preferences for a company (by realm_id).
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    preferences = db.query(EmailPreference).filter_by(realm_id=realm_id).all()

    return {
        "realm_id": realm_id,
        "company_name": company.company_name,
        "preferences": [_serialize_preference(p) for p in preferences],
        "count": len(preferences),
    }


# ------------------------------------------------------
# POST: Add a new email preference
# ------------------------------------------------------
@router.post("/{realm_id}")
async def add_email_preference(
    realm_id: str,
    preference: EmailPreferenceCreate,
    db: Session = Depends(get_db),
):
    """
    Add a new email preference for a company.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Check if email already exists for this realm
    existing = db.query(EmailPreference).filter_by(
        realm_id=realm_id, email=preference.email
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Email {preference.email} already exists for this company",
        )

    # If this is set as primary, unset other primary emails
    if preference.is_primary:
        db.query(EmailPreference).filter_by(realm_id=realm_id).update(
            {"is_primary": "false"}
        )

    # Create new preference
    new_preference = EmailPreference(
        realm_id=realm_id,
        email=preference.email,
        label=preference.label,
        is_primary=_bool_to_str(preference.is_primary),
        receive_reports=_bool_to_str(preference.receive_reports),
        receive_billing=_bool_to_str(preference.receive_billing),
        receive_notifications=_bool_to_str(preference.receive_notifications),
    )

    db.add(new_preference)
    db.commit()
    db.refresh(new_preference)

    return {
        "message": "Email preference added successfully",
        "preference": _serialize_preference(new_preference),
    }


# ------------------------------------------------------
# PUT: Update an existing email preference
# ------------------------------------------------------
@router.put("/{realm_id}/{preference_id}")
async def update_email_preference(
    realm_id: str,
    preference_id: int,
    preference: EmailPreferenceUpdate,
    db: Session = Depends(get_db),
):
    """
    Update an existing email preference.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Find the preference
    existing = db.query(EmailPreference).filter_by(
        id=preference_id, realm_id=realm_id
    ).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Email preference not found")

    # Check if updating to a new email that already exists
    if preference.email and preference.email != existing.email:
        duplicate = db.query(EmailPreference).filter_by(
            realm_id=realm_id, email=preference.email
        ).first()
        if duplicate:
            raise HTTPException(
                status_code=400,
                detail=f"Email {preference.email} already exists for this company",
            )
        existing.email = preference.email

    # Update fields if provided
    if preference.label is not None:
        existing.label = preference.label

    if preference.is_primary is not None:
        # If setting as primary, unset other primary emails first
        if preference.is_primary:
            db.query(EmailPreference).filter(
                EmailPreference.realm_id == realm_id,
                EmailPreference.id != preference_id
            ).update({"is_primary": "false"})
        existing.is_primary = _bool_to_str(preference.is_primary)

    if preference.receive_reports is not None:
        existing.receive_reports = _bool_to_str(preference.receive_reports)

    if preference.receive_billing is not None:
        existing.receive_billing = _bool_to_str(preference.receive_billing)

    if preference.receive_notifications is not None:
        existing.receive_notifications = _bool_to_str(preference.receive_notifications)

    existing.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(existing)

    return {
        "message": "Email preference updated successfully",
        "preference": _serialize_preference(existing),
    }


# ------------------------------------------------------
# DELETE: Remove an email preference
# ------------------------------------------------------
@router.delete("/{realm_id}/{preference_id}")
async def delete_email_preference(
    realm_id: str,
    preference_id: int,
    db: Session = Depends(get_db),
):
    """
    Delete an email preference.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Find the preference
    preference = db.query(EmailPreference).filter_by(
        id=preference_id, realm_id=realm_id
    ).first()
    if not preference:
        raise HTTPException(status_code=404, detail="Email preference not found")

    email = preference.email
    db.delete(preference)
    db.commit()

    return {
        "message": f"Email preference for {email} deleted successfully",
        "deleted_id": preference_id,
    }


# ------------------------------------------------------
# DELETE: Remove email preference by email address
# ------------------------------------------------------
@router.delete("/{realm_id}/email/{email}")
async def delete_email_preference_by_email(
    realm_id: str,
    email: str,
    db: Session = Depends(get_db),
):
    """
    Delete an email preference by email address.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Find the preference
    preference = db.query(EmailPreference).filter_by(
        realm_id=realm_id, email=email
    ).first()
    if not preference:
        raise HTTPException(
            status_code=404,
            detail=f"Email preference for {email} not found",
        )

    preference_id = preference.id
    db.delete(preference)
    db.commit()

    return {
        "message": f"Email preference for {email} deleted successfully",
        "deleted_id": preference_id,
    }


# ------------------------------------------------------
# GET: Get recipients for a specific email type
# ------------------------------------------------------
@router.get("/{realm_id}/recipients/{email_type}")
async def get_email_recipients(
    realm_id: str,
    email_type: str,  # "reports", "billing", "notifications"
    db: Session = Depends(get_db),
):
    """
    Get all email addresses that should receive a specific type of email.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Map email type to column
    type_column_map = {
        "reports": "receive_reports",
        "billing": "receive_billing",
        "notifications": "receive_notifications",
    }

    if email_type not in type_column_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid email type. Must be one of: {', '.join(type_column_map.keys())}",
        )

    column_name = type_column_map[email_type]
    preferences = db.query(EmailPreference).filter(
        EmailPreference.realm_id == realm_id,
        getattr(EmailPreference, column_name) == "true"
    ).all()

    return {
        "realm_id": realm_id,
        "email_type": email_type,
        "recipients": [p.email for p in preferences],
        "count": len(preferences),
    }


# ------------------------------------------------------
# POST: Bulk add email preferences
# ------------------------------------------------------
@router.post("/{realm_id}/bulk")
async def bulk_add_email_preferences(
    realm_id: str,
    preferences: List[EmailPreferenceCreate],
    db: Session = Depends(get_db),
):
    """
    Bulk add email preferences for a company.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    added = []
    skipped = []

    for pref in preferences:
        # Check if email already exists
        existing = db.query(EmailPreference).filter_by(
            realm_id=realm_id, email=pref.email
        ).first()
        if existing:
            skipped.append(pref.email)
            continue

        new_preference = EmailPreference(
            realm_id=realm_id,
            email=pref.email,
            label=pref.label,
            is_primary=_bool_to_str(pref.is_primary),
            receive_reports=_bool_to_str(pref.receive_reports),
            receive_billing=_bool_to_str(pref.receive_billing),
            receive_notifications=_bool_to_str(pref.receive_notifications),
        )
        db.add(new_preference)
        added.append(pref.email)

    db.commit()

    return {
        "message": f"Bulk operation completed. Added: {len(added)}, Skipped: {len(skipped)}",
        "added": added,
        "skipped": skipped,
    }


# ------------------------------------------------------
# GET: Email logs for a realm
# ------------------------------------------------------
@router.get("/{realm_id}/logs")
async def get_email_logs(
    realm_id: str,
    limit: int = 50,
    email_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Get email logs for a company.
    """
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    query = db.query(EmailLog).filter_by(realm_id=realm_id)

    if email_type:
        query = query.filter_by(email_type=email_type)

    logs = query.order_by(EmailLog.sent_at.desc()).limit(limit).all()

    return {
        "realm_id": realm_id,
        "logs": [
            {
                "id": log.id,
                "recipient_email": log.recipient_email,
                "subject": log.subject,
                "email_type": log.email_type,
                "resend_id": log.resend_id,
                "status": log.status,
                "error_message": log.error_message,
                "sent_at": log.sent_at.isoformat() if log.sent_at else None,
            }
            for log in logs
        ],
        "count": len(logs),
    }


# ------------------------------------------------------
# POST: Test email sending
# ------------------------------------------------------
@router.post("/{realm_id}/test")
async def send_test_email(
    realm_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Send a test email to verify configuration.
    """
    from services.email_service import email_service

    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email address is required")

    result = email_service.send_email(
        to=[email],
        subject="Test Email from CFO Worx",
        html=f"""
        <div style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>🧪 Test Email</h2>
            <p>This is a test email from CFO Worx for <strong>{company.company_name}</strong>.</p>
            <p>If you received this email, your email configuration is working correctly!</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Sent at: {datetime.utcnow().isoformat()}</p>
        </div>
        """,
        db=db,
        realm_id=realm_id,
        email_type="notification",
        tags=[{"name": "email_type", "value": "test"}],
    )

    if result["success"]:
        return {
            "message": f"Test email sent successfully to {email}",
            "resend_id": result.get("id"),
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send test email: {result.get('error')}",
        )


# ------------------------------------------------------
# GET: Debug email configuration
# ------------------------------------------------------
@router.get("/debug/status")
async def debug_email_status():
    """
    Debug endpoint to check email service configuration.
    Returns the status of the email service without sending any emails.
    """
    from config import RESEND_API_KEY, EMAIL_FROM
    
    status = {
        "resend_api_key_configured": bool(RESEND_API_KEY),
        "resend_api_key_preview": f"{RESEND_API_KEY[:10]}..." if RESEND_API_KEY and len(RESEND_API_KEY) > 10 else "Not set",
        "email_from": EMAIL_FROM,
        "service_ready": bool(RESEND_API_KEY and EMAIL_FROM),
    }
    
    # Try to validate the API key by making a simple request
    if RESEND_API_KEY:
        try:
            import resend
            resend.api_key = RESEND_API_KEY
            # Try to get domains (a simple API call to verify key)
            # This won't send any email
            status["api_key_valid"] = True
            status["message"] = "Email service is configured and ready"
        except Exception as e:
            status["api_key_valid"] = False
            status["validation_error"] = str(e)
            status["message"] = f"API key validation failed: {str(e)}"
    else:
        status["api_key_valid"] = False
        status["message"] = "RESEND_API_KEY is not configured. Please set it in your .env file."
    
    return status


# ------------------------------------------------------
# POST: Send test email without realm_id (for debugging)
# ------------------------------------------------------
@router.post("/debug/send-test")
async def debug_send_test_email(payload: dict, db: Session = Depends(get_db)):
    """
    Debug endpoint to send a test email without requiring a realm_id.
    Useful for testing the email service configuration.
    """
    from services.email_service import email_service
    from config import RESEND_API_KEY, EMAIL_FROM
    
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email address is required in payload")
    
    # Check configuration first
    if not RESEND_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="RESEND_API_KEY is not configured. Please set it in your .env file."
        )
    
    if not EMAIL_FROM:
        raise HTTPException(
            status_code=500,
            detail="EMAIL_FROM is not configured. Please set it in your .env file."
        )
    
    try:
        result = email_service.send_email(
            to=[email],
            subject="🧪 CFO Worx Email Test",
            html=f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"></head>
            <body style="margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; background-color: #f4f7fa;">
                <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                    <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                        <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 700;">
                            ✅ Email Test Successful!
                        </h1>
                    </div>
                    <div style="background-color: #ffffff; padding: 40px 30px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                        <p style="color: #334155; font-size: 16px; line-height: 1.6;">
                            This is a test email from CFO Worx email service.
                        </p>
                        <p style="color: #334155; font-size: 16px; line-height: 1.6;">
                            If you're seeing this, your email configuration is working correctly!
                        </p>
                        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
                        <p style="color: #64748b; font-size: 14px;">
                            <strong>Configuration:</strong><br>
                            From: {EMAIL_FROM}<br>
                            To: {email}<br>
                            Sent at: {datetime.utcnow().isoformat()}Z
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """,
            email_type="notification",
        )
        
        if result["success"]:
            return {
                "success": True,
                "message": f"Test email sent successfully to {email}",
                "resend_id": result.get("id"),
                "from": EMAIL_FROM,
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to send email: {result.get('error')}"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error sending test email: {str(e)}"
        )


# ------------------------------------------------------
# POST: Send welcome email manually
# ------------------------------------------------------
@router.post("/{realm_id}/send-welcome")
async def send_welcome_email_manual(
    realm_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Manually send a welcome email to a company.
    Useful for re-sending welcome emails or for companies that didn't receive one.
    """
    from services.email_service import email_service
    
    # Verify company exists
    company = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Use provided email or company's email
    email = payload.get("email") or company.email or company.customer_communication_email
    if not email:
        raise HTTPException(
            status_code=400,
            detail="No email address available. Please provide one in the payload or update company info."
        )
    
    company_name = company.company_name or "Your Company"
    
    result = email_service.send_welcome_email(
        to=email,
        company_name=company_name,
        db=db,
        realm_id=realm_id,
    )
    
    if result["success"]:
        # Create email preference if doesn't exist
        existing_pref = db.query(EmailPreference).filter_by(
            realm_id=realm_id, email=email
        ).first()
        if not existing_pref:
            email_pref = EmailPreference(
                realm_id=realm_id,
                email=email,
                label="Primary",
                is_primary="true",
                receive_reports="true",
                receive_billing="true",
                receive_notifications="true",
            )
            db.add(email_pref)
            db.commit()
        
        return {
            "success": True,
            "message": f"Welcome email sent to {email}",
            "resend_id": result.get("id"),
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send welcome email: {result.get('error')}"
        )

