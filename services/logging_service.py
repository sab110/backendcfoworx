"""
Logging Service
================
Provides centralized logging functionality for the application.
Logs are stored in the database for admin dashboard visibility.
"""

from sqlalchemy.orm import Session
from models import SystemLog, WebhookLog
from datetime import datetime
import traceback
from typing import Optional, Dict, Any


class LoggingService:
    """Service for logging system events to the database"""
    
    @staticmethod
    def log(
        db: Session,
        level: str,
        source: str,
        action: str,
        message: str,
        realm_id: str = None,
        details: Dict[str, Any] = None,
        error_traceback: str = None,
        duration_ms: int = None,
        ip_address: str = None,
        user_agent: str = None
    ) -> SystemLog:
        """
        Create a system log entry
        
        Args:
            db: Database session
            level: Log level (INFO, WARNING, ERROR, DEBUG)
            source: Source component (stripe_webhook, qbo_sync, email_service, etc.)
            action: Action being performed (payment_received, token_refresh, etc.)
            message: Human-readable log message
            realm_id: Associated company realm_id (optional)
            details: Additional JSON details (optional)
            error_traceback: Error traceback for errors (optional)
            duration_ms: Duration in milliseconds (optional)
            ip_address: Request IP address (optional)
            user_agent: Request user agent (optional)
        
        Returns:
            Created SystemLog instance
        """
        log_entry = SystemLog(
            level=level.upper(),
            source=source,
            action=action,
            message=message,
            realm_id=realm_id,
            details=details,
            error_traceback=error_traceback,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.utcnow()
        )
        
        try:
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            return log_entry
        except Exception as e:
            db.rollback()
            print(f"Failed to save system log: {str(e)}")
            return None
    
    @staticmethod
    def info(db: Session, source: str, action: str, message: str, **kwargs) -> SystemLog:
        """Log an INFO level message"""
        return LoggingService.log(db, "INFO", source, action, message, **kwargs)
    
    @staticmethod
    def warning(db: Session, source: str, action: str, message: str, **kwargs) -> SystemLog:
        """Log a WARNING level message"""
        return LoggingService.log(db, "WARNING", source, action, message, **kwargs)
    
    @staticmethod
    def error(db: Session, source: str, action: str, message: str, exception: Exception = None, **kwargs) -> SystemLog:
        """Log an ERROR level message"""
        error_tb = None
        if exception:
            error_tb = traceback.format_exc()
        return LoggingService.log(db, "ERROR", source, action, message, error_traceback=error_tb, **kwargs)
    
    @staticmethod
    def debug(db: Session, source: str, action: str, message: str, **kwargs) -> SystemLog:
        """Log a DEBUG level message"""
        return LoggingService.log(db, "DEBUG", source, action, message, **kwargs)
    
    @staticmethod
    def log_webhook(
        db: Session,
        source: str,
        event_type: str,
        event_id: str = None,
        payload: Dict[str, Any] = None,
        status: str = "received",
        error_message: str = None,
        processing_time_ms: int = None,
        realm_id: str = None
    ) -> WebhookLog:
        """
        Create a webhook log entry
        
        Args:
            db: Database session
            source: Webhook source (stripe, intuit, other)
            event_type: Type of webhook event
            event_id: Unique event ID
            payload: Full webhook payload (optional, be careful with sensitive data)
            status: Processing status (received, processed, failed, ignored)
            error_message: Error message if failed
            processing_time_ms: Processing time in milliseconds
            realm_id: Associated company realm_id
        
        Returns:
            Created WebhookLog instance
        """
        # Sanitize payload - remove sensitive data
        safe_payload = None
        if payload:
            safe_payload = LoggingService._sanitize_payload(payload)
        
        log_entry = WebhookLog(
            source=source,
            event_type=event_type,
            event_id=event_id,
            payload=safe_payload,
            status=status,
            error_message=error_message,
            processing_time_ms=processing_time_ms,
            realm_id=realm_id,
            created_at=datetime.utcnow()
        )
        
        try:
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            return log_entry
        except Exception as e:
            db.rollback()
            print(f"Failed to save webhook log: {str(e)}")
            return None
    
    @staticmethod
    def _sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive data from webhook payloads"""
        if not payload:
            return payload
        
        # Keys to redact
        sensitive_keys = {
            'access_token', 'refresh_token', 'api_key', 'secret',
            'password', 'card', 'cvc', 'cvv', 'exp_month', 'exp_year',
            'number', 'bank_account'
        }
        
        def redact(obj):
            if isinstance(obj, dict):
                return {
                    k: '[REDACTED]' if k.lower() in sensitive_keys else redact(v)
                    for k, v in obj.items()
                }
            elif isinstance(obj, list):
                return [redact(item) for item in obj]
            return obj
        
        return redact(payload)


# Convenience functions for quick logging
def log_info(db: Session, source: str, action: str, message: str, **kwargs):
    return LoggingService.info(db, source, action, message, **kwargs)

def log_warning(db: Session, source: str, action: str, message: str, **kwargs):
    return LoggingService.warning(db, source, action, message, **kwargs)

def log_error(db: Session, source: str, action: str, message: str, **kwargs):
    return LoggingService.error(db, source, action, message, **kwargs)

def log_webhook(db: Session, source: str, event_type: str, **kwargs):
    return LoggingService.log_webhook(db, source, event_type, **kwargs)

