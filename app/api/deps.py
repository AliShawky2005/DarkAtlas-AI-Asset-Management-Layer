"""
FastAPI dependencies — reusable building blocks injected into route handlers.

Usage in a route:
    from app.api.deps import get_db, require_api_key

    @router.post("/assets", dependencies=[Depends(require_api_key)])
    async def create_asset(db: AsyncSession = Depends(get_db)):
        ...
"""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

# ── API Key authentication ────────────────────────────────────────────────────
#
# APIKeyHeader tells FastAPI to look for a header named "X-API-Key".
# `auto_error=False` means FastAPI won't auto-reject requests missing the header
# — we handle that check ourselves in `require_api_key` below so we can return
# a more informative error message.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    api_key: str | None = Security(api_key_header),
) -> str:
    """
    Dependency that enforces API key authentication.

    Attach to any write route:
        @router.post("/...", dependencies=[Depends(require_api_key)])

    Or inject the key if you need it in the handler body:
        async def handler(_: str = Depends(require_api_key)):
    """
    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "unauthorized",
                "message": "A valid X-API-Key header is required for write operations.",
            },
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


# Re-export so route files have a single import source:
#   from app.api.deps import get_db, require_api_key, AsyncSession, Depends
__all__ = ["get_db", "require_api_key", "AsyncSession", "Depends"]
