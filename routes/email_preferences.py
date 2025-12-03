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

