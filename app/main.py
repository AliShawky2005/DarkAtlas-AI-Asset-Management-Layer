from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import engine, Base, AsyncSessionLocal
from app.middleware.rate_limit import limiter
import app.models  # noqa: F401 — registers all ORM models with Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables and seed the default organization on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure the default org exists (needed for legacy callers with no X-Org-Id)
    async with AsyncSessionLocal() as session:
        try:
            from app.services.auth_service import ensure_default_org
            await ensure_default_org(session)
            await session.commit()
        except Exception:
            await session.rollback()

    print(f"[DarkAtlas] Tables synced. API v{settings.APP_VERSION} ready.")
    yield
    await engine.dispose()
    print("[DarkAtlas] Shutdown complete.")


app = FastAPI(
    title="DarkAtlas — AI Asset Management",
    description=(
        "Track B + All Bonuses: LangChain-powered analysis layer for Buguard's "
        "DarkAtlas Attack Surface Management platform.\n\n"
        "**Auth:** All endpoints require `X-API-Key` header.\n"
        "- `admin` role: full access (import, enrich, manage keys)\n"
        "- `reader` role: read-only (list, analyze, report)\n\n"
        "**Multi-tenancy:** Pass `X-Org-Id` header to scope data to an organization. "
        "Defaults to `default` org.\n\n"
        "**Rate limits:** 60/min global · 10/min LLM endpoints · 5/min agent"
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# ── Rate limiter ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.routes.assets        import router as assets_router
from app.api.routes.analyze       import router as analyze_router
from app.api.routes.organizations import router as orgs_router
from app.api.routes.auth          import router as auth_router
from app.api.routes.graph         import router as graph_router
from app.api.routes.agent         import router as agent_router
from app.api.routes.eval          import router as eval_router

app.include_router(assets_router, prefix="/api/v1/assets",   tags=["Assets"])
app.include_router(analyze_router, prefix="/api/v1/analyze", tags=["Analysis"])
app.include_router(orgs_router,  prefix="/api/v1/orgs",      tags=["Organizations"])
app.include_router(auth_router,  prefix="/api/v1/auth",      tags=["Auth & Keys"])
app.include_router(graph_router, prefix="/api/v1/graph",     tags=["Graph"])
app.include_router(agent_router, prefix="/api/v1/agent",     tags=["AI Agent"])
app.include_router(eval_router,  prefix="/api/v1/eval",      tags=["Evaluation"])

# ── Graph visualization page (no /api prefix — served at /graph) ──────────────
from app.api.routes.graph import graph_page
app.add_api_route("/graph", graph_page, include_in_schema=False)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "features": [
            "multi-tenancy",
            "rbac",
            "graph-visualization",
            "rate-limiting",
            "caching",
            "langchain-agent",
            "eval-harness",
        ],
    }