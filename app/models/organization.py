"""
Organization model — Bonus 1: Multi-tenancy.

Each organization is a tenant. All assets are scoped to one org.
The "default" org is always present and is used when no X-Org-Id header is sent.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Organization(Base):
    """
    One row = one tenant / customer organization.

    The id is a human-readable slug (e.g., "acme-corp", "default").
    We use a slug instead of a UUID so it can be passed as a header value
    without looking up a UUID first.
    """
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(String(256), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Organization {self.id!r} ({self.name!r})>"
