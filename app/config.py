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

    # ── Security ──────────────────────────────────────────────────────────────
    API_KEY: str = "dev-api-key-change-in-production"

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

    # ── App ───────────────────────────────────────────────────────────────────
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False


settings = Settings()