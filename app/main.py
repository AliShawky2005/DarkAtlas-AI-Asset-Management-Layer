from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"[DarkAtlas] Tables synced. API v{settings.APP_VERSION} ready.")
    yield
    await engine.dispose()
    print("[DarkAtlas] Shutdown complete.")


app = FastAPI(
    title="DarkAtlas — AI Asset Management",
    description=(
        "Track B: LangChain-powered analysis layer for Buguard's "
        "DarkAtlas Attack Surface Management platform.\n\n"
        "**Auth:** Write endpoints require `X-API-Key` header.\n"
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.routes.assets import router as assets_router
from app.api.routes.analyze import router as analyze_router

app.include_router(assets_router, prefix="/api/v1/assets", tags=["Assets"])
app.include_router(analyze_router, prefix="/api/v1/analyze", tags=["Analysis"])


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}