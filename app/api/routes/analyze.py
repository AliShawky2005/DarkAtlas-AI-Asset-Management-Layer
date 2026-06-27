"""
Analysis routes — AI-powered endpoints.

Bonus 1: All analysis scoped to org (X-Org-Id)
Bonus 2: require_reader on all read endpoints
Bonus 4: Rate limiting on LLM endpoints (10/minute)

GET  /health          — LLM connection test
POST /query           — natural-language query
GET  /risk            — risk scoring & summary
POST /enrich/{id}     — asset enrichment
GET  /report          — report generation
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_org_id, require_reader, require_admin
from app.middleware.rate_limit import limiter
from app.models.api_key import ApiKey
from app.services.analysis.base import test_llm_connection
from app.services.analysis.enrichment import enrich_asset
from app.services.analysis.nl_query import natural_language_query
from app.services.analysis.risk import RiskSummaryResponse, analyze_risk
from app.services.analysis.report import ReportResponse, generate_report

router = APIRouter()


# ── LLM health check ──────────────────────────────────────────────────────────

@router.get("/health", summary="Test LLM connection")
async def analyze_health():
    try:
        result = await test_llm_connection()
        return {"status": "ok", **result}
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Configuration error: {e}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM provider unreachable: {e}")


# ── Natural-language asset query ──────────────────────────────────────────────

class NLQueryRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        examples=["show me all expired certificates", "find production subdomains"],
    )


@router.post(
    "/query",
    summary="Natural-language asset query",
    description=(
        "Ask a question in plain English and get matching assets from the database.\n\n"
        "**Examples:** `show me all expired certificates` · "
        "`find production subdomains with api in the name` · "
        "`list all active ip addresses`\n\n"
        "**Rate limit:** 10 requests/minute. Requires reader key."
    ),
)
@limiter.limit("10/minute")
async def nl_query(
    request: Request,   # required by slowapi
    body: NLQueryRequest,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
):
    try:
        return await natural_language_query(db, body.query, organization_id=org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


# ── Risk scoring ──────────────────────────────────────────────────────────────

@router.get(
    "/risk",
    response_model=RiskSummaryResponse,
    summary="Risk scoring & executive summary",
    description=(
        "Analyzes assets using security rules, then generates an AI executive summary.\n\n"
        "**Rules:** expired certs → HIGH · Telnet/RDP exposed → CRITICAL · "
        "SSH public → HIGH · EOL technology → MEDIUM · stale assets → MEDIUM\n\n"
        "Use `tag=production` to scope analysis to production assets only.\n\n"
        "**Rate limit:** 10/min. Results cached 5 minutes. Requires reader key."
    ),
)
@limiter.limit("10/minute")
async def risk_analysis(
    request: Request,
    tag: Optional[str] = Query(None, description="Scope to assets with this tag"),
    asset_type: Optional[str] = Query(None, description="Scope to a specific asset type"),
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
) -> RiskSummaryResponse:
    try:
        return await analyze_risk(db, tag=tag, asset_type_filter=asset_type, organization_id=org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk analysis failed: {e}")


# ── Asset enrichment ──────────────────────────────────────────────────────────

@router.post(
    "/enrich/{asset_id}",
    summary="Enrich & classify an asset",
    description=(
        "Uses the LLM to classify an asset by environment, criticality, and category, "
        "then saves the enrichment back to the database.\n\n"
        "**Requires admin key** (writes to DB)."
    ),
)
@limiter.limit("10/minute")
async def enrich_asset_endpoint(
    request: Request,
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_admin),
):
    try:
        return await enrich_asset(db, asset_id, organization_id=org_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}")


# ── Report generation ─────────────────────────────────────────────────────────

@router.get(
    "/report",
    response_model=ReportResponse,
    summary="Generate full security report",
    description=(
        "Generates a complete written attack surface management report.\n\n"
        "**Sections:** Executive Summary · Asset Inventory · "
        "Risk Analysis · Recommendations · Conclusion\n\n"
        "**Rate limit:** 10/min. Results cached 5 minutes. Requires reader key."
    ),
)
@limiter.limit("10/minute")
async def generate_report_endpoint(
    request: Request,
    tag: Optional[str] = Query(None, description="Scope report to assets with this tag"),
    asset_type: Optional[str] = Query(None, description="Scope report to a specific asset type"),
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
) -> ReportResponse:
    try:
        return await generate_report(db, tag=tag, asset_type_filter=asset_type, organization_id=org_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")