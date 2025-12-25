# services/email_service.py
import resend
import base64
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from config import RESEND_API_KEY, EMAIL_FROM, FRONTEND_URL
from services.logging_service import log_info, log_error


class EmailService:
    """
    Email service using Resend API for sending transactional emails.
    Professional templates without icons/emojis.
    """

    def __init__(self):
        if not RESEND_API_KEY:
            print("Warning: RESEND_API_KEY not configured. Emails will not be sent.")
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

    def _get_base_template(self, title: str, content: str, show_button: bool = True, 
                           button_text: str = "Go to Dashboard", button_url: str = None) -> str:
        """
        Generate a professional email template.
        Clean, minimal design without icons or emojis.
        """
        button_url = button_url or f"{FRONTEND_URL}/dashboard"
        
        button_section = ""
        if show_button:
            button_section = f"""
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{button_url}" 
                           style="display: inline-block; background-color: #1a365d; color: #ffffff; text-decoration: none; padding: 12px 28px; border-radius: 4px; font-weight: 600; font-size: 14px;">
                            {button_text}
                        </a>
                    </div>
            """
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
        </head>
        <body style="margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
                <!-- Header -->
                <div style="background-color: #1a365d; padding: 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 600; letter-spacing: 0.5px;">
                        CFO Worx
                    </h1>
                </div>
                
                <!-- Content -->
                <div style="background-color: #ffffff; padding: 40px 30px; border: 1px solid #e0e0e0; border-top: none;">
                    <h2 style="color: #1a365d; font-size: 20px; font-weight: 600; margin: 0 0 20px 0;">
                        {title}
                    </h2>
                    
                    {content}
                    
                    {button_section}
                </div>
                
                <!-- Footer -->
                <div style="padding: 20px; text-align: center; border: 1px solid #e0e0e0; border-top: none; background-color: #fafafa;">
                    <p style="color: #666666; font-size: 12px; margin: 0 0 5px 0;">
                        CFO Worx - Royalty Management Solutions
                    </p>
                    <p style="color: #999999; font-size: 11px; margin: 0;">
                        This is an automated message. Please do not reply directly to this email.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

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
                        Format: [{"filename": "report.xlsx", "content": base64_string}]
            tags: List of tag objects for tracking (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        if not RESEND_API_KEY:
            error_msg = "RESEND_API_KEY not configured"
            print(f"Error: {error_msg}")
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

            print(f"Email sent successfully to {to}, ID: {resend_id}")

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
            print(f"Failed to send email: {error_msg}")

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
        """
        subject = f"Welcome to CFO Worx - {company_name}"

        content = f"""
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        Dear {company_name} Team,
                    </p>
                    
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        Thank you for connecting your QuickBooks account with CFO Worx. Your account has been 
                        successfully set up and is ready to use.
                    </p>
                    
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 15px 0;">
                        <strong>Next Steps:</strong>
                    </p>
                    
                    <ul style="color: #333333; font-size: 15px; line-height: 1.8; margin: 0 0 20px 0; padding-left: 20px;">
                        <li>Complete your onboarding to configure your franchises</li>
                        <li>Set up your email preferences for automated reports</li>
                        <li>Map your QuickBooks departments to franchise locations</li>
                        <li>Generate your first royalty report</li>
                    </ul>
                    
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        If you have any questions or require assistance, please contact our support team.
                    </p>
        """

        html = self._get_base_template(
            title="Welcome to CFO Worx",
            content=content,
            button_text="Access Your Dashboard"
        )

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
        franchise_number: Optional[str] = None,
        download_url: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a report notification email with optional attachment.

        Args:
            to: List of recipient email addresses
            company_name: Name of the company
            report_type: Type of report (e.g., "RVCR", "Payment Summary")
            report_period: Period covered by the report (e.g., "November 2024")
            franchise_number: Franchise number (optional)
            download_url: URL to download the report (optional)
            attachments: List of file attachments (optional)
                        Format: [{"filename": "report.xlsx", "content": base64_string}]
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        franchise_info = f" - Franchise {franchise_number}" if franchise_number else ""
        subject = f"{report_type} Report Ready{franchise_info} - {report_period}"

        download_section = ""
        if download_url:
            download_section = f"""
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 20px 0;">
                        You can also download this report directly from your dashboard using the link below.
                    </p>
            """

        attachment_notice = ""
        if attachments:
            file_names = [att.get("filename", "attachment") for att in attachments]
            attachment_notice = f"""
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-left: 3px solid #1a365d;">
                        <strong>Attached Files:</strong><br>
                        {', '.join(file_names)}
                    </p>
            """

        content = f"""
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        Dear {company_name} Team,
                    </p>
                    
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        Your <strong>{report_type}</strong> report for <strong>{report_period}</strong> has been 
                        generated and is attached to this email for your records.
                    </p>
                    
                    <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                        <tr>
                            <td style="padding: 10px 15px; background-color: #f8f9fa; border: 1px solid #e0e0e0; font-size: 14px; color: #666666; width: 140px;">
                                <strong>Report Type</strong>
                            </td>
                            <td style="padding: 10px 15px; border: 1px solid #e0e0e0; font-size: 14px; color: #333333;">
                                {report_type}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 10px 15px; background-color: #f8f9fa; border: 1px solid #e0e0e0; font-size: 14px; color: #666666;">
                                <strong>Period</strong>
                            </td>
                            <td style="padding: 10px 15px; border: 1px solid #e0e0e0; font-size: 14px; color: #333333;">
                                {report_period}
                            </td>
                        </tr>
                        {"<tr><td style='padding: 10px 15px; background-color: #f8f9fa; border: 1px solid #e0e0e0; font-size: 14px; color: #666666;'><strong>Franchise</strong></td><td style='padding: 10px 15px; border: 1px solid #e0e0e0; font-size: 14px; color: #333333;'>" + franchise_number + "</td></tr>" if franchise_number else ""}
                        <tr>
                            <td style="padding: 10px 15px; background-color: #f8f9fa; border: 1px solid #e0e0e0; font-size: 14px; color: #666666;">
                                <strong>Generated</strong>
                            </td>
                            <td style="padding: 10px 15px; border: 1px solid #e0e0e0; font-size: 14px; color: #333333;">
                                {datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')} UTC
                            </td>
                        </tr>
                    </table>
                    
                    {attachment_notice}
                    {download_section}
                    
                    <p style="color: #666666; font-size: 13px; line-height: 1.6; margin: 20px 0 0 0;">
                        Please review the attached report at your earliest convenience. For any discrepancies 
                        or questions, contact your account manager.
                    </p>
        """

        html = self._get_base_template(
            title=f"{report_type} Report",
            content=content,
            button_text="View in Dashboard",
            button_url=download_url or f"{FRONTEND_URL}/dashboard"
        )

        return self.send_email(
            to=to,
            subject=subject,
            html=html,
            db=db,
            realm_id=realm_id,
            email_type="report",
            attachments=attachments,
            tags=[
                {"name": "email_type", "value": "report"}, 
                {"name": "report_type", "value": report_type.replace(" ", "_")}
            ],
        )

    def send_report_with_files(
        self,
        to: List[str],
        company_name: str,
        report_type: str,
        report_period: str,
        franchise_number: Optional[str] = None,
        excel_path: Optional[str] = None,
        pdf_path: Optional[str] = None,
        excel_url: Optional[str] = None,
        pdf_url: Optional[str] = None,
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a report email with Excel and/or PDF files attached.

        Args:
            to: List of recipient email addresses
            company_name: Name of the company
            report_type: Type of report (e.g., "RVCR", "Payment Summary")
            report_period: Period covered (e.g., "November 2024")
            franchise_number: Franchise number (optional)
            excel_path: Path to Excel file to attach (optional)
            pdf_path: Path to PDF file to attach (optional)
            excel_url: URL to download Excel (optional, for email body)
            pdf_url: URL to download PDF (optional, for email body)
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        attachments = []
        
        # Attach Excel file
        if excel_path:
            try:
                with open(excel_path, 'rb') as f:
                    excel_content = base64.b64encode(f.read()).decode('utf-8')
                    file_name = excel_path.split('/')[-1].split('\\')[-1]
                    attachments.append({
                        "filename": file_name,
                        "content": excel_content
                    })
            except Exception as e:
                print(f"Warning: Could not attach Excel file: {e}")
        
        # Attach PDF file
        if pdf_path:
            try:
                with open(pdf_path, 'rb') as f:
                    pdf_content = base64.b64encode(f.read()).decode('utf-8')
                    file_name = pdf_path.split('/')[-1].split('\\')[-1]
                    attachments.append({
                        "filename": file_name,
                        "content": pdf_content
                    })
            except Exception as e:
                print(f"Warning: Could not attach PDF file: {e}")
        
        return self.send_report_notification(
            to=to,
            company_name=company_name,
            report_type=report_type,
            report_period=report_period,
            franchise_number=franchise_number,
            download_url=excel_url or pdf_url,
            attachments=attachments if attachments else None,
            db=db,
            realm_id=realm_id,
        )

    def send_report_with_blob_content(
        self,
        to: List[str],
        company_name: str,
        report_type: str,
        report_period: str,
        franchise_number: Optional[str] = None,
        excel_content: Optional[bytes] = None,
        excel_filename: Optional[str] = None,
        pdf_content: Optional[bytes] = None,
        pdf_filename: Optional[str] = None,
        download_url: Optional[str] = None,
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a report email with file content (bytes) attached.
        Useful when files are in memory or from Azure Blob Storage.

        Args:
            to: List of recipient email addresses
            company_name: Name of the company
            report_type: Type of report
            report_period: Period covered
            franchise_number: Franchise number (optional)
            excel_content: Excel file content as bytes (optional)
            excel_filename: Excel filename (optional)
            pdf_content: PDF file content as bytes (optional)
            pdf_filename: PDF filename (optional)
            download_url: URL to download (optional)
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        attachments = []
        
        if excel_content and excel_filename:
            attachments.append({
                "filename": excel_filename,
                "content": base64.b64encode(excel_content).decode('utf-8')
            })
        
        if pdf_content and pdf_filename:
            attachments.append({
                "filename": pdf_filename,
                "content": base64.b64encode(pdf_content).decode('utf-8')
            })
        
        return self.send_report_notification(
            to=to,
            company_name=company_name,
            report_type=report_type,
            report_period=report_period,
            franchise_number=franchise_number,
            download_url=download_url,
            attachments=attachments if attachments else None,
            db=db,
            realm_id=realm_id,
        )

    def send_billing_notification(
        self,
        to: List[str],
        company_name: str,
        notification_type: str,
        details: Dict[str, Any],
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a billing notification email.

        Args:
            to: List of recipient email addresses
            company_name: Name of the company
            notification_type: Type of billing notification (payment_failed, subscription_renewed, trial_ending)
            details: Additional details for the notification
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        templates = {
            "payment_failed": {
                "subject": "Payment Failed - Action Required",
                "title": "Payment Processing Issue",
                "message": f"We were unable to process your payment for {company_name}. Please update your payment method to ensure continued access to your account.",
                "action_text": "Update Payment Method",
            },
            "subscription_renewed": {
                "subject": "Subscription Renewed Successfully",
                "title": "Subscription Confirmation",
                "message": f"Your CFO Worx subscription for {company_name} has been renewed successfully. Thank you for your continued business.",
                "action_text": "View Subscription",
            },
            "trial_ending": {
                "subject": "Trial Period Ending Soon",
                "title": "Trial Expiration Notice",
                "message": f"Your trial period for {company_name} is ending soon. Subscribe now to maintain access to all CFO Worx features and your data.",
                "action_text": "Subscribe Now",
            },
            "subscription_cancelled": {
                "subject": "Subscription Cancelled",
                "title": "Subscription Cancellation Confirmed",
                "message": f"Your CFO Worx subscription for {company_name} has been cancelled as requested. Your access will continue until the end of the current billing period.",
                "action_text": "Reactivate Subscription",
            },
        }

        template = templates.get(notification_type, {
            "subject": "Billing Notification",
            "title": "Account Update",
            "message": f"There is an update regarding your {company_name} account. Please review the details below.",
            "action_text": "View Account",
        })

        # Build details table if additional details provided
        details_html = ""
        if details:
            rows = ""
            for key, value in details.items():
                label = key.replace("_", " ").title()
                rows += f"""
                        <tr>
                            <td style="padding: 10px 15px; background-color: #f8f9fa; border: 1px solid #e0e0e0; font-size: 14px; color: #666666; width: 140px;">
                                <strong>{label}</strong>
                            </td>
                            <td style="padding: 10px 15px; border: 1px solid #e0e0e0; font-size: 14px; color: #333333;">
                                {value}
                            </td>
                        </tr>
                """
            if rows:
                details_html = f"""
                    <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                        {rows}
                    </table>
                """

        content = f"""
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        Dear {company_name} Team,
                    </p>
                    
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        {template['message']}
                    </p>
                    
                    {details_html}
                    
                    <p style="color: #666666; font-size: 13px; line-height: 1.6; margin: 20px 0 0 0;">
                        If you have questions regarding your billing or account, please contact our support team.
                    </p>
        """

        html = self._get_base_template(
            title=template["title"],
            content=content,
            button_text=template["action_text"]
        )

        return self.send_email(
            to=to,
            subject=template["subject"],
            html=html,
            db=db,
            realm_id=realm_id,
            email_type="billing",
            tags=[
                {"name": "email_type", "value": "billing"}, 
                {"name": "notification_type", "value": notification_type}
            ],
        )

    def send_error_notification(
        self,
        to: List[str],
        company_name: str,
        error_type: str,
        error_message: str,
        details: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
        realm_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an error notification email to administrators or users.

        Args:
            to: List of recipient email addresses
            company_name: Name of the company
            error_type: Type of error (e.g., "Report Generation Failed")
            error_message: Description of the error
            details: Additional details about the error
            db: Database session for logging (optional)
            realm_id: Company realm ID for logging (optional)

        Returns:
            Dict with 'success' boolean and 'id' or 'error' message
        """
        subject = f"Error Notification: {error_type}"

        details_html = ""
        if details:
            rows = ""
            for key, value in details.items():
                label = key.replace("_", " ").title()
                rows += f"""
                        <tr>
                            <td style="padding: 8px 12px; background-color: #f8f9fa; border: 1px solid #e0e0e0; font-size: 13px; color: #666666;">
                                {label}
                            </td>
                            <td style="padding: 8px 12px; border: 1px solid #e0e0e0; font-size: 13px; color: #333333;">
                                {value}
                            </td>
                        </tr>
                """
            details_html = f"""
                    <table style="width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 13px;">
                        {rows}
                    </table>
            """

        content = f"""
                    <p style="color: #333333; font-size: 15px; line-height: 1.6; margin: 0 0 20px 0;">
                        An error has occurred that requires your attention.
                    </p>
                    
                    <div style="background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 4px; padding: 15px; margin: 20px 0;">
                        <p style="color: #991b1b; font-size: 14px; font-weight: 600; margin: 0 0 10px 0;">
                            {error_type}
                        </p>
                        <p style="color: #7f1d1d; font-size: 14px; margin: 0;">
                            {error_message}
                        </p>
                    </div>
                    
                    {details_html}
                    
                    <p style="color: #666666; font-size: 13px; line-height: 1.6; margin: 20px 0 0 0;">
                        Company: {company_name}<br>
                        Time: {datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')} UTC
                    </p>
        """

        html = self._get_base_template(
            title="Error Notification",
            content=content,
            show_button=False
        )

        return self.send_email(
            to=to,
            subject=subject,
            html=html,
            db=db,
            realm_id=realm_id,
            email_type="error",
            tags=[
                {"name": "email_type", "value": "error"}, 
                {"name": "error_type", "value": error_type.replace(" ", "_")}
            ],
        )


# Create a singleton instance
email_service = EmailService()
