"""
LangChain Agent — Bonus 5: AI agent that calls your own API as tools.

Uses LangGraph's ReAct agent pattern.
The agent has 5 tools — each one calls a real API endpoint.
The agent decides which tools to call based on the user's question,
reasons through results, and synthesizes a final answer.

This demonstrates the full agentic loop:
  User question → Agent plans → Tool calls → Observe results → Final answer
"""

import json
from typing import Any

import httpx
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from app.services.analysis.base import get_llm, DARKATLAS_SYSTEM_PROMPT
from app.config import settings


# ── Response schema ───────────────────────────────────────────────────────────

class AgentResponse(BaseModel):
    response: str
    tools_used: list[str]
    steps_taken: int


# ── Base HTTP caller ──────────────────────────────────────────────────────────

def _make_api_url(path: str) -> str:
    """Build a URL pointing to our own API (running on same host)."""
    return f"http://localhost:8001{path}"


def _get_headers(org_id: str = "default") -> dict:
    """Headers for internal API calls — uses the env API key."""
    return {
        "X-API-Key": settings.API_KEY,
        "X-Org-Id": org_id,
        "Content-Type": "application/json",
    }


# ── LangChain Tools (each calls a real API endpoint) ─────────────────────────

def make_tools(org_id: str = "default"):
    """
    Create the tool set for the agent, scoped to an organization.
    Tools are created fresh per request so org_id is captured in closure.
    """

    @tool
    def list_assets_tool(
        asset_type: str = "",
        status: str = "",
        tag: str = "",
        search: str = "",
    ) -> str:
        """
        List assets from the DarkAtlas database.
        Use to find specific assets, count assets by type, or explore the attack surface.
        Parameters:
          asset_type: Filter by type (domain, subdomain, ip_address, service, certificate, technology)
          status: Filter by status (active, stale, archived)
          tag: Filter by tag label (e.g. production, staging, critical)
          search: Search in asset value (partial match, e.g. "api", "443")
        """
        params: dict[str, Any] = {"page_size": 50}
        if asset_type:
            params["type"] = asset_type
        if status:
            params["status"] = status
        if tag:
            params["tag"] = tag
        if search:
            params["search"] = search

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    _make_api_url("/api/v1/assets"),
                    params=params,
                    headers=_get_headers(org_id),
                )
                resp.raise_for_status()
                data = resp.json()
                # Return a summary to keep token count low
                assets = data.get("assets", [])
                summary = f"Found {data.get('total', 0)} assets (showing {len(assets)}):\n"
                for a in assets[:20]:
                    summary += (
                        f"  - [{a['type']}] {a['value']} | status={a['status']} "
                        f"| tags={a.get('tags', [])} | metadata={a.get('metadata', {})}\n"
                    )
                return summary
        except Exception as e:
            return f"Error fetching assets: {e}"

    @tool
    def risk_analysis_tool(tag: str = "", asset_type: str = "") -> str:
        """
        Run a full risk analysis on the assets.
        Returns risk findings (expired certs, dangerous ports, stale assets)
        and an executive summary.
        Use when the user asks about risk, vulnerabilities, or security posture.
        Parameters:
          tag: Scope analysis to assets with this tag (e.g. production)
          asset_type: Scope to a specific asset type
        """
        params: dict[str, Any] = {}
        if tag:
            params["tag"] = tag
        if asset_type:
            params["asset_type"] = asset_type

        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    _make_api_url("/api/v1/analyze/risk"),
                    params=params,
                    headers=_get_headers(org_id),
                )
                resp.raise_for_status()
                data = resp.json()
                lines = [
                    f"Total analyzed: {data.get('total_assets_analyzed', 0)}",
                    f"Risk counts: {data.get('risk_counts', {})}",
                    "Findings:",
                ]
                for f in data.get("findings", [])[:15]:
                    lines.append(
                        f"  [{f['risk_level'].upper()}] {f['asset_type']} '{f['asset_value']}': {f['finding']}"
                    )
                lines.append(f"\nSummary: {data.get('summary', '')}")
                return "\n".join(lines)
        except Exception as e:
            return f"Error running risk analysis: {e}"

    @tool
    def enrich_asset_tool(asset_id: str) -> str:
        """
        Enrich a specific asset — classify its environment, criticality, and category.
        Use when the user wants to understand what an asset is or asks to classify it.
        Parameters:
          asset_id: The UUID of the asset to enrich
        """
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    _make_api_url(f"/api/v1/analyze/enrich/{asset_id}"),
                    headers=_get_headers(org_id),
                )
                resp.raise_for_status()
                return json.dumps(resp.json(), indent=2)
        except Exception as e:
            return f"Error enriching asset {asset_id}: {e}"

    @tool
    def generate_report_tool(tag: str = "", asset_type: str = "") -> str:
        """
        Generate a full written security report.
        Use when the user asks for a report, summary, or overview of security posture.
        Parameters:
          tag: Scope report to assets with this tag
          asset_type: Scope report to a specific asset type
        """
        params: dict[str, Any] = {}
        if tag:
            params["tag"] = tag
        if asset_type:
            params["asset_type"] = asset_type

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.get(
                    _make_api_url("/api/v1/analyze/report"),
                    params=params,
                    headers=_get_headers(org_id),
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("report", "Report generation returned empty content.")
        except Exception as e:
            return f"Error generating report: {e}"

    @tool
    def natural_language_query_tool(query: str) -> str:
        """
        Search assets using a natural language query.
        Use to find specific assets that match a description.
        Examples: "expired certificates", "production subdomains with api", "active ip addresses"
        Parameters:
          query: Natural language description of the assets to find
        """
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(
                    _make_api_url("/api/v1/analyze/query"),
                    json={"query": query},
                    headers=_get_headers(org_id),
                )
                resp.raise_for_status()
                data = resp.json()
                lines = [
                    f"Query: {data.get('query')}",
                    f"Interpretation: {data.get('explanation')}",
                    f"Total matches: {data.get('total', 0)}",
                    "Assets:",
                ]
                for a in data.get("assets", [])[:10]:
                    lines.append(f"  - [{a['type']}] {a['value']} (status={a['status']})")
                return "\n".join(lines)
        except Exception as e:
            return f"Error executing query: {e}"

    return [
        list_assets_tool,
        risk_analysis_tool,
        enrich_asset_tool,
        generate_report_tool,
        natural_language_query_tool,
    ]


# ── Agent system prompt ───────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = f"""{DARKATLAS_SYSTEM_PROMPT}

You have access to 5 tools that query the live DarkAtlas asset database:
1. list_assets_tool — browse and filter assets
2. risk_analysis_tool — get risk findings and executive summary
3. enrich_asset_tool — classify an asset by environment/criticality
4. generate_report_tool — produce a full written security report
5. natural_language_query_tool — search assets with plain English

AGENT RULES:
- Always call at least one tool before answering — never answer from memory
- Only report facts returned by the tools
- If a tool returns an error, say so and try an alternative approach
- Synthesize results from multiple tool calls into a clear, actionable answer
- If the user's question is ambiguous, pick the most security-relevant interpretation
"""


# ── Main agent runner ─────────────────────────────────────────────────────────

async def run_agent(message: str, org_id: str = "default") -> AgentResponse:
    """
    Run the ReAct agent with the user's message.

    The agent will:
    1. Plan which tools to call
    2. Execute tools (each calls a real API endpoint)
    3. Observe results
    4. Repeat until it has enough information
    5. Return a synthesized final answer
    """
    llm = get_llm()
    tools = make_tools(org_id)

    # Create the ReAct agent using LangGraph
    agent = create_react_agent(llm, tools)

    # Run the agent
    result = await agent.ainvoke({
        "messages": [
            ("system", AGENT_SYSTEM_PROMPT),
            ("human", message),
        ]
    })

    # Extract the final answer and tool usage from the result
    messages = result.get("messages", [])
    final_response = ""
    tools_used = []
    steps = 0

    for msg in messages:
        msg_type = getattr(msg, "type", "") or type(msg).__name__.lower()
        if "tool" in msg_type:
            tool_name = getattr(msg, "name", "unknown")
            if tool_name not in tools_used:
                tools_used.append(tool_name)
            steps += 1
        elif hasattr(msg, "content") and msg_type in ("ai", "assistant"):
            # Last AI message is the final answer
            content = msg.content
            if content and isinstance(content, str):
                final_response = content

    return AgentResponse(
        response=final_response or "The agent completed but returned no response.",
        tools_used=tools_used,
        steps_taken=steps,
    )
