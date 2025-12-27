import os
import uuid
from datetime import datetime, timedelta
from azure.storage.blob import (
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
    BlobSasPermissions,
)
from config import AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER_NAME
from azure.core.exceptions import ResourceNotFoundError


class AzureStorageService:
    """
    Azure Blob Storage Service
    -------------------------------------------------------
    Implements all report storage and retrieval features as
    defined in:
    • SOW §6.1.1, §6.2, §6.6.2
    • FRD §6.11, §6.17, §6.18, §6.23, §9

    Handles:
    - Upload (PDF/CSV reports)
    - Tenant-based folder organization
    - Secure SAS-based download URLs
    - Listing & Deletion for admin dashboards
    """

    def __init__(self, container_name: str = "reports"):
        if not AZURE_STORAGE_CONNECTION_STRING:
            raise ValueError("Missing AZURE_STORAGE_CONNECTION_STRING in environment variables.")

        self.container_name = AZURE_STORAGE_CONTAINER_NAME
        self.blob_service_client = BlobServiceClient.from_connection_string(
            AZURE_STORAGE_CONNECTION_STRING
        )
        self.container_client = self._ensure_container()

    # -----------------------------------------------------------------
    # Ensure container exists
    # -----------------------------------------------------------------
    def _ensure_container(self):
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)

            # Try to get the container properties to check if it exists
            try:
                container_client.get_container_properties()  # Will raise ResourceNotFoundError if not exists
            except ResourceNotFoundError:
                # Container doesn't exist, so create it
                container_client.create_container()
                print(f"Created container: {self.container_name}")

            return container_client
        except Exception as e:
            raise RuntimeError(f"Failed to create/get container: {e}")

    # -----------------------------------------------------------------
    # Standardized blob naming convention per FRD §6.11
    # Format: {client_id}/{franchise_number}/{file_name}.{ext}
    # -----------------------------------------------------------------
    def _generate_blob_name(self, client_id: str, license_id: str, file_name: str, ext: str):
        """
        Generate blob name with format: {client_id}/{license_id}/{file_name}.{ext}

        Args:
            client_id: The realm_id / client identifier
            license_id: The franchise number
            file_name: The file name (e.g., "01444 - 082024 RVCR")
            ext: File extension (e.g., "xlsx", "pdf")
        """
        # Sanitize file name for blob storage (remove any path separators)
        safe_file_name = file_name.replace("/", "-").replace("\\", "-")
        blob_name = f"{client_id}/{license_id}/{safe_file_name}.{ext}"
        return blob_name

    # -----------------------------------------------------------------
    # Upload a file and return its URL + blob_name
    # -----------------------------------------------------------------
    def upload_file(
        self,
        file_data: bytes,
        client_id: str,
        license_id: str,
        file_name: str,
        content_type: str,
        ext: str,
    ):
        """
        Uploads file bytes to Azure Blob Storage.
        Stores using structured tenant paths:
        {client_id}/{license_id}/{file_name}.{ext}

        Args:
            client_id: The realm_id / client identifier
            license_id: The franchise number
            file_name: The file name (e.g., "01444 - 082024 RVCR")
            content_type: MIME type of the file
            ext: File extension
        """
        try:
            blob_name = self._generate_blob_name(client_id, license_id, file_name, ext)
            blob_client = self.container_client.get_blob_client(blob_name)

            blob_client.upload_blob(
                file_data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )

            blob_url = blob_client.url
            print(f"Uploaded {file_name}.{ext} for client {client_id} -> {blob_url}")
            return blob_url, blob_name
        except Exception as e:
            raise RuntimeError(f"Upload failed for {file_name}: {e}")

    # -----------------------------------------------------------------
    # Generate signed SAS URL for secure download
    # -----------------------------------------------------------------
    def generate_sas_url(self, blob_name: str, expiry_years: int = 10):
        """
        Generates a signed URL for secure download access.
        Default expiry = 10 years (long-lived URLs for reports).
        """
        try:
            account_name = self.blob_service_client.account_name
            account_key = self._extract_account_key()

            # Calculate expiry: 10 years = ~3652 days
            expiry_days = expiry_years * 365

            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=self.container_name,
                blob_name=blob_name,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(days=expiry_days),
            )

            sas_url = f"https://{account_name}.blob.core.windows.net/{self.container_name}/{blob_name}?{sas_token}"
            print(f"SAS URL generated (expires in {expiry_years} years)")
            return sas_url
        except Exception as e:
            raise RuntimeError(f"SAS generation failed: {e}")

    # -----------------------------------------------------------------
    # List files (for Admin Dashboard FRD §6.23)
    # -----------------------------------------------------------------
    def list_files(self, client_id: str = None, license_id: str = None):
        """
        Returns a list of all blobs (optionally filtered by client/license).
        Used for admin visibility and report tracking.
        """
        try:
            prefix = ""
            if client_id and license_id:
                prefix = f"{client_id}/{license_id}/"
            elif client_id:
                prefix = f"{client_id}/"

            blobs = self.container_client.list_blobs(name_starts_with=prefix)
            return [
                {
                    "name": blob.name,
                    "size": blob.size,
                    "last_modified": blob.last_modified.isoformat(),
                    "url": self.container_client.get_blob_client(blob.name).url,
                }
                for blob in blobs
            ]
        except Exception as e:
            raise RuntimeError(f"Listing failed: {e}")

    # -----------------------------------------------------------------
    # Download file as bytes
    # -----------------------------------------------------------------
    def download_file(self, blob_name: str):
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            return blob_client.download_blob().readall()
        except Exception as e:
            raise RuntimeError(f"Download failed for {blob_name}: {e}")

    # -----------------------------------------------------------------
    # Delete a blob (for log retention and retries)
    # -----------------------------------------------------------------
    def delete_file(self, blob_name: str):
        try:
            blob_client = self.container_client.get_blob_client(blob_name)
            blob_client.delete_blob()
            print(f"Deleted blob {blob_name}")
            return True
        except Exception as e:
            raise RuntimeError(f"Delete failed for {blob_name}: {e}")

    # -----------------------------------------------------------------
    # Extract Account Key from Connection String (for SAS generation)
    # -----------------------------------------------------------------
    def _extract_account_key(self):
        try:
            for part in AZURE_STORAGE_CONNECTION_STRING.split(";"):
                if part.strip().startswith("AccountKey="):
                    return part.split("=", 1)[1]
            raise ValueError("AccountKey not found in connection string.")
        except Exception as e:
            raise RuntimeError(f"Failed to extract AccountKey: {e}")


# ---------------------------------------------------------------------
# Example Usage
# ---------------------------------------------------------------------
# from services.azure_storage_service import AzureStorageService
#
# storage = AzureStorageService()
#
# # Upload a PDF report
# blob_url, blob_name = storage.upload_file(
#     pdf_bytes,
#     client_id="CFOWorx",
#     license_id="SERV1234",
#     report_type="PaymentSummary",
#     content_type="application/pdf",
#     ext="pdf",
# )
#
# # Generate secure SAS URL for client download
# signed_url = storage.generate_sas_url(blob_name, expiry_minutes=60)
#
# # List files for Admin Dashboard
# files = storage.list_files(client_id="CFOWorx")
