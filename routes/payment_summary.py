"""
Payment Summary (Royalty Report) API Routes
Endpoints for generating and managing payment summary reports
"""

import os
import tempfile
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import (
    QuickBooksToken,
    CompanyInfo,
    CompanyLicenseMapping,
    GeneratedReport,
    EmailPreference
)
from services.azure_storage_service import AzureStorageService
from services.email_service import email_service
from services.payment_summary_generator import (
    calculate_payment_summary,
    generate_payment_summary_excel,
    convert_excel_to_pdf,
)
from routes.rvcr_reports import (
    fetch_class_sales_report,
    query_class_ids,
    get_qbo_base_url,
    refresh_token_if_expired,
    get_report_recipients,
    format_period_display,
    send_report_email
)

router = APIRouter()


# ============================================================================
# REQUEST MODELS
# ============================================================================

class PaymentSummaryRequest(BaseModel):
    realm_id: str
    department_id: str


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/generate")
async def generate_payment_summary_endpoint(
    request: PaymentSummaryRequest,
    db: Session = Depends(get_db)
):
    """
    Generate Payment Summary (Royalty Report) for a specific franchise.
    """
    realm_id = request.realm_id
    department_id = request.department_id

    print(f"Starting Payment Summary generation for realm_id: {realm_id}, department_id: {department_id}")

    try:
        # 1. Get token from database
        token_record = db.query(QuickBooksToken).filter(
            QuickBooksToken.realm_id == realm_id
        ).first()

        if not token_record:
            raise HTTPException(status_code=404, detail=f"No QuickBooks token found for realm_id: {realm_id}")

        # 2. Refresh token if needed
        access_token = refresh_token_if_expired(token_record, db)

        # 3. Get company info
        company_info = db.query(CompanyInfo).filter(
            CompanyInfo.realm_id == realm_id
        ).first()

        # 4. Get license mapping for department
        mapping = db.query(CompanyLicenseMapping).filter(
            CompanyLicenseMapping.realm_id == realm_id,
            CompanyLicenseMapping.qbo_department_id == department_id,
            CompanyLicenseMapping.is_active == "true"
        ).first()

        if not mapping:
            raise HTTPException(
                status_code=404,
                detail=f"No license mapping found for department_id: {department_id}"
            )

        franchise_number = mapping.franchise_number
        department_name = mapping.qbo_department_name or "Unknown"

        print(f"Franchise: {franchise_number}, Department: {department_name}")

        # 5. Query class IDs
        class_ids = query_class_ids(realm_id, access_token)

        # 6. Calculate period dates
        now = datetime.utcnow()
        last_month = now - relativedelta(months=1)
        period_start = datetime(last_month.year, last_month.month, 1).strftime("%Y-%m-%d")
        period_end = (datetime(last_month.year, last_month.month, 1) + relativedelta(months=1) - timedelta(days=1)).strftime("%Y-%m-%d")

        period_month = last_month.month
        period_year = last_month.year

        print(f"Period: {period_start} to {period_end}")

        # 7. Fetch Last Month report
        last_month_data = fetch_class_sales_report(
            realm_id=realm_id,
            access_token=access_token,
            department_id=department_id,
            class_ids=class_ids,
            report_type="last_month"
        )

        # 8. Fetch YTD report
        ytd_data = fetch_class_sales_report(
            realm_id=realm_id,
            access_token=access_token,
            department_id=department_id,
            class_ids=class_ids,
            report_type="ytd"
        )

        # 9. Calculate payment summary
        summary = calculate_payment_summary(
            last_month_data=last_month_data,
            ytd_data=ytd_data,
            franchise_number=franchise_number,
            department_name=department_name,
            owner_name=company_info.company_name if company_info else "",
            period_month=period_month,
            period_year=period_year
        )

        # 10. Generate report name: Franchise # - mmyyyy Payment Summary
        report_name = f"{franchise_number} - {period_month:02d}{period_year} Payment Summary"

        # 11. Generate Excel file
        temp_dir = tempfile.mkdtemp()
        excel_path = os.path.join(temp_dir, f"{report_name}.xlsx")

        generate_payment_summary_excel(summary, excel_path)
        print(f"Excel generated: {excel_path}")

        # 12. Try to generate PDF
        pdf_path = os.path.join(temp_dir, f"{report_name}.pdf")
        pdf_available = convert_excel_to_pdf(excel_path, pdf_path)

        if pdf_available:
            print(f"PDF generated: {pdf_path}")
        else:
            print(f"PDF generation not available")

        # 13. Upload to Azure Storage
        storage = AzureStorageService()

        with open(excel_path, 'rb') as f:
            excel_bytes = f.read()

        excel_blob_url, excel_blob_name = storage.upload_file(
            file_data=excel_bytes,
            client_id=realm_id,
            license_id=franchise_number,
            # file_name=report_name,
            report_type=report_name,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ext="xlsx"
        )
        print(f"Excel uploaded: {excel_blob_name}")

        pdf_blob_url = None
        pdf_blob_name = None
        if pdf_available and os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()

            pdf_blob_url, pdf_blob_name = storage.upload_file(
                file_data=pdf_bytes,
                client_id=realm_id,
                license_id=franchise_number,
                # file_name=report_name,
                report_type=report_name,
                content_type="application/pdf",
                ext="pdf"
            )
            print(f"PDF uploaded: {pdf_blob_name}")

        # 14. Generate SAS URLs (10 year expiry)
        excel_sas_url = storage.generate_sas_url(excel_blob_name)
        pdf_sas_url = storage.generate_sas_url(pdf_blob_name) if pdf_blob_name else None

        # 15. Save to database
        # Format period_month as "mmyyyy" string (matching RVCR format)
        period_month_str = f"{period_month:02d}{period_year}"

        report_record = GeneratedReport(
            realm_id=realm_id,
            franchise_number=franchise_number,
            report_type="payment_summary",
            report_name=report_name,
            report_title=f"Payment Summary - {franchise_number}",
            period_start=period_start,
            period_end=period_end,
            period_month=period_month_str,
            excel_blob_url=excel_blob_url,
            excel_blob_name=excel_blob_name,
            pdf_blob_url=pdf_blob_url,
            pdf_blob_name=pdf_blob_name,
            qbo_department_id=department_id,
            qbo_department_name=department_name,
            report_basis="Cash",
            status="generated"
        )
        db.add(report_record)
        db.commit()

        # 16. Send email notification with attachments
        company_name = company_info.company_name if company_info else "Company"
        report_period_display = format_period_display(period_end)
        email_result = send_report_email(
            db=db,
            realm_id=realm_id,
            company_name=company_name,
            report_type="Payment Summary",
            report_period=report_period_display,
            franchise_number=franchise_number,
            excel_path=excel_path,
            pdf_path=pdf_path if pdf_available else None,
            excel_url=excel_sas_url,
            pdf_url=pdf_sas_url
        )

        # 17. Cleanup temp files
        try:
            os.remove(excel_path)
            if pdf_available and os.path.exists(pdf_path):
                os.remove(pdf_path)
            os.rmdir(temp_dir)
        except Exception as e:
            print(f"Temp cleanup warning: {e}")

        print(f"Payment Summary generated successfully for {franchise_number}")

        return {
            "success": True,
            "report_id": report_record.id,
            "franchise_number": franchise_number,
            "department_name": department_name,
            "period": f"{period_month:02d}/{period_year}",
            "excel_download_url": excel_sas_url,
            "pdf_download_url": pdf_sas_url,
            "pdf_available": pdf_available,
            "summary": summary
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Payment Summary generation error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-all/{realm_id}")
async def generate_all_payment_summaries(
    realm_id: str,
    db: Session = Depends(get_db)
):
    """
    Generate Payment Summary reports for all franchises of a company.
    """
    print(f"Starting bulk Payment Summary generation for realm_id: {realm_id}")

    # Get all active license mappings for this company
    mappings = db.query(CompanyLicenseMapping).filter(
        CompanyLicenseMapping.realm_id == realm_id,
        CompanyLicenseMapping.is_active == "true"
    ).all()

    if not mappings:
        raise HTTPException(
            status_code=404,
            detail=f"No active license mappings found for realm_id: {realm_id}"
        )

    results = []
    for mapping in mappings:
        try:
            request = PaymentSummaryRequest(
                realm_id=realm_id,
                department_id=mapping.qbo_department_id
            )
            result = await generate_payment_summary_endpoint(request, db)
            results.append({
                "franchise_number": mapping.franchise_number,
                "department_name": mapping.qbo_department_name,
                "success": True,
                "report_id": result["report_id"],
                "excel_download_url": result["excel_download_url"],
                "pdf_download_url": result["pdf_download_url"],
            })
        except Exception as e:
            results.append({
                "franchise_number": mapping.franchise_number,
                "department_name": mapping.qbo_department_name,
                "success": False,
                "error": str(e)
            })

    success_count = sum(1 for r in results if r["success"])

    return {
        "realm_id": realm_id,
        "total": len(results),
        "success_count": success_count,
        "failed_count": len(results) - success_count,
        "results": results
    }


@router.get("/list/{realm_id}")
async def list_payment_summaries(
    realm_id: str,
    db: Session = Depends(get_db)
):
    """
    List all Payment Summary reports for a company.
    """
    reports = db.query(GeneratedReport).filter(
        GeneratedReport.realm_id == realm_id,
        GeneratedReport.report_type == "payment_summary"
    ).order_by(GeneratedReport.generated_at.desc()).all()

    storage = AzureStorageService()

    result = []
    for report in reports:
        excel_url = storage.generate_sas_url(report.excel_blob_name) if report.excel_blob_name else None
        pdf_url = storage.generate_sas_url(report.pdf_blob_name) if report.pdf_blob_name else None

        # Parse period_month (mmyyyy format) for display
        pm = report.period_month or ""
        display_month = pm[:2] if len(pm) >= 2 else ""
        display_year = pm[2:] if len(pm) >= 4 else ""

        result.append({
            "id": report.id,
            "franchise_number": report.franchise_number,
            "report_name": report.report_name,
            "period_month": display_month,
            "period_year": display_year,
            "period_start": report.period_start,
            "period_end": report.period_end,
            "department_name": report.qbo_department_name,
            "generated_at": report.generated_at.isoformat() if report.generated_at else None,
            "excel_download_url": excel_url,
            "pdf_download_url": pdf_url,
        })

    return {
        "realm_id": realm_id,
        "count": len(result),
        "reports": result
    }


@router.get("/{report_id}")
async def get_payment_summary(
    report_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific Payment Summary report.
    """
    report = db.query(GeneratedReport).filter(
        GeneratedReport.id == report_id,
        GeneratedReport.report_type == "payment_summary"
    ).first()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    storage = AzureStorageService()

    excel_url = storage.generate_sas_url(report.excel_blob_name) if report.excel_blob_name else None
    pdf_url = storage.generate_sas_url(report.pdf_blob_name) if report.pdf_blob_name else None

    # Parse period_month (mmyyyy format) for display
    pm = report.period_month or ""
    display_month = pm[:2] if len(pm) >= 2 else ""
    display_year = pm[2:] if len(pm) >= 4 else ""

    return {
        "id": report.id,
        "realm_id": report.realm_id,
        "franchise_number": report.franchise_number,
        "report_name": report.report_name,
        "period_month": display_month,
        "period_year": display_year,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "department_name": report.qbo_department_name,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "excel_download_url": excel_url,
        "pdf_download_url": pdf_url,
    }
