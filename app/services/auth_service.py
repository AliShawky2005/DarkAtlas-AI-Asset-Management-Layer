"""
Auth service — Bonus 2: RBAC.

Handles API key generation, hashing, and verification.

Design decisions:
- Raw keys are never stored. We generate a random key, show it once,
  then only store the bcrypt hash. This mirrors how GitHub/Stripe handle tokens.
- Keys follow the format: "dka_<random_hex>" so they're recognizable
  in logs and easy to search/revoke.
- bcrypt is slow by design (cost factor = 12) — this is fine since
  auth checks happen once per request and results can be cached.
"""

import secrets
import uuid

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey, Role
from app.models.organization import Organization

# bcrypt context — cost=12 is the recommended minimum for security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _generate_raw_key() -> str:
    """
    Generate a cryptographically random API key.
    Format: dka_<64 hex chars>
    Example: dka_a3f7e21b9d0c...
    """
    return f"dka_{secrets.token_hex(32)}"


def hash_key(raw_key: str) -> str:
    """Hash a raw API key with bcrypt. Store this in the DB."""
    return pwd_context.hash(raw_key)


def verify_key(raw_key: str, hashed: str) -> bool:
    """Check a raw key against its stored bcrypt hash."""
    return pwd_context.verify(raw_key, hashed)


async def create_api_key(
    db: AsyncSession,
    org_id: str,
    role: Role,
    label: str,
) -> tuple[ApiKey, str]:
    """
    Create a new API key for an organization.

    Returns (ApiKey ORM object, raw_key_string).
    The raw key is returned ONCE — it cannot be retrieved again.
    """
    raw_key = _generate_raw_key()
    hashed = hash_key(raw_key)

    key = ApiKey(
        label=label,
        key_hash=hashed,
        role=role,
        organization_id=org_id,
        is_active=True,
    )
    db.add(key)
    await db.flush()
    return key, raw_key


async def verify_api_key(
    db: AsyncSession,
    raw_key: str,
) -> ApiKey | None:
    """
    Look up and verify a raw API key.

    Returns the ApiKey row if valid and active, None otherwise.

    Note: We can't use a simple DB lookup because keys are hashed.
    We fetch all active keys for efficiency (there won't be millions)
    and verify each hash. In production with millions of keys you'd
    add a prefix index on the first N chars of the hash.
    """
    if not raw_key or not raw_key.startswith("dka_"):
        return None

    # Load all active keys and verify hashes
    stmt = select(ApiKey).where(ApiKey.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    keys = result.scalars().all()

    for key in keys:
        if verify_key(raw_key, key.key_hash):
            return key

    return None


async def get_keys_for_org(
    db: AsyncSession,
    org_id: str,
) -> list[ApiKey]:
    """List all API keys for an organization."""
    stmt = select(ApiKey).where(ApiKey.organization_id == org_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def revoke_key(
    db: AsyncSession,
    key_id: uuid.UUID,
    org_id: str,
) -> ApiKey | None:
    """Deactivate an API key. Returns the key if found, None if not."""
    stmt = select(ApiKey).where(
        ApiKey.id == key_id,
        ApiKey.organization_id == org_id,
    )
    result = await db.execute(stmt)
    key = result.scalar_one_or_none()
    if key:
        key.is_active = False
        await db.flush()
    return key


async def ensure_default_org(db: AsyncSession) -> None:
    """
    Ensure the 'default' organization exists.
    Called at startup so the system works out-of-the-box.
    """
    stmt = select(Organization).where(Organization.id == "default")
    result = await db.execute(stmt)
    if not result.scalar_one_or_none():
        db.add(Organization(id="default", name="Default Organization"))
        await db.flush()
