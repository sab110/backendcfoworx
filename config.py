import os
from dotenv import load_dotenv
load_dotenv()

# Load environment variables
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PORTAL_CONFIGURATION_ID=os.getenv("STRIPE_PORTAL_CONFIGURATION_ID")
AZURE_STORAGE_CONNECTION_STRING=os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_CONTAINER_NAME=os.getenv("AZURE_STORAGE_CONTAINER_NAME")

# Database settings
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_SERVER_NAME = os.getenv("DB_SERVER_NAME")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME", "postgres")

# QuickBooks OAuth settings
QUICKBOOKS_CLIENT_ID = os.getenv("CLIENT_ID")
QUICKBOOKS_CLIENT_SECRET = os.getenv("CLIENT_SECRET")
QUICKBOOKS_REDIRECT_URI = os.getenv("QUICKBOOKS_REDIRECT_URI")
ENVIRONMENT = os.getenv("ENVIRONMENT", "sandbox")

# Admin credentials
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # Change in .env!
ADMIN_JWT_SECRET = os.getenv("ADMIN_JWT_SECRET", "your-super-secret-key-change-in-production")
ADMIN_JWT_EXPIRY_HOURS = int(os.getenv("ADMIN_JWT_EXPIRY_HOURS", "24"))