# models.py
from sqlalchemy import (
    Column, Integer, String, ForeignKey, TIMESTAMP, Text, func, DateTime, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from db import Base


# ------------------------------------------------------
# USER MODEL
# ------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(String(50), default="user")
    phone = Column(String(20), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, onupdate=func.now())

    # ✅ Fix: Reference QuickBooksToken instead of QuickBooksOAuth
    quickbooks_token = relationship(
        "QuickBooksToken",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"


# ------------------------------------------------------
# QUICKBOOKS TOKEN MODEL
# ------------------------------------------------------
class QuickBooksToken(Base):
    __tablename__ = "quickbooks_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    realm_id = Column(String, nullable=False, unique=True)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ✅ Add relationship back to User
    user = relationship("User", back_populates="quickbooks_token")

    def is_expired(self):
        return datetime.utcnow() >= self.expires_at

    @classmethod
    def create_from_auth_client(cls, user_id, realm_id, auth_client):
        return cls(
            user_id=user_id,
            realm_id=realm_id,
            access_token=auth_client.access_token,
            refresh_token=auth_client.refresh_token,
            expires_at=datetime.utcnow() + timedelta(seconds=3600),
        )


# ------------------------------------------------------
# PLAN MODEL
# ------------------------------------------------------
class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)  # e.g., "Standard", "Pro"
    billing_cycle = Column(String(20), nullable=False)  # "monthly", "6-month", "annual"
    price = Column(String(20), nullable=False)  # e.g., "$39/mo"
    stripe_price_id = Column(String(100), unique=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    subscriptions = relationship("Subscription", back_populates="plan")

    def __repr__(self):
        return f"<Plan(name='{self.name}', billing_cycle='{self.billing_cycle}', price='{self.price}')>"


# ------------------------------------------------------
# SUBSCRIPTION MODEL (Company-Level)
# ------------------------------------------------------
class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(String, ForeignKey("company_info.realm_id", ondelete="CASCADE"), nullable=False, unique=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    stripe_subscription_id = Column(String(100), unique=True, nullable=True)
    stripe_customer_id = Column(String(100), nullable=True)
    status = Column(String(50), default="inactive")  # active, canceled, past_due, etc.
    quantity = Column(Integer, default=1)  # Number of licenses (seats)
    start_date = Column(TIMESTAMP, nullable=True)
    end_date = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, onupdate=func.now())

    # Relationships
    company = relationship("CompanyInfo", back_populates="subscription")
    plan = relationship("Plan", back_populates="subscriptions")

    def __repr__(self):
        return f"<Subscription(realm_id={self.realm_id}, status='{self.status}')>"


# ------------------------------------------------------
# QUICKBOOKS COMPANY INFO MODEL
# ------------------------------------------------------
class CompanyInfo(Base):
    __tablename__ = "company_info"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(String, ForeignKey("quickbooks_tokens.realm_id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # Basic Company Information
    company_name = Column(String(255), nullable=True)
    legal_name = Column(String(255), nullable=True)
    employer_id = Column(String(100), nullable=True)  # Tax ID
    
    # Address Information (stored as JSON for flexibility)
    company_addr = Column(JSON, nullable=True)
    legal_addr = Column(JSON, nullable=True)
    customer_communication_addr = Column(JSON, nullable=True)
    
    # Contact Information
    email = Column(String(255), nullable=True)
    customer_communication_email = Column(String(255), nullable=True)
    primary_phone = Column(String(50), nullable=True)
    web_addr = Column(String(255), nullable=True)
    
    # Company Details
    company_start_date = Column(String(50), nullable=True)
    fiscal_year_start_month = Column(String(50), nullable=True)
    country = Column(String(10), nullable=True)
    supported_languages = Column(String(50), nullable=True)
    default_timezone = Column(String(100), nullable=True)
    
    # QuickBooks Metadata
    qbo_id = Column(String(50), nullable=True)  # QuickBooks ID
    sync_token = Column(String(50), nullable=True)
    domain = Column(String(50), nullable=True)
    
    # Additional metadata (NameValue pairs, etc.)
    # metadata = Column(JSON, nullable=True)
    
    # Onboarding Status
    onboarding_completed = Column(String(10), default="false")  # "true" or "false"
    onboarding_completed_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    subscription = relationship(
        "Subscription",
        back_populates="company",
        uselist=False,
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<CompanyInfo(realm_id='{self.realm_id}', company_name='{self.company_name}')>"


# ------------------------------------------------------
# LICENSE MODEL
# ------------------------------------------------------
class License(Base):
    __tablename__ = "licenses"

    id = Column(Integer, primary_key=True, index=True)
    franchise_number = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    owner = Column(String(255), nullable=True)
    address = Column(String(500), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(10), nullable=True)
    zip_code = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<License(franchise_number='{self.franchise_number}', name='{self.name}')>"




# ------------------------------------------------------
# COMPANY-LICENSE MAPPING MODEL
# ------------------------------------------------------
class CompanyLicenseMapping(Base):
    __tablename__ = "company_license_mappings"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(String, ForeignKey("company_info.realm_id", ondelete="CASCADE"), nullable=False, index=True)
    franchise_number = Column(String(50), nullable=False, index=True)
    
    # QuickBooks Department Info
    qbo_department_id = Column(String(50), nullable=True)
    qbo_department_name = Column(String(255), nullable=True)
    
    # Mapping status
    is_active = Column(String(10), default="true")
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<CompanyLicenseMapping(realm_id='{self.realm_id}', franchise_number='{self.franchise_number}', department='{self.qbo_department_name}')>"


# ------------------------------------------------------
# FAILED PAYMENT LOG MODEL
# ------------------------------------------------------
class FailedPaymentLog(Base):
    __tablename__ = "failed_payment_logs"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(String, ForeignKey("company_info.realm_id", ondelete="SET NULL"), nullable=True, index=True)
    stripe_customer_id = Column(String(100), nullable=True, index=True)
    stripe_subscription_id = Column(String(100), nullable=True)
    stripe_invoice_id = Column(String(100), nullable=True)
    
    # Payment details
    amount = Column(Integer, nullable=True)  # Amount in cents
    currency = Column(String(10), default="usd")
    failure_code = Column(String(100), nullable=True)
    failure_message = Column(Text, nullable=True)
    
    # Customer info at time of failure
    customer_email = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    
    # Status tracking
    status = Column(String(50), default="unresolved")  # unresolved, resolved, retrying
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    # Timestamps
    failed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<FailedPaymentLog(id={self.id}, customer_email='{self.customer_email}', status='{self.status}')>"


# ------------------------------------------------------
# SUBMISSION MODEL (Franchisee submissions)
# ------------------------------------------------------
class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(String, ForeignKey("company_info.realm_id", ondelete="CASCADE"), nullable=False, index=True)
    franchise_number = Column(String(50), nullable=True, index=True)
    
    # Submission details
    submission_type = Column(String(100), nullable=True)  # e.g., "royalty_report", "sales_report"
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    
    # Financial data
    gross_sales = Column(Integer, nullable=True)  # Amount in cents
    royalty_amount = Column(Integer, nullable=True)
    advertising_fee = Column(Integer, nullable=True)
    
    # Status
    status = Column(String(50), default="submitted")  # submitted, approved, rejected, pending_review
    
    # File attachments (stored as JSON array of file URLs)
    attachments = Column(JSON, nullable=True)
    
    # Notes and metadata
    notes = Column(Text, nullable=True)
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    
    # Timestamps
    submitted_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Submission(id={self.id}, realm_id='{self.realm_id}', status='{self.status}')>"


# ------------------------------------------------------
# ADMIN ACTIVITY LOG MODEL
# ------------------------------------------------------
class AdminActivityLog(Base):
    __tablename__ = "admin_activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    admin_username = Column(String(100), nullable=False, index=True)
    action = Column(String(100), nullable=False)  # e.g., "login", "view_clients", "export_data"
    resource_type = Column(String(100), nullable=True)  # e.g., "subscription", "client", "payment"
    resource_id = Column(String(100), nullable=True)
    details = Column(JSON, nullable=True)  # Additional context
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AdminActivityLog(id={self.id}, admin='{self.admin_username}', action='{self.action}')>"


# ------------------------------------------------------
# EMAIL PREFERENCE MODEL
# ------------------------------------------------------
class EmailPreference(Base):
    __tablename__ = "email_preferences"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(String, ForeignKey("company_info.realm_id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    label = Column(String(100), nullable=True)  # e.g., "Primary", "Billing", "Reports"
    is_primary = Column(String(10), default="false")  # "true" or "false"
    receive_reports = Column(String(10), default="true")  # Receive report emails
    receive_billing = Column(String(10), default="true")  # Receive billing emails
    receive_notifications = Column(String(10), default="true")  # Receive notification emails
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<EmailPreference(id={self.id}, realm_id='{self.realm_id}', email='{self.email}')>"


# ------------------------------------------------------
# EMAIL LOG MODEL (for tracking sent emails)
# ------------------------------------------------------
class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(String, ForeignKey("company_info.realm_id", ondelete="SET NULL"), nullable=True, index=True)
    recipient_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    email_type = Column(String(50), nullable=False)  # e.g., "welcome", "report", "billing", "notification"
    resend_id = Column(String(100), nullable=True)  # ID from Resend API
    status = Column(String(50), default="sent")  # sent, failed, bounced, delivered
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<EmailLog(id={self.id}, recipient='{self.recipient_email}', type='{self.email_type}')>"