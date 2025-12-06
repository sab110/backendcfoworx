from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import FRONTEND_URL
from routes.stripe_integration import router as stripe_router
from routes.reports import router as reports_router
from routes.quickbooks_auth import router as quickbooks_router
from routes.subscriptions import router as subscriptions_router
from routes.licenses import router as licenses_router
from routes.admin import router as admin_router
from routes.email_preferences import router as email_preferences_router
from routes.rvcr_reports import router as rvcr_router
from db import engine, Base


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Royalties Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://royaltiesagent.com",
        "https://www.royaltiesagent.com",
        "https://staging.royaltiesagent.com",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

app.include_router(stripe_router,   prefix="/api/stripe",     tags=["Stripe Billing"])
app.include_router(reports_router,  prefix="/api/reports",    tags=["Reports"])
app.include_router(quickbooks_router, prefix="/api/quickbooks", tags=["QuickBooks SSO"])
app.include_router(subscriptions_router, prefix="/api/subscriptions", tags=["Subscriptions"])
app.include_router(licenses_router, prefix="/api/licenses", tags=["Licenses"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(email_preferences_router, prefix="/api/email-preferences", tags=["Email Preferences"])
app.include_router(rvcr_router, prefix="/api/rvcr", tags=["RVCR Reports"])

@app.get("/")
def root():
    return {"message": "API is running!"}

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "message": "Royalties Automation API is running",
        "version": "1.0.0"
    }
