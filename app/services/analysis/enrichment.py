"""
Phase 6 — Automated Enrichment & Classification

Chain:
  1. Fetch asset from DB by ID
  2. LLM classifies the asset (environment, criticality, category)
  3. We validate the LLM output against allowed values
  4. We write the enrichment back to the DB (tags + metadata)
  5. Return the enriched asset

This is the only analysis feature that writes back to the database.
The LLM provides classification decisions; we apply them safely.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.schemas.asset import AssetResponse
from app.services.analysis.base import DARKATLAS_SYSTEM_PROMPT, get_llm


# ── Allowed classification values ─────────────────────────────────────────────
# We restrict LLM output to these known values.
# Any value outside these sets is rejected and replaced with "unknown".

VALID_ENVIRONMENTS = {"production", "staging", "development", "internal", "unknown"}
VALID_CRITICALITIES = {"critical", "high", "medium", "low"}
VALID_CATEGORIES = {
    "web",             # web-facing services, domains, subdomains
    "infrastructure",  # IP addresses, servers, network assets
    "security",        # certificates, auth services
    "data",            # databases, storage, data pipelines
    "internal",        # internal-only, not externally reachable
    "unknown",
}


# ── Structured output schema ──────────────────────────────────────────────────

class AssetClassification(BaseModel):
    """The structured output the LLM must return for each asset."""

    environment: str = Field(
        ...,
        description=(
            "The deployment environment of this asset. "
            "Must be one of: production, staging, development, internal, unknown."
        ),
    )
    criticality: str = Field(
        ...,
        description=(
            "Business criticality of this asset. "
            "Must be one of: critical, high, medium, low. "
            "Consider: is it customer-facing? Does it handle sensitive data? "
            "Is it a core infrastructure component?"
        ),
    )
    category: str = Field(
        ...,
        description=(
            "Functional category of this asset. "
            "Must be one of: web, infrastructure, security, data, internal, unknown."
        ),
    )
    suggested_tags: list[str] = Field(
        default_factory=list,
        description=(
            "Additional descriptive tags to add to this asset, maximum 5. "
            "Examples: api-endpoint, external-facing, load-balancer, cdn, database. "
            "Only suggest tags that are clearly supported by the asset data."
        ),
    )
    reasoning: str = Field(
        ...,
        description=(
            "One concise sentence explaining the classification decisions, "
            "citing specific asset attributes as evidence."
        ),
    )


# ── Prompt ────────────────────────────────────────────────────────────────────

ENRICHMENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", DARKATLAS_SYSTEM_PROMPT),
    ("human", """Classify the following asset for an Attack Surface Management inventory.

ASSET DETAILS:
  Type:       {asset_type}
  Value:      {asset_value}
  Status:     {asset_status}
  Current tags: {asset_tags}
  Metadata:   {asset_metadata}

Classify this asset by:
1. environment — where is it deployed? (production/staging/development/internal/unknown)
2. criticality — how critical is it to the business? (critical/high/medium/low)
3. category    — what function does it serve? (web/infrastructure/security/data/internal/unknown)
4. suggested_tags — up to 5 additional descriptive tags (only if clearly supported by the data)
5. reasoning   — one sentence citing specific evidence from the asset data

CLASSIFICATION GUIDELINES:
- If the asset value contains "prod" or "www" or current tags include "production" → environment=production
- If the asset value contains "staging", "stage", "dev", "test" → environment=staging or development
- If type=certificate → category=security
- If type=ip_address or type=service → category=infrastructure
- If type=domain or type=subdomain → category=web
- If type=technology → category depends on the technology name/version
- Criticality: customer-facing assets = high or critical. Internal tools = medium. Dev/test = low.
- Only suggest tags clearly supported by the data — never invent information.
"""),
])


# ── DB operations ─────────────────────────────────────────────────────────────

async def _get_asset(db: AsyncSession, asset_id: str) -> Optional[Asset]:
    """Fetch an asset by UUID string."""
    try:
        uid = uuid.UUID(str(asset_id))
    except ValueError:
        return None
    result = await db.execute(select(Asset).where(Asset.id == uid))
    return result.scalar_one_or_none()


async def _apply_enrichment(
    db: AsyncSession,
    asset: Asset,
    classification: AssetClassification,
) -> Asset:
    """
    Write the LLM classification back to the asset in the database.

    What we update:
      tags         — add environment, criticality, category, and suggested tags
                     (never remove existing tags — additive only)
      asset_metadata — add enrichment details with timestamp
    """
    now = datetime.now(timezone.utc)

    # Build the new tags to add (lowercase, stripped)
    new_tags = {
        classification.environment,
        f"{classification.criticality}-criticality",
        classification.category,
    }
    # Add suggested tags (sanitized)
    for tag in classification.suggested_tags[:5]:
        cleaned = tag.strip().lower().replace(" ", "-")
        if cleaned:
            new_tags.add(cleaned)

    # Remove "unknown" — don't tag assets with "unknown"
    new_tags.discard("unknown")

    # Merge with existing tags (additive — we never remove existing tags)
    existing_tags = set(asset.tags or [])
    asset.tags = sorted(existing_tags | new_tags)

    # Update metadata with enrichment results
    existing_meta = dict(asset.asset_metadata or {})
    existing_meta["enrichment"] = {
        "environment": classification.environment,
        "criticality": classification.criticality,
        "category": classification.category,
        "reasoning": classification.reasoning,
        "enriched_at": now.isoformat(),
        "suggested_tags": classification.suggested_tags,
    }
    asset.asset_metadata = existing_meta
    asset.last_seen = now

    await db.flush()
    return asset


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_classification(raw: AssetClassification) -> AssetClassification:
    """
    Validate LLM output against our allowed value sets.
    Replace any invalid value with "unknown" or "medium".
    This prevents the LLM from writing garbage into the database.
    """
    environment = raw.environment.strip().lower()
    if environment not in VALID_ENVIRONMENTS:
        environment = "unknown"

    criticality = raw.criticality.strip().lower()
    if criticality not in VALID_CRITICALITIES:
        criticality = "medium"  # safe default

    category = raw.category.strip().lower()
    if category not in VALID_CATEGORIES:
        category = "unknown"

    return AssetClassification(
        environment=environment,
        criticality=criticality,
        category=category,
        suggested_tags=raw.suggested_tags,
        reasoning=raw.reasoning,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

async def enrich_asset(db: AsyncSession, asset_id: str, organization_id: str = "default") -> dict:
    """
    Classify an asset using the LLM and save the enrichment to the DB.

    Returns:
      - asset_id, asset_value, asset_type
      - classification: what the LLM decided
      - asset: the full updated asset
    """
    # Step 1: Fetch the real asset (scoped to org)
    asset = await _get_asset(db, asset_id)
    if not asset or asset.organization_id != organization_id:
        raise ValueError(f"Asset '{asset_id}' not found.")

    # Step 2: Build prompt context from real asset data
    llm = get_llm()
    structured_llm = llm.with_structured_output(AssetClassification)
    chain = ENRICHMENT_PROMPT | structured_llm

    raw_classification: AssetClassification = await chain.ainvoke({
        "asset_type": asset.type.value,
        "asset_value": asset.value,
        "asset_status": asset.status.value,
        "asset_tags": ", ".join(asset.tags or []) or "none",
        "asset_metadata": str(asset.asset_metadata or {}) or "none",
    })

    # Step 3: Validate — reject any values outside our allowed sets
    classification = _validate_classification(raw_classification)

    # Step 4: Write enrichment back to DB
    updated_asset = await _apply_enrichment(db, asset, classification)

    return {
        "asset_id": str(updated_asset.id),
        "asset_value": updated_asset.value,
        "asset_type": updated_asset.type.value,
        "classification": {
            "environment": classification.environment,
            "criticality": classification.criticality,
            "category": classification.category,
            "reasoning": classification.reasoning,
            "suggested_tags": classification.suggested_tags,
        },
        "asset": AssetResponse.from_orm(updated_asset).model_dump(),
    }