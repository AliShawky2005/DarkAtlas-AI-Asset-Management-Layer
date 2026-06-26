"""
Base LangChain infrastructure — shared by all four analysis features.

Every analysis service imports from here:
  - get_llm()               → the configured LLM instance
  - SYSTEM_PROMPT           → shared cybersecurity analyst persona
  - format_assets_for_prompt() → converts DB assets into clean prompt text
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.config import settings


# ── LLM factory ───────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """
    Creates and returns the configured LLM instance.

    @lru_cache(maxsize=1) means this function runs ONCE — on first call.
    Every subsequent call returns the same cached object.
    This is important because creating an LLM client opens a connection
    and loads configuration — we don't want to do that on every request.

    temperature=0 everywhere because:
      - We need consistent, deterministic analysis
      - Security decisions should not vary randomly
      - Structured JSON output is more reliable at temp=0
    """
    provider = settings.LLM_PROVIDER.lower()

    if provider == "groq":
        from langchain_groq import ChatGroq
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set in your .env file.")
        return ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=settings.LLM_MODEL,
            temperature=0,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in your .env file.")
        return ChatAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL,
            temperature=0,
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in your .env file.")
        return ChatOpenAI(
            api_key=settings.OPENAI_API_KEY,
            model=settings.LLM_MODEL,
            temperature=0,
        )

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}'. "
            "Valid options: 'groq', 'anthropic', 'openai'."
        )


# ── Shared system prompt ──────────────────────────────────────────────────────

DARKATLAS_SYSTEM_PROMPT = """You are an expert cybersecurity analyst working with DarkAtlas, \
an Attack Surface Management (ASM) platform built by Buguard.

You analyze internet-facing assets: domains, subdomains, IP addresses, services, \
TLS certificates, and technologies.

CRITICAL RULES — you must follow these at all times:
1. Only reference assets explicitly provided in the context. Never invent domains, \
IPs, certificates, or vulnerabilities.
2. Base every finding on specific data fields (value, metadata, tags, status).
3. If the data is insufficient to make a conclusion, say so clearly.
4. Be precise and concise — security analysts need facts, not filler."""


# ── Prompt utilities ──────────────────────────────────────────────────────────

def format_assets_for_prompt(assets: list[dict]) -> str:
    """
    Converts a list of asset dictionaries into clean, readable text
    suitable for injection into an LLM prompt.

    Why not just dump raw JSON? Because:
    - JSON is noisy (lots of brackets and quotes the LLM has to parse)
    - This structured format is faster for the LLM to process
    - It's easier to verify what the LLM is actually seeing

    Input:
      [{"type": "certificate", "value": "cert-abc", "metadata": {"expires_at": "2024-01-01"}}]

    Output:
      ASSET 1: type=certificate | value=cert-abc | status=unknown |
               tags=none | metadata={expires_at=2024-01-01}
    """
    if not assets:
        return "No assets found matching the query."

    lines = []
    for i, asset in enumerate(assets, 1):
        metadata = asset.get("metadata", {})
        meta_str = (
            ", ".join(f"{k}={v}" for k, v in metadata.items())
            if metadata else "none"
        )
        tags = asset.get("tags", [])
        tags_str = ", ".join(tags) if tags else "none"

        lines.append(
            f"ASSET {i}: type={asset.get('type', '?')} | "
            f"value={asset.get('value', '?')} | "
            f"status={asset.get('status', 'unknown')} | "
            f"tags=[{tags_str}] | "
            f"metadata={{{meta_str}}}"
        )

    return "\n".join(lines)


# ── LLM connection test ───────────────────────────────────────────────────────

async def test_llm_connection() -> dict:
    """
    Sends a minimal message to the LLM to verify the connection works.
    Called by GET /api/v1/analyze/health.

    Uses .ainvoke() — the async version of .invoke().
    All LangChain chain calls in this project use async (.ainvoke)
    so we don't block the FastAPI event loop while waiting for the LLM.
    """
    llm = get_llm()

    # Simple chain: prompt → LLM → extract text string
    # StrOutputParser() just pulls the text content out of the LLM response object
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant. Respond in exactly one sentence."),
        ("human", "Confirm that the DarkAtlas AI analysis layer is operational."),
    ])
    chain = prompt | llm | StrOutputParser()

    response = await chain.ainvoke({})

    return {
        "provider": settings.LLM_PROVIDER,
        "model": settings.LLM_MODEL,
        "response": response,
    }