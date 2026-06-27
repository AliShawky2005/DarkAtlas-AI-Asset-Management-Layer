from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Single source of truth for all app configuration.
    Reads from environment variables and .env file automatically.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://darkatlas:darkatlas@localhost:5432/darkatlas"
    )

    # ── Security (Bonus 2 — RBAC) ─────────────────────────────────────────────
    # Legacy single key kept for backwards-compat; superseded by ApiKey table
    API_KEY: str = "dev-api-key-change-in-production"
    # Default org used when no X-Org-Id header is provided
    DEFAULT_ORG_ID: str = "default"

    # ── LLM provider ─────────────────────────────────────────────────────────
    # Supported: "groq" | "anthropic" | "openai"
    LLM_PROVIDER: str = "groq"

    # API keys — only fill in the one you're using
    GROQ_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Model names:
    #   groq      → llama-3.3-70b-versatile  (free)
    #   anthropic → claude-3-5-sonnet-20241022
    #   openai    → gpt-4o
    LLM_MODEL: str = "llama-3.3-70b-versatile"

    # ── Rate limiting (Bonus 4) ───────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: str = "60/minute"     # global limit per IP
    RATE_LIMIT_LLM: str = "10/minute"         # stricter limit for LLM endpoints

    # ── App ───────────────────────────────────────────────────────────────────
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False


settings = Settings()