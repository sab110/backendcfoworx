from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from services.azure_storage_service import AzureStorageService
from typing import Optional

router = APIRouter()

# Initialize storage service
storage = AzureStorageService(container_name="reports")

# ---------------------------------------------------------------------
#  POST /api/reports/upload
# ---------------------------------------------------------------------
@router.post("/upload")
async def upload_report(
    client_id: str = Form(...),
    license_id: str = Form(...),
    report_type: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Uploads ILRM / RVCR / PaymentSummary reports to Azure Blob Storage.

    As per:
      - SOW §6.1.1 (Blob Storage for reports/artifacts)
      - FRD §6.11, §6.18, §7 (Data Storage & Deliverables)
    """
    try:
        content = await file.read()
        content_type = file.content_type or "application/octet-stream"
        ext = file.filename.split(".")[-1]

        blob_url, blob_name = storage.upload_file(
            content,
            client_id=client_id,
            license_id=license_id,
            report_type=report_type,
            content_type=content_type,
            ext=ext,
        )

        return JSONResponse(
            content={
                "status": "success",
                "message": f"{report_type} uploaded successfully.",
                "blob_name": blob_name,
                "blob_url": blob_url,
            },
            status_code=201,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------
#  GET /api/reports/download-url/{blob_name}
# ---------------------------------------------------------------------
@router.get("/download-url/{blob_name}")
def get_download_url(blob_name: str, expiry_minutes: Optional[int] = 30):
    """
    Generates a signed (temporary) SAS URL for secure report download.

    References:
      - SOW §6.6.2 (“GET /api/reports/{clientId}/{yyyy-mm}” → signed URL)
      - FRD §6.18 (Secure file-based access per franchise)
    """
    try:
        sas_url = storage.generate_sas_url(blob_name, expiry_minutes=expiry_minutes)
        return {"status": "success", "signed_url": sas_url, "expires_in_minutes": expiry_minutes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------
#  GET /api/reports/list
# ---------------------------------------------------------------------
@router.get("/list")
def list_reports(client_id: Optional[str] = None, license_id: Optional[str] = None):
    """
    Lists all stored reports for a specific client or license.

    References:
      - FRD §6.17 (Log retention)
      - FRD §6.23 (Admin dashboard failure log / file visibility)
    """
    try:
        reports = storage.list_files(client_id=client_id, license_id=license_id)
        return {"status": "success", "count": len(reports), "reports": reports}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------
#  DELETE /api/reports/{blob_name}
# ---------------------------------------------------------------------
@router.delete("/{blob_name}")
def delete_report(blob_name: str):
    """
    Deletes a report file from Azure Blob Storage.

    References:
      - FRD §6.17 (Retention cleanup)
      - Admin override / maintenance control
    """
    try:
        success = storage.delete_file(blob_name)
        if success:
            return {"status": "success", "message": f"Blob {blob_name} deleted successfully."}
        else:
            raise HTTPException(status_code=404, detail="Blob not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
