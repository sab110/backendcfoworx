# services/email_service.py
import resend
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from config import RESEND_API_KEY, EMAIL_FROM, FRONTEND_URL
from services.logging_service import log_info, log_error


class EmailService:
    """
    Email service using Resend API for sending transactional emails.
    """

    def __init__(self):
        if not RESEND_API_KEY:
            print("⚠️ Warning: RESEND_API_KEY not configured. Emails will not be sent.")
        else:
            resend.api_key = RESEND_API_KEY

    def _log_email(
        self,
        db: Session,
        realm_id: Optional[str],
        recipient_email: str,
        subject: str,
        email_type: str,
        resend_id: Optional[str] = None,
        status: str = "sent",
        error_message: Optional[str] = None,
    ):
        """Log email to database for tracking."""
        from models import EmailLog

        email_log = EmailLog(
            realm_id=realm_id,
            recipient_email=recipient_email,
            subject=subject,
            email_type=email_type,
            resend_id=resend_id,
            status=status,
            error_message=error_message,
            sent_at=datetime.utcnow(),
        )
        db.add(email_log)
        db.commit()
        return email_log

    def send_email(
        self,
        to: List[str],
        subject: str,
        html: str,
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
        email_type: str = "notification",
        text: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Send an email using Resend API.

        Args:
            to: List of recipient email addresses (max 50)
            subject: Email subject
            html: HTML content of the email
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)
            email_type: Type of email for logging (welcome, report, billing, notification)
            text: Plain text version (optional, auto-generated from HTML if not provided)
            reply_to: Reply-to email address (optional)
            cc: CC email addresses (optional)
            bcc: BCC email addresses (optional)
            attachments: List of attachment objects (optional)
            tags: List of tag objects for tracking (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        if not RESEND_API_KEY:
            error_msg = "RESEND_API_KEY not configured"
            print(f"❌ {error_msg}")
            return {"success": False, "error": error_msg}

        try:
            params: resend.Emails.SendParams = {
                "from": EMAIL_FROM,
                "to": to,
                "subject": subject,
                "html": html,
            }

            if text:
                params["text"] = text
            if reply_to:
                params["reply_to"] = reply_to
            if cc:
                params["cc"] = cc
            if bcc:
                params["bcc"] = bcc
            if attachments:
                params["attachments"] = attachments
            if tags:
                params["tags"] = tags

            response = resend.Emails.send(params)
            resend_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)

            print(f"✅ Email sent successfully to {to}, ID: {resend_id}")

            # Log to database if session provided
            if db:
                for recipient in to:
                    self._log_email(
                        db=db,
                        realm_id=realm_id,
                        recipient_email=recipient,
                        subject=subject,
                        email_type=email_type,
                        resend_id=resend_id,
                        status="sent",
                    )
                
                # Also log to system logs
                log_info(
                    db,
                    source="email_service",
                    action="email_sent",
                    message=f"Email sent: {email_type} to {len(to)} recipient(s)",
                    realm_id=realm_id,
                    details={"recipients": to, "subject": subject, "email_type": email_type, "resend_id": resend_id}
                )

            return {"success": True, "id": resend_id}

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Failed to send email: {error_msg}")

            # Log failure to database if session provided
            if db:
                for recipient in to:
                    self._log_email(
                        db=db,
                        realm_id=realm_id,
                        recipient_email=recipient,
                        subject=subject,
                        email_type=email_type,
                        status="failed",
                        error_message=error_msg,
                    )
                
                # Also log to system logs
                log_error(
                    db,
                    source="email_service",
                    action="email_failed",
                    message=f"Email failed: {email_type} to {len(to)} recipient(s) - {error_msg}",
                    realm_id=realm_id,
                    details={"recipients": to, "subject": subject, "email_type": email_type, "error": error_msg}
                )

            return {"success": False, "error": error_msg}

    def send_welcome_email(
        self,
        to: str,
        company_name: str,
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a welcome email when a company signs up for the first time.

        Args:
            to: Recipient email address
            company_name: Name of the company
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        subject = f"Welcome to CFO Worx, {company_name}! 🎉"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Welcome to CFO Worx</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7fa;">
            <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                <!-- Header -->
                <div style="background: linear-gradient(135deg, #1a365d 0%, #2d5a87 100%); border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 700;">
                        Welcome to CFO Worx! 🎉
                    </h1>
                    <p style="color: #a0c4e8; margin: 10px 0 0 0; font-size: 16px;">
                        Your royalty management journey begins here
                    </p>
                </div>
                
                <!-- Content -->
                <div style="background-color: #ffffff; padding: 40px 30px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                        Hi <strong>{company_name}</strong>,
                    </p>
                    
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                        Thank you for connecting your QuickBooks account with CFO Worx! We're excited to help streamline your royalty management process.
                    </p>
                    
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 25px 0;">
                        Here's what you can do next:
                    </p>
                    
                    <ul style="color: #334155; font-size: 15px; line-height: 1.8; margin: 0 0 25px 0; padding-left: 20px;">
                        <li>Complete your onboarding to set up your franchises</li>
                        <li>Configure your email preferences for reports</li>
                        <li>Map your QuickBooks departments to franchise locations</li>
                        <li>Generate your first royalty report</li>
                    </ul>
                    
                    <!-- CTA Button -->
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{FRONTEND_URL}/dashboard" 
                           style="display: inline-block; background: linear-gradient(135deg, #1a365d 0%, #2d5a87 100%); color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 16px;">
                            Go to Dashboard →
                        </a>
                    </div>
                    
                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
                    
                    <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin: 0;">
                        If you have any questions or need assistance, please don't hesitate to reach out to our support team.
                    </p>
                </div>
                
                <!-- Footer -->
                <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
                    <p style="margin: 0 0 5px 0;">© 2024 CFO Worx. All rights reserved.</p>
                    <p style="margin: 0;">Royalty Management Made Simple</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=[to],
            subject=subject,
            html=html,
            db=db,
            realm_id=realm_id,
            email_type="welcome",
            tags=[{"name": "email_type", "value": "welcome"}],
        )

    def send_report_notification(
        self,
        to: List[str],
        company_name: str,
        report_type: str,
        report_period: str,
        download_url: Optional[str] = None,
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a report notification email.

        Args:
            to: List of recipient email addresses
            company_name: Name of the company
            report_type: Type of report (e.g., "Royalty Volume Calculation Report")
            report_period: Period covered by the report (e.g., "Q3 2024")
            download_url: URL to download the report (optional)
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        subject = f"Your {report_type} is Ready - {report_period}"

        download_section = ""
        if download_url:
            download_section = f"""
            <div style="text-align: center; margin: 30px 0;">
                <a href="{download_url}" 
                   style="display: inline-block; background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 16px;">
                    Download Report →
                </a>
            </div>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Report Ready</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7fa;">
            <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                <!-- Header -->
                <div style="background: linear-gradient(135deg, #059669 0%, #10b981 100%); border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 700;">
                        📊 Report Ready
                    </h1>
                    <p style="color: #a7f3d0; margin: 10px 0 0 0; font-size: 16px;">
                        {report_type}
                    </p>
                </div>
                
                <!-- Content -->
                <div style="background-color: #ffffff; padding: 40px 30px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                        Hi <strong>{company_name}</strong>,
                    </p>
                    
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                        Your <strong>{report_type}</strong> for <strong>{report_period}</strong> has been generated and is ready for review.
                    </p>
                    
                    {download_section}
                    
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                        You can also access this report from your dashboard at any time.
                    </p>
                    
                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
                    
                    <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin: 0;">
                        This is an automated notification. Please do not reply to this email.
                    </p>
                </div>
                
                <!-- Footer -->
                <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
                    <p style="margin: 0 0 5px 0;">© 2024 CFO Worx. All rights reserved.</p>
                    <p style="margin: 0;">Royalty Management Made Simple</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=to,
            subject=subject,
            html=html,
            db=db,
            realm_id=realm_id,
            email_type="report",
            tags=[{"name": "email_type", "value": "report"}, {"name": "report_type", "value": report_type.replace(" ", "_")}],
        )

    def send_billing_notification(
        self,
        to: List[str],
        company_name: str,
        notification_type: str,  # e.g., "payment_failed", "subscription_renewed", "trial_ending"
        details: Dict[str, Any],
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a billing notification email.

        Args:
            to: List of recipient email addresses
            company_name: Name of the company
            notification_type: Type of billing notification
            details: Additional details for the notification
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        templates = {
            "payment_failed": {
                "subject": "⚠️ Payment Failed - Action Required",
                "color": "#dc2626",
                "icon": "⚠️",
                "title": "Payment Failed",
                "message": f"We were unable to process your payment for {company_name}. Please update your payment method to continue using CFO Worx.",
            },
            "subscription_renewed": {
                "subject": "✅ Subscription Renewed Successfully",
                "color": "#059669",
                "icon": "✅",
                "title": "Subscription Renewed",
                "message": f"Your CFO Worx subscription has been renewed successfully for {company_name}.",
            },
            "trial_ending": {
                "subject": "⏰ Your Trial is Ending Soon",
                "color": "#d97706",
                "icon": "⏰",
                "title": "Trial Ending Soon",
                "message": f"Your trial for {company_name} is ending soon. Subscribe now to continue enjoying CFO Worx features.",
            },
        }

        template = templates.get(notification_type, {
            "subject": "Billing Notification",
            "color": "#1a365d",
            "icon": "📧",
            "title": "Billing Update",
            "message": f"There's an update regarding your {company_name} account.",
        })

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{template['title']}</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7fa;">
            <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                <div style="background: {template['color']}; border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 700;">
                        {template['icon']} {template['title']}
                    </h1>
                </div>
                
                <div style="background-color: #ffffff; padding: 40px 30px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);">
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                        Hi <strong>{company_name}</strong>,
                    </p>
                    
                    <p style="color: #334155; font-size: 16px; line-height: 1.6; margin: 0 0 20px 0;">
                        {template['message']}
                    </p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{FRONTEND_URL}/dashboard" 
                           style="display: inline-block; background: {template['color']}; color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 16px;">
                            Go to Dashboard →
                        </a>
                    </div>
                    
                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 30px 0;">
                    
                    <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin: 0;">
                        If you have questions, please contact our support team.
                    </p>
                </div>
                
                <div style="text-align: center; padding: 20px; color: #94a3b8; font-size: 12px;">
                    <p style="margin: 0 0 5px 0;">© 2024 CFO Worx. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to=to,
            subject=template["subject"],
            html=html,
            db=db,
            realm_id=realm_id,
            email_type="billing",
            tags=[{"name": "email_type", "value": "billing"}, {"name": "notification_type", "value": notification_type}],
        )


# Create a singleton instance
email_service = EmailService()

