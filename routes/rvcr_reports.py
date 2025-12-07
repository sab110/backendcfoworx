"""
RVCR (Royalty Volume Calculation Report) Generation Endpoint
Generates RVCR reports from QuickBooks ClassSales data
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import tempfile
import os
import json
import uuid
import requests

from db import get_db
from config import ENVIRONMENT
from models import (
    QuickBooksToken,
    CompanyInfo,
    CompanyLicenseMapping,
    GeneratedReport,
)
from services.azure_storage_service import AzureStorageService
from generate_royalty_report import RoyaltyReportGenerator
from routes.quickbooks_auth import get_auth_client

router = APIRouter()

# Initialize services
storage = AzureStorageService(container_name="reports")


# ------------------------------------------------------
# Request Models
# ------------------------------------------------------
class RVCRGenerateRequest(BaseModel):
    """Request model for RVCR generation
    
    Note: Reports are always generated for "Last Month" as per business requirements.
    The date_macro="Last Month" is used for the last month API call, and the YTD call
    uses dynamic dates derived from the Last Month report's actual period.
    """
    realm_id: str
    department_id: str


# ------------------------------------------------------
# Helper Functions
# ------------------------------------------------------
def get_qbo_base_url() -> str:
    """Get QuickBooks API base URL based on environment"""
    return (
        "https://sandbox-quickbooks.api.intuit.com"
        if ENVIRONMENT == "sandbox"
        else "https://quickbooks.api.intuit.com"
    )


def refresh_token_if_expired(token_entry: QuickBooksToken, db: Session) -> str:
    """
    Refresh QuickBooks access token if expired.
    Returns the valid access token.
    Updates both access_token and refresh_token in database.
    """
    if token_entry.is_expired():
        print(f"🔄 Token expired for realm_id: {token_entry.realm_id}, refreshing...")
        try:
            auth_client = get_auth_client()
            auth_client.refresh(refresh_token=token_entry.refresh_token)
            
            # Update tokens in database
            token_entry.access_token = auth_client.access_token
            token_entry.refresh_token = auth_client.refresh_token
            token_entry.expires_at = datetime.utcnow() + timedelta(seconds=3600)
            token_entry.updated_at = datetime.utcnow()
            db.commit()
            
            print(f"✅ Token refreshed successfully for realm_id: {token_entry.realm_id}")
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=401,
                detail=f"Token refresh failed: {str(e)}"
            )
    
    return token_entry.access_token


def query_class_ids(realm_id: str, access_token: str) -> list:
    """
    Query QuickBooks for class IDs needed for RVCR
    Classes: 1 - WATER, 2 - FIRE, 3 - MOLD/BIO HAZARD, 4 - OTHER, 5 - SUBCONTRACT, 6 - RECONSTRUCTION
    """
    base_url = get_qbo_base_url()
    
    # Query for the standard RVCR classes
    class_names = [
        "1 - WATER",
        "2 - FIRE", 
        "3 - MOLD/BIO HAZARD",
        "4 - OTHER",
        "5 - SUBCONTRACT",
        "6 - RECONSTRUCTION"
    ]
    
    # Build the SQL query - fetch all classes and filter client-side
    # This is more reliable than IN clause which can have formatting issues
    query = "SELECT * FROM Class"
    
    url = f"{base_url}/v3/company/{realm_id}/query"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "text/plain"
    }
    params = {
        "query": query,
        "minorversion": "75"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"⚠️ Class query failed: {response.status_code} - {response.text}")
            return []
        
        data = response.json()
        classes = data.get("QueryResponse", {}).get("Class", [])
        
        # Filter classes that match our target names (case-insensitive)
        target_names_lower = [name.lower() for name in class_names]
        matching_ids = []
        
        for cls in classes:
            name = cls.get("Name", "")
            if name.lower() in target_names_lower:
                matching_ids.append(cls.get("Id"))
        
        print(f"✅ Found {len(matching_ids)} matching class IDs: {matching_ids}")
        return matching_ids
        
    except Exception as e:
        print(f"❌ Error querying classes: {str(e)}")
        return []


def fetch_class_sales_report(
    realm_id: str,
    access_token: str,
    department_id: str,
    class_ids: list,
    report_type: str,  # "last_month" or "ytd"
    last_month_end_date: str = None  # For YTD: the EndPeriod from Last Month report (YYYY-MM-DD)
) -> dict:
    """
    Fetch ClassSales report from QuickBooks API
    
    Args:
        realm_id: QuickBooks realm ID
        access_token: Valid access token
        department_id: QuickBooks department ID
        class_ids: List of class IDs to include
        report_type: "last_month" or "ytd"
        last_month_end_date: For YTD report - the end date from the Last Month report (YYYY-MM-DD format)
                            Used to calculate YTD range: Jan 1 of that year to this date
    """
    base_url = get_qbo_base_url()
    url = f"{base_url}/v3/company/{realm_id}/reports/ClassSales"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    # Build class parameter - comma-separated IDs
    class_param = ",".join(class_ids) if class_ids else ""
    
    # Build params based on report type
    params = {
        "summarize_column_by": "Classes",
        "accounting_method": "Cash",
        "department": department_id,
        "minorversion": "75"
    }
    
    # Add class filter if we have class IDs
    if class_param:
        params["class"] = class_param
    
    if report_type == "last_month":
        # Always use date_macro for Last Month - this ensures QuickBooks determines the actual period
        params["date_macro"] = "Last Month"
    else:  # ytd
        # YTD dates are derived from the Last Month report's actual period
        # This ensures YTD aligns with the Last Month being reported
        if not last_month_end_date:
            raise ValueError("last_month_end_date is required for YTD report")
        
        # Parse the end date to determine the year
        end_date = datetime.strptime(last_month_end_date, "%Y-%m-%d")
        start_date = datetime(end_date.year, 1, 1)  # Jan 1 of the same year
        
        params["start_date"] = start_date.strftime("%Y-%m-%d")
        params["end_date"] = end_date.strftime("%Y-%m-%d")
    
    print(f"📊 Fetching {report_type} ClassSales report with params: {params}")
    
    try:
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"QuickBooks ClassSales API error: {response.text}"
            )
        
        data = response.json()
        print(f"✅ Successfully fetched {report_type} report")
        return data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching ClassSales report: {str(e)}"
        )


def generate_report_name(franchise_number: str, period_end: str) -> str:
    """
    Generate report name following convention: Franchise # - mmyyyy RVCR
    Example: 01444 - 082024 RVCR
    """
    try:
        date_obj = datetime.strptime(period_end, "%Y-%m-%d")
        mmyyyy = date_obj.strftime("%m%Y")
    except:
        mmyyyy = datetime.utcnow().strftime("%m%Y")
    
    # Pad franchise number to 5 digits
    padded_franchise = franchise_number.zfill(5)
    
    return f"{padded_franchise} - {mmyyyy} RVCR"


# ------------------------------------------------------
# RVCR Generation Endpoint
# ------------------------------------------------------
@router.post("/generate")
async def generate_rvcr_report(
    request: RVCRGenerateRequest,
    db: Session = Depends(get_db)
):
    """
    Generate RVCR (Royalty Volume Calculation Report) for a franchise
    
    This endpoint:
    1. Validates the realm_id and department_id
    2. Refreshes QuickBooks token if needed
    3. Queries QuickBooks for class IDs
    4. Fetches Last Month and YTD ClassSales reports
    5. Generates Excel and PDF reports
    6. Uploads to Azure Storage
    7. Stores reference in database
    
    File naming convention: {franchise_number} - {mmyyyy} RVCR
    Example: 01444 - 082024 RVCR
    
    Storage path: {realm_id}/{franchise_number}/{year-month}_RVCR_{uuid}.{ext}
    """
    realm_id = request.realm_id
    department_id = request.department_id
    
    print(f"🚀 Starting RVCR generation for realm_id: {realm_id}, department_id: {department_id}")
    
    try:
        # 1. Get and validate QuickBooks token
        token_entry = db.query(QuickBooksToken).filter_by(realm_id=realm_id).first()
        if not token_entry:
            raise HTTPException(
                status_code=404,
                detail=f"No QuickBooks token found for realm_id: {realm_id}"
            )
        
        # 2. Refresh token if expired
        access_token = refresh_token_if_expired(token_entry, db)
        
        # 3. Get company license mapping (department info)
        license_mapping = db.query(CompanyLicenseMapping).filter_by(
            realm_id=realm_id,
            qbo_department_id=department_id
        ).first()
        
        if not license_mapping:
            raise HTTPException(
                status_code=404,
                detail=f"No license mapping found for realm_id: {realm_id}, department_id: {department_id}"
            )
        
        franchise_number = license_mapping.franchise_number
        department_name = license_mapping.qbo_department_name
        
        print(f"📋 Found license mapping: franchise={franchise_number}, department={department_name}")
        
        # 4. Get company info (for group/company name)
        company_info = db.query(CompanyInfo).filter_by(realm_id=realm_id).first()
        if not company_info:
            raise HTTPException(
                status_code=404,
                detail=f"No company info found for realm_id: {realm_id}"
            )
        
        main_group_name = company_info.company_name or "Company"
        print(f"🏢 Company: {main_group_name}")
        
        # 5. Query class IDs from QuickBooks
        class_ids = query_class_ids(realm_id, access_token)
        
        # 6. Fetch Last Month report FIRST (uses date_macro="Last Month")
        # This determines the actual period from QuickBooks
        last_month_data = fetch_class_sales_report(
            realm_id=realm_id,
            access_token=access_token,
            department_id=department_id,
            class_ids=class_ids,
            report_type="last_month"
        )
        
        # 7. Extract the actual period from the Last Month report header
        lm_header = last_month_data.get("Header", {})
        period_start = lm_header.get("StartPeriod", "")
        period_end = lm_header.get("EndPeriod", "")
        report_basis = lm_header.get("ReportBasis", "Cash")
        
        print(f"📅 Last Month period: {period_start} to {period_end}")
        
        if not period_end:
            raise HTTPException(
                status_code=500,
                detail="Could not determine report period from Last Month data"
            )
        
        # 8. Fetch YTD report using dates derived from Last Month's period
        # YTD = Jan 1 of that year to the end of Last Month
        ytd_data = fetch_class_sales_report(
            realm_id=realm_id,
            access_token=access_token,
            department_id=department_id,
            class_ids=class_ids,
            report_type="ytd",
            last_month_end_date=period_end  # Pass the actual end date for YTD calculation
        )
        
        # Generate report name: Franchise # - mmyyyy RVCR
        report_name = generate_report_name(franchise_number, period_end)
        report_title = f"RVCR - {department_name}"
        
        print(f"📝 Report name: {report_name}")
        
        # 8. Save JSON data to temp files
        temp_dir = tempfile.mkdtemp()
        last_month_file = os.path.join(temp_dir, "last_month.json")
        ytd_file = os.path.join(temp_dir, "ytd.json")
        
        with open(last_month_file, 'w', encoding='utf-8') as f:
            json.dump(last_month_data, f, indent=2)
        
        with open(ytd_file, 'w', encoding='utf-8') as f:
            json.dump(ytd_data, f, indent=2)
        
        # 9. Generate Excel and PDF reports
        excel_output = os.path.join(temp_dir, f"{report_name}.xlsx")
        
        generator = RoyaltyReportGenerator()
        pdf_path = None
        pdf_available = False
        
        # 9a. Generate Excel report first (always succeeds)
        try:
            excel_path = generator.generate_report(
                last_month_file=last_month_file,
                ytd_file=ytd_file,
                output_file=excel_output,
                report_title=report_title,
                department_name=department_name,
                main_group_name=main_group_name
            )
            print(f"✅ Excel report generated: {excel_path}")
        except Exception as gen_error:
            print(f"❌ Excel generation error: {str(gen_error)}")
            raise HTTPException(
                status_code=500,
                detail=f"Report generation failed: {str(gen_error)}"
            )
        
        # 9b. Try PDF conversion (optional - may fail in serverless environments)
        try:
            pdf_path = generator.convert_to_pdf(excel_path)
            pdf_available = True
            print(f"✅ PDF report generated: {pdf_path}")
        except Exception as pdf_error:
            print(f"⚠️ PDF conversion skipped (not available in this environment): {str(pdf_error)}")
            pdf_available = False
        
        # 10. Upload to Azure Storage
        # Convention: {client_id}/{franchise_number}/{report_name}.{ext}
        # Example: 9130347220447566/09229/09229 - 112024 RVCR.xlsx
        
        # Read Excel file
        with open(excel_path, 'rb') as f:
            excel_bytes = f.read()
        
        # Upload Excel with proper naming: Franchise # - mmyyyy RVCR
        excel_blob_url, excel_blob_name = storage.upload_file(
            file_data=excel_bytes,
            client_id=realm_id,
            license_id=franchise_number,
            file_name=report_name,  # e.g., "01444 - 082024 RVCR"
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ext="xlsx"
        )
        print(f"☁️ Excel uploaded: {excel_blob_name}")
        
        # Upload PDF only if available
        pdf_blob_url = None
        pdf_blob_name = None
        if pdf_available and pdf_path:
            with open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()
            
            # Upload PDF with same naming convention
            pdf_blob_url, pdf_blob_name = storage.upload_file(
                file_data=pdf_bytes,
                client_id=realm_id,
                license_id=franchise_number,
                file_name=report_name,  # e.g., "01444 - 082024 RVCR"
                content_type="application/pdf",
                ext="pdf"
            )
            print(f"☁️ PDF uploaded: {pdf_blob_name}")
        else:
            print(f"ℹ️ PDF upload skipped (not available)")
        
        # 11. Get period_month in mmyyyy format
        try:
            period_date = datetime.strptime(period_end, "%Y-%m-%d")
            period_month_str = period_date.strftime("%m%Y")
        except:
            period_month_str = datetime.utcnow().strftime("%m%Y")
        
        # 12. Store reference in database
        generated_report = GeneratedReport(
            realm_id=realm_id,
            franchise_number=franchise_number,
            report_type="RVCR",
            report_name=report_name,
            report_title=report_title,
            period_start=period_start,
            period_end=period_end,
            period_month=period_month_str,
            excel_blob_name=excel_blob_name,
            excel_blob_url=excel_blob_url,
            pdf_blob_name=pdf_blob_name,
            pdf_blob_url=pdf_blob_url,
            qbo_department_id=department_id,
            qbo_department_name=department_name,
            report_basis=report_basis,
            status="generated",
            generated_at=datetime.utcnow()
        )
        db.add(generated_report)
        db.commit()
        db.refresh(generated_report)
        
        print(f"💾 Report record saved: ID={generated_report.id}")
        
        # 13. Cleanup temp files
        try:
            os.remove(last_month_file)
            os.remove(ytd_file)
            os.remove(excel_path)
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)
            os.rmdir(temp_dir)
        except Exception as cleanup_error:
            print(f"⚠️ Cleanup warning: {cleanup_error}")
        
        # 14. Generate SAS URLs for immediate download
        excel_sas_url = storage.generate_sas_url(excel_blob_name)  # Default 10 years expiry
        pdf_sas_url = storage.generate_sas_url(pdf_blob_name) if pdf_blob_name else None
        
        # Build response message
        if pdf_available:
            message = f"RVCR report generated successfully for {department_name}"
        else:
            message = f"RVCR Excel report generated for {department_name} (PDF not available in serverless environment)"
        
        return {
            "status": "success",
            "message": message,
            "pdf_available": pdf_available,
            "report": {
                "id": generated_report.id,
                "report_name": report_name,
                "report_title": report_title,
                "franchise_number": franchise_number,
                "department_name": department_name,
                "period_start": period_start,
                "period_end": period_end,
                "period_month": period_month_str,
                "report_basis": report_basis,
                "generated_at": generated_report.generated_at.isoformat()
            },
            "files": {
                "excel": {
                    "blob_name": excel_blob_name,
                    "blob_url": excel_blob_url,
                    "download_url": excel_sas_url
                },
                "pdf": {
                    "blob_name": pdf_blob_name,
                    "blob_url": pdf_blob_url,
                    "download_url": pdf_sas_url
                } if pdf_available else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"❌ RVCR generation error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"RVCR generation failed: {str(e)}"
        )


# ------------------------------------------------------
# Get RVCR Report by ID
# ------------------------------------------------------
@router.get("/{report_id}")
async def get_rvcr_report(
    report_id: int,
    db: Session = Depends(get_db)
):
    """
    Get RVCR report details by ID
    """
    report = db.query(GeneratedReport).filter_by(
        id=report_id,
        report_type="RVCR"
    ).first()
    
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"RVCR report not found: {report_id}"
        )
    
    # Generate fresh download URLs
    excel_sas_url = None
    pdf_sas_url = None
    
    if report.excel_blob_name:
        excel_sas_url = storage.generate_sas_url(report.excel_blob_name)  # Default 10 years expiry
    
    if report.pdf_blob_name:
        pdf_sas_url = storage.generate_sas_url(report.pdf_blob_name)  # Default 10 years expiry
    
    return {
        "id": report.id,
        "realm_id": report.realm_id,
        "franchise_number": report.franchise_number,
        "report_name": report.report_name,
        "report_title": report.report_title,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "period_month": report.period_month,
        "qbo_department_id": report.qbo_department_id,
        "qbo_department_name": report.qbo_department_name,
        "report_basis": report.report_basis,
        "status": report.status,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "files": {
            "excel": {
                "blob_name": report.excel_blob_name,
                "blob_url": report.excel_blob_url,
                "download_url": excel_sas_url
            },
            "pdf": {
                "blob_name": report.pdf_blob_name,
                "blob_url": report.pdf_blob_url,
                "download_url": pdf_sas_url
            }
        }
    }


# ------------------------------------------------------
# List RVCR Reports for a Realm/Franchise
# ------------------------------------------------------
@router.get("/list/{realm_id}")
async def list_rvcr_reports(
    realm_id: str,
    franchise_number: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    List RVCR reports for a realm, optionally filtered by franchise number
    """
    query = db.query(GeneratedReport).filter_by(
        realm_id=realm_id,
        report_type="RVCR"
    )
    
    if franchise_number:
        query = query.filter_by(franchise_number=franchise_number)
    
    # Order by most recent first
    query = query.order_by(GeneratedReport.generated_at.desc())
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    reports = query.offset(offset).limit(limit).all()
    
    # Format response
    report_list = []
    for report in reports:
        # Generate fresh download URLs
        excel_sas_url = None
        pdf_sas_url = None
        
        if report.excel_blob_name:
            try:
                excel_sas_url = storage.generate_sas_url(report.excel_blob_name)  # Default 10 years expiry
            except:
                pass
        
        if report.pdf_blob_name:
            try:
                pdf_sas_url = storage.generate_sas_url(report.pdf_blob_name)  # Default 10 years expiry
            except:
                pass
        
        report_list.append({
            "id": report.id,
            "franchise_number": report.franchise_number,
            "report_name": report.report_name,
            "report_title": report.report_title,
            "period_month": report.period_month,
            "qbo_department_name": report.qbo_department_name,
            "status": report.status,
            "generated_at": report.generated_at.isoformat() if report.generated_at else None,
            "excel_download_url": excel_sas_url,
            "pdf_download_url": pdf_sas_url
        })
    
    return {
        "status": "success",
        "total": total,
        "limit": limit,
        "offset": offset,
        "reports": report_list
    }


# ------------------------------------------------------
# Generate RVCR for All Franchises in a Realm
# ------------------------------------------------------
@router.post("/generate-all/{realm_id}")
async def generate_all_rvcr_reports(
    realm_id: str,
    db: Session = Depends(get_db)
):
    """
    Generate RVCR reports for all franchises/departments in a realm
    
    This is useful for generating monthly reports for all locations at once.
    Reports are always generated for "Last Month" as determined by QuickBooks.
    """
    # Get all active license mappings for this realm
    mappings = db.query(CompanyLicenseMapping).filter_by(
        realm_id=realm_id,
        is_active="true"
    ).all()
    
    if not mappings:
        raise HTTPException(
            status_code=404,
            detail=f"No active license mappings found for realm_id: {realm_id}"
        )
    
    results = []
    errors = []
    
    for mapping in mappings:
        try:
            # Create request for each department (always generates for Last Month)
            request = RVCRGenerateRequest(
                realm_id=realm_id,
                department_id=mapping.qbo_department_id
            )
            
            # Generate report
            result = await generate_rvcr_report(request, db)
            results.append({
                "franchise_number": mapping.franchise_number,
                "department_name": mapping.qbo_department_name,
                "status": "success",
                "report_id": result.get("report", {}).get("id")
            })
            
        except Exception as e:
            errors.append({
                "franchise_number": mapping.franchise_number,
                "department_name": mapping.qbo_department_name,
                "status": "error",
                "error": str(e)
            })
    
    return {
        "status": "completed",
        "total_franchises": len(mappings),
        "successful": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors
    }

