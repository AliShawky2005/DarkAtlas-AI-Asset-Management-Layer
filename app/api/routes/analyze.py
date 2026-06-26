"""
Analysis routes — AI-powered endpoints.

Phase 3: GET  /health          — LLM connection test         ✅
Phase 4: POST /query           — natural-language query       ✅
Phase 5: GET  /risk            — risk scoring & summary       ✅
Phase 6: POST /enrich/{id}     — asset enrichment             ✅
Phase 7: GET  /report          — report generation            ✅
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.analysis.base import test_llm_connection
from app.services.analysis.enrichment import enrich_asset
from app.services.analysis.nl_query import natural_language_query
from app.services.analysis.risk import RiskSummaryResponse, analyze_risk
from app.services.analysis.report import ReportResponse, generate_report

router = APIRouter()


# ── Phase 3: LLM health check ─────────────────────────────────────────────────

@router.get("/health", summary="Test LLM connection")
async def analyze_health():
    try:
        result = await test_llm_connection()
        return {"status": "ok", **result}
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Configuration error: {e}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM provider unreachable: {e}")


# ── Phase 4: Natural-language asset query ─────────────────────────────────────

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
        "`list all active ip addresses`"
    ),
)
async def nl_query(
    request: NLQueryRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await natural_language_query(db, request.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


# ── Phase 5: Risk scoring ─────────────────────────────────────────────────────

@router.get(
    "/risk",
    response_model=RiskSummaryResponse,
    summary="Risk scoring & executive summary",
    description=(
        "Analyzes assets using security rules, then generates an AI executive summary.\n\n"
        "**Rules:** expired certs → HIGH · Telnet/RDP exposed → CRITICAL · "
        "SSH public → HIGH · EOL technology → MEDIUM · stale assets → MEDIUM\n\n"
        "Use `tag=production` to scope analysis to production assets only."
    ),
)
async def risk_analysis(
    tag: Optional[str] = Query(None, description="Scope to assets with this tag"),
    asset_type: Optional[str] = Query(None, description="Scope to a specific asset type"),
    db: AsyncSession = Depends(get_db),
) -> RiskSummaryResponse:
    try:
        return await analyze_risk(db, tag=tag, asset_type_filter=asset_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk analysis failed: {e}")


# ── Phase 6: Asset enrichment ─────────────────────────────────────────────────

@router.post(
    "/enrich/{asset_id}",
    summary="Enrich & classify an asset",
    description=(
        "Uses the LLM to classify an asset by environment, criticality, and category, "
        "then saves the enrichment back to the database.\n\n"
        "**Classifications:**\n"
        "- `environment`: production · staging · development · internal · unknown\n"
        "- `criticality`: critical · high · medium · low\n"
        "- `category`: web · infrastructure · security · data · internal · unknown"
    ),
)
async def enrich_asset_endpoint(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await enrich_asset(db, asset_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}")


# ── Phase 7: Report generation ────────────────────────────────────────────────

@router.get(
    "/report",
    response_model=ReportResponse,
    summary="Generate full security report",
    description=(
        "Generates a complete written attack surface management report.\n\n"
        "**Sections:** Executive Summary · Asset Inventory · "
        "Risk Analysis · Recommendations · Conclusion\n\n"
        "Use `tag=production` to generate a production-only report."
    ),
)
async def generate_report_endpoint(
    tag: Optional[str] = Query(None, description="Scope report to assets with this tag"),
    asset_type: Optional[str] = Query(None, description="Scope report to a specific asset type"),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    try:
        return await generate_report(db, tag=tag, asset_type_filter=asset_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")