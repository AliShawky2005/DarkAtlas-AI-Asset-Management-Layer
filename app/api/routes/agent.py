"""
Agent route — Bonus 5: LangChain ReAct agent chat endpoint.

POST /api/v1/agent/chat — send a free-text question, get a reasoned answer
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_org_id, require_reader
from app.middleware.rate_limit import limiter
from app.models.api_key import ApiKey
from app.services.analysis.agent import run_agent, AgentResponse

router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        examples=[
            "What are my riskiest assets?",
            "Give me a full security report for production assets",
            "Find all expired certificates and tell me what to do",
            "Enrich asset <uuid> and explain what environment it's in",
        ],
    )


@router.post(
    "/chat",
    response_model=AgentResponse,
    summary="Chat with the DarkAtlas AI agent",
    description=(
        "Send a free-text question to the DarkAtlas ReAct agent.\n\n"
        "The agent will reason through your question, call the appropriate "
        "API tools (list assets, run risk analysis, generate reports, etc.), "
        "and return a synthesized answer.\n\n"
        "**Examples:**\n"
        "- `What are my riskiest assets?`\n"
        "- `Show me all expired certificates on production subdomains`\n"
        "- `Generate a security report and highlight the top 3 issues`\n"
        "- `What technologies are we running and are any end-of-life?`\n\n"
        "**Rate limit:** 5 requests/minute (agent makes multiple API calls per request). "
        "Requires reader key."
    ),
)
@limiter.limit("5/minute")
async def agent_chat(
    request: Request,
    body: AgentChatRequest,
    org_id: str = Depends(get_org_id),
    _key: ApiKey = Depends(require_reader),
) -> AgentResponse:
    try:
        return await run_agent(body.message, org_id=org_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {e}",
        )
