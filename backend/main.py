from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from db.mdb import ConfigurationError, close_connector
from shared.aae_client import AgentEngineConfigurationError

# Routers, grouped by which database they touch.
#   insurance/   members' insurance record, policies, plans, claims   (insurance database)
#   views/       composed reads: the combined member, traces with their step text (both)
#   workflow/    start / progress / medical-director decision                       (both)
#   admin/       seed and reset                                                     (both)
from insurance.policies.routes import router as policies_router
from insurance.claims.routes import router as claims_router
from insurance.plans.routes import router as plans_router
from views.routes import members_router, audit_router
from admin.routes import router as admin_router
from workflow.routes import router as workflow_router
from chat.routes import router as chat_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The shared MongoClient is created lazily on first request via the connector getters.
    yield
    # Close the connection pool cleanly on shutdown.
    close_connector()


app = FastAPI(
    title="Care Coordination Backend",
    description="API for member care coordination, continuous authorization, and clinical decision support",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ConfigurationError)
async def configuration_error(request: Request, exc: ConfigurationError):
    """A required environment variable is missing. 503, naming it, rather than a 500 with a
    stack trace: the service is up, it is just not configured for this route."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(AgentEngineConfigurationError)
async def agent_engine_configuration_error(request: Request, exc: AgentEngineConfigurationError):
    """The agents' credentials or targets are not configured: 503 naming every missing
    variable (never a value), for the same reason as above."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})


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


# Insurance-side routers
app.include_router(policies_router)
app.include_router(claims_router)
app.include_router(plans_router)
# Composed reads. `/api/members/{id}` is the combined member document the frontend has
# always read; `/api/audit/...` returns traces with their step text.
app.include_router(members_router)
app.include_router(audit_router)
app.include_router(admin_router)
# Same admin handlers again under `/api/admin`. The root mount stays for curl and
# the seed CLI, but the browser can only reach the backend through the frontend's
# `/api/*` proxy, so the "Reset demo" button needs a prefixed path to call.
app.include_router(admin_router, prefix="/api/admin")
# Frontend-facing workflow entry points (Start Process, progress, human closure).
app.include_router(workflow_router)
# Free-form chat with the same agents, independent of the authorization workflow.
app.include_router(chat_router)
