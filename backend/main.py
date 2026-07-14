from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Import routers from each domain
from members.routes import router as members_router
from authorizations.routes import router as authorizations_router
from claims.routes import router as claims_router
from guidelines.routes import router as guidelines_router
from audit.routes import router as audit_router
from plans.routes import router as plans_router

load_dotenv()

app = FastAPI(
    title="Care Coordination Backend",
    description="API for member care coordination, continuous authorization, and clinical decision support",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def read_root():
    return {
        "message": "Care Coordination Backend API",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Include domain routers
app.include_router(members_router)
app.include_router(authorizations_router)
app.include_router(claims_router)
app.include_router(guidelines_router)
app.include_router(audit_router)
app.include_router(plans_router)
