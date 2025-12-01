from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import FRONTEND_URL
from routes.stripe_integration import router as stripe_router
from routes.reports import router as reports_router
from routes.quickbooks_auth import router as quickbooks_router
from routes.subscriptions import router as subscriptions_router
from routes.licenses import router as licenses_router
from db import engine, Base


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Royalties Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://royaltiesagent.com",
        "https://www.royaltiesagent.com",
        "https://staging.royaltiesagent.com"
    ],
    
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stripe_router,   prefix="/api/stripe",     tags=["Stripe Billing"])
app.include_router(reports_router,  prefix="/api/reports",    tags=["Reports"])
app.include_router(quickbooks_router, prefix="/api/quickbooks", tags=["QuickBooks SSO"])
app.include_router(subscriptions_router, prefix="/api/subscriptions", tags=["Subscriptions"])
app.include_router(licenses_router, prefix="/api/licenses", tags=["Licenses"])

@app.get("/")
def root():
    return {"message": "API is running!"}
