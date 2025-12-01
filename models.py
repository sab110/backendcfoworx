# models.py
from sqlalchemy import (
    Column, Integer, String, ForeignKey, TIMESTAMP, Text, func, DateTime
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from db import Base

Base = declarative_base()

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

    subscription = relationship(
        "Subscription",
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
# SUBSCRIPTION MODEL
# ------------------------------------------------------
class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    stripe_subscription_id = Column(String(100), unique=True, nullable=True)
    stripe_customer_id = Column(String(100), nullable=True)
    status = Column(String(50), default="inactive")  # active, canceled, past_due, etc.
    start_date = Column(TIMESTAMP, nullable=True)
    end_date = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, onupdate=func.now())

    user = relationship("User", back_populates="subscription")
    plan = relationship("Plan", back_populates="subscriptions")

    def __repr__(self):
        return f"<Subscription(user_id={self.user_id}, status='{self.status}')>"
