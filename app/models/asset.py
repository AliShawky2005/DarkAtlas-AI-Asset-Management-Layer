"""
ORM models for the two core tables:
  - assets             — every internet-facing resource being tracked
  - asset_relationships — directed edges between assets (the graph layer)
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ── Enum definitions ──────────────────────────────────────────────────────────
#
# `str, PyEnum` means these enums are also strings.
# So AssetType.DOMAIN == "domain" is True.
# This matters for JSON serialization and Pydantic validation.

class AssetType(str, PyEnum):
    """The six types of assets DarkAtlas tracks."""
    DOMAIN      = "domain"
    SUBDOMAIN   = "subdomain"
    IP_ADDRESS  = "ip_address"
    SERVICE     = "service"       # e.g. 443/tcp
    CERTIFICATE = "certificate"
    TECHNOLOGY  = "technology"    # e.g. nginx/1.24.0


class AssetStatus(str, PyEnum):
    """Lifecycle state of an asset."""
    ACTIVE   = "active"    # currently observed
    STALE    = "stale"     # not seen recently
    ARCHIVED = "archived"  # intentionally removed from tracking


class AssetSource(str, PyEnum):
    """How the asset entered the system."""
    IMPORT = "import"
    SCAN   = "scan"
    MANUAL = "manual"


# ── Asset model ───────────────────────────────────────────────────────────────

class Asset(Base):
    """
    One row = one internet-facing resource.

    Natural key: (type, value) must be unique.
    This is the foundation of deduplication in Phase 2.
    """
    __tablename__ = "assets"

    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_asset_type_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, name="asset_type"),
        nullable=False,
    )

    value: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        index=True,
    )

    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"),
        nullable=False,
        default=AssetStatus.ACTIVE,
    )

    # first_seen: set once on creation, never updated.
    # last_seen:  updated every time the asset is re-imported or re-scanned.
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    source: Mapped[AssetSource] = mapped_column(
        Enum(AssetSource, name="asset_source"),
        nullable=False,
        default=AssetSource.IMPORT,
    )

    # tags: free-form labels e.g. ["production", "critical"]
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # asset_metadata: type-specific JSON blob.
    # Named asset_metadata (not metadata) because SQLAlchemy's Base already
    # has a .metadata attribute — naming it the same would cause a conflict.
    # We map this to "metadata" in the API schemas.
    #
    # Examples:
    #   certificate -> {"issuer": "Let's Encrypt", "expires_at": "2025-09-01"}
    #   service     -> {"port": 443, "protocol": "tcp", "banner": "nginx/1.24"}
    #   technology  -> {"name": "nginx", "version": "1.24.0"}
    asset_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # ORM-level relationships (no extra DB columns — these are Python helpers)
    outgoing: Mapped[list["AssetRelationship"]] = relationship(
        "AssetRelationship",
        foreign_keys="AssetRelationship.source_id",
        back_populates="source_asset",
        cascade="all, delete-orphan",
    )
    incoming: Mapped[list["AssetRelationship"]] = relationship(
        "AssetRelationship",
        foreign_keys="AssetRelationship.target_id",
        back_populates="target_asset",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Asset {self.type}:{self.value} [{self.status}]>"


# ── AssetRelationship model ───────────────────────────────────────────────────

class AssetRelationship(Base):
    """
    A directed edge between two assets.

    Common relationship_type values:
      subdomain_of  — api.example.com -> example.com
      resolves_to   — api.example.com -> 203.0.113.10
      runs_on       — 443/tcp         -> 203.0.113.10
      secured_by    — api.example.com -> certificate
      uses          — api.example.com -> nginx
    """
    __tablename__ = "asset_relationships"

    __table_args__ = (
        UniqueConstraint(
            "source_id", "target_id", "relationship_type",
            name="uq_relationship",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    source_asset: Mapped["Asset"] = relationship(
        "Asset", foreign_keys=[source_id], back_populates="outgoing"
    )
    target_asset: Mapped["Asset"] = relationship(
        "Asset", foreign_keys=[target_id], back_populates="incoming"
    )

    def __repr__(self) -> str:
        return f"<Relationship {self.source_id} --[{self.relationship_type}]--> {self.target_id}>"