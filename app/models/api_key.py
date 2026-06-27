"""
ApiKey model — Bonus 2: RBAC.

Instead of a single global API key from .env, we store hashed keys in the DB.
Each key has a role (admin or reader) and belongs to one organization.

- admin  → full access (create, import, enrich, analyze, manage keys)
- reader → read-only (GET assets, GET analysis results)
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Role(str, PyEnum):
    """Access role attached to an API key."""
    ADMIN  = "admin"   # full read + write access
    READER = "reader"  # read-only access


class ApiKey(Base):
    """
    One row = one API key credential.

    The raw key is shown ONCE on creation and never stored.
    We store only the bcrypt hash for verification.
    """
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Human-readable label so admins can identify which key is which
    label: Mapped[str] = mapped_column(String(128), nullable=False)

    # bcrypt hash of the raw key — never store the raw value
    key_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    role: Mapped[Role] = mapped_column(
        Enum(Role, name="api_key_role"),
        nullable=False,
        default=Role.READER,
    )

    # Which organization this key grants access to
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        default="default",
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<ApiKey {self.label!r} role={self.role} org={self.organization_id}>"
