"""
Evaluation harness routes — Bonus 6: LLM-as-judge quality scoring.

Endpoints:
  POST /api/v1/eval/nl-query  — run NL query + score quality
  POST /api/v1/eval/risk      — run risk analysis + score summary quality
  GET  /api/v1/eval/report    — run report generation + score quality
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_org_id, require_reader
from app.models.api_key import ApiKey
from app.services.analysis.eval import (
    evaluate_nl_query,
    evaluate_risk_summary,
    evaluate_report,
)
from app.services.analysis.nl_query import natural_language_query
from app.services.analysis.risk import analyze_risk
from app.services.analysis.report import generate_report

router = APIRouter()


class NLQueryEvalRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500,
                       examples=["show me expired certificates on production"])


@router.post(
    "/nl-query",
    summary="Evaluate NL query quality",
    description=(
        "Runs a natural-language query AND scores the output quality using an LLM judge.\n\n"
        "Returns both the actual query results and a quality evaluation "
        "(relevance score, grounding check, pass/fail).\n\n"
        "Requires reader key."
    ),
)
async def eval_nl_query(
    body: NLQueryEvalRequest,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
):
    try:
        # Run the actual query
        result = await natural_language_query(db, body.query, organization_id=org_id)
        # Score it with LLM judge
        evaluation = await evaluate_nl_query(body.query, result)
        return {
            "query": body.query,
            "result": result,
            "evaluation": evaluation,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")


@router.post(
    "/risk",
    summary="Evaluate risk analysis quality",
    description=(
        "Runs a risk analysis AND scores the LLM summary for factual grounding.\n\n"
        "The judge checks whether the summary only references findings "
        "from the rule engine — catching any hallucinations.\n\n"
        "Requires reader key."
    ),
)
async def eval_risk(
    tag: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
):
    try:
        result = await analyze_risk(db, tag=tag, asset_type_filter=asset_type, organization_id=org_id)
        evaluation = await evaluate_risk_summary(result.findings, result.summary)
        return {
            "risk_analysis": result,
            "evaluation": evaluation,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")


@router.get(
    "/report",
    summary="Evaluate report quality",
    description=(
        "Generates a security report AND scores it for completeness and grounding.\n\n"
        "Requires reader key."
    ),
)
async def eval_report(
    tag: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
):
    try:
        result = await generate_report(db, tag=tag, asset_type_filter=asset_type, organization_id=org_id)
        evaluation = await evaluate_report(result)
        return {
            "report": result,
            "evaluation": evaluation,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")
