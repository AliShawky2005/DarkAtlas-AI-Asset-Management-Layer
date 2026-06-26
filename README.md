# DarkAtlas — AI Asset Management Layer

> **Buguard AI Internship Assessment — Track B: AI Applications**

A LangChain-powered analysis layer for Buguard's DarkAtlas Attack Surface Management platform. This system ingests internet-facing assets, deduplicates them, and exposes four AI-driven analysis features: natural-language querying, risk scoring, automated enrichment, and report generation.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [AI Features — Example Prompts & Outputs](#ai-features--example-prompts--outputs)
- [Design Decisions](#design-decisions)
- [Running Tests](#running-tests)
- [Environment Variables](#environment-variables)

---

## Quick Start

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running)
- A [Groq API key](https://console.groq.com) (free, no credit card required)

### 1. Clone and configure

```bash
git clone <your-repo-url>
cd darkatlas-ai
copy .env.example .env        # Windows
# cp .env.example .env        # Mac/Linux
```

Open `.env` and fill in your Groq API key:

```env
GROQ_API_KEY=gsk_your_key_here
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
```

### 2. Start the system

```bash
docker-compose up --build
```

First run takes 3–5 minutes (downloads PostgreSQL + Python packages).
Wait for:
```
[DarkAtlas] Tables synced. API v1.0.0 ready.
```

### 3. Verify it works

```bash
curl http://localhost:8001/health
# → {"status":"ok","version":"1.0.0"}

curl http://localhost:8001/api/v1/analyze/health
# → {"status":"ok","provider":"groq","model":"llama-3.3-70b-versatile","response":"..."}
```

### 4. Import sample data

```bash
curl -X POST http://localhost:8001/api/v1/assets/import \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key-change-in-production" \
  -d '{
    "assets": [
      {
        "type": "domain",
        "value": "example.com",
        "status": "active",
        "tags": ["production"],
        "metadata": {}
      },
      {
        "type": "subdomain",
        "value": "api.example.com",
        "status": "active",
        "tags": ["production"],
        "metadata": {}
      },
      {
        "type": "certificate",
        "value": "cert.example.com",
        "status": "stale",
        "tags": ["production"],
        "metadata": {"expires_at": "2024-01-01", "issuer": "Lets Encrypt"}
      },
      {
        "type": "service",
        "value": "22/tcp",
        "status": "active",
        "tags": ["production"],
        "metadata": {"port": 22, "protocol": "tcp"}
      },
      {
        "type": "ip_address",
        "value": "203.0.113.10",
        "status": "active",
        "tags": ["production"],
        "metadata": {}
      }
    ]
  }'
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        HTTP Client                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    FastAPI (port 8001)                       │
│                                                             │
│   /api/v1/assets/*          /api/v1/analyze/*               │
│   ┌──────────────┐          ┌──────────────────────────┐    │
│   │ Import API   │          │  LangChain Analysis      │    │
│   │ List / Get   │          │  ┌──────────────────┐    │    │
│   └──────┬───────┘          │  │ NL Query (Ph.4)  │    │    │
│          │                  │  │ Risk Score (Ph.5)│    │    │
│          │                  │  │ Enrichment (Ph.6)│    │    │
│          │                  │  │ Report Gen (Ph.7)│    │    │
│          │                  │  └────────┬─────────┘    │    │
└──────────┼──────────────────┼───────────┼──────────────┘    
           │                  │           │
┌──────────▼──────────────────▼─┐   ┌────▼──────────────┐
│         PostgreSQL             │   │   Groq API        │
│   assets + asset_relationships │   │ Llama 3.3 70B     │
└───────────────────────────────┘   └───────────────────┘
```

**Key design principle:** The LLM never queries the database directly and never returns asset data from memory. It only translates queries into filters (Phase 4), writes summaries from rule-engine outputs (Phase 5), makes classification decisions (Phase 6), and narrates structured facts (Phase 7). All actual asset data always comes from PostgreSQL.

---

## Project Structure

```
darkatlas-ai/
├── app/
│   ├── main.py                      # FastAPI app, lifespan, router registration
│   ├── config.py                    # Pydantic-settings (reads from .env)
│   ├── database.py                  # Async SQLAlchemy engine + session factory
│   ├── api/
│   │   ├── deps.py                  # Shared dependencies (DB session, API key auth)
│   │   └── routes/
│   │       ├── assets.py            # Import, list, get endpoints
│   │       └── analyze.py           # All 4 AI analysis endpoints
│   ├── models/
│   │   └── asset.py                 # SQLAlchemy ORM: Asset, AssetRelationship
│   ├── schemas/
│   │   └── asset.py                 # Pydantic schemas: request/response validation
│   └── services/
│       ├── asset_service.py         # DB operations: upsert, dedup, list, get
│       └── analysis/
│           ├── base.py              # LLM factory, shared prompt utilities
│           ├── nl_query.py          # Phase 4: NL → structured filter → DB query
│           ├── risk.py              # Phase 5: Rule engine + LLM summary
│           ├── enrichment.py        # Phase 6: LLM classification + DB write-back
│           └── report.py            # Phase 7: Full report generation
├── tests/
│   ├── test_risk.py                 # 17 tests: rule engine correctness
│   └── test_schemas.py              # 17 tests: input validation & normalization
├── docker-compose.yml               # PostgreSQL + FastAPI orchestration
├── Dockerfile                       # Python 3.12-slim container
├── requirements.txt                 # All pinned dependencies
├── pytest.ini                       # Test configuration
└── .env.example                     # Environment variable template
```

---

## API Endpoints

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | API liveness probe |
| `GET` | `/api/v1/analyze/health` | LLM connection test |

### Asset Management

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/v1/assets/import` | ✅ X-API-Key | Bulk import with deduplication |
| `GET` | `/api/v1/assets` | — | List assets (filter + paginate) |
| `GET` | `/api/v1/assets/{id}` | — | Get single asset by UUID |

**Import deduplication:** Assets are identified by `(type, value)`. Re-importing an existing asset updates `last_seen`, merges tags, and merges metadata. It never creates duplicates.

**List filters:** `?type=certificate&status=stale&tag=production&search=api&page=1&page_size=20`

### AI Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/analyze/query` | Natural-language asset query |
| `GET` | `/api/v1/analyze/risk` | Risk scoring + executive summary |
| `POST` | `/api/v1/analyze/enrich/{id}` | Classify and enrich an asset |
| `GET` | `/api/v1/analyze/report` | Full security report generation |

---

## AI Features — Example Prompts & Outputs

### Feature 1 — Natural-Language Query

**Request:**
```bash
curl -X POST http://localhost:8001/api/v1/analyze/query \
  -H "Content-Type: application/json" \
  -d '{"query": "show me all expired certificates on production"}'
```

**Response:**
```json
{
  "query": "show me all expired certificates on production",
  "explanation": "Filtering by certificate type, stale status, and production tag",
  "filters_applied": {
    "type": "certificate",
    "status": "stale",
    "tag": "production",
    "search": null
  },
  "total": 1,
  "assets": [...]
}
```

**How it works:** The LLM translates the English query into `{type, status, tag, search}` filters. Those filters are applied to the real database. The LLM never sees or returns asset data directly — hallucination is structurally impossible.

---

### Feature 2 — Risk Scoring

**Request:**
```bash
curl "http://localhost:8001/api/v1/analyze/risk?tag=production"
```

**Response:**
```json
{
  "total_assets_analyzed": 5,
  "risk_counts": {"critical": 1, "high": 1, "medium": 1, "low": 0},
  "findings": [
    {
      "asset_value": "22/tcp",
      "risk_level": "high",
      "finding": "High-risk service publicly exposed: SSH (22/tcp)",
      "recommendation": "Restrict SSH access to trusted IPs only."
    },
    {
      "asset_value": "cert.example.com",
      "risk_level": "high",
      "finding": "Certificate EXPIRED 908 day(s) ago (expiry: 2024-01-01)",
      "recommendation": "Renew this certificate immediately."
    }
  ],
  "summary": "The organization's attack surface presents a high risk posture..."
}
```

**How it works:** A deterministic Python rule engine runs first (no LLM). Rules flag expired certificates, dangerous ports, EOL technologies, and stale assets. The LLM then writes an executive summary from those findings — it cannot invent risks not present in the rule output.

**Rules applied:**
- Telnet (23), RDP (3389) exposed → CRITICAL
- SSH (22), FTP (21) exposed → HIGH
- Certificate expired → HIGH
- Certificate expiring within 30 days → HIGH
- Certificate expiring within 90 days → MEDIUM
- Technology with version (EOL risk) → MEDIUM
- Stale domain/subdomain/IP → MEDIUM

---

### Feature 3 — Asset Enrichment

**Request:**
```bash
curl -X POST http://localhost:8001/api/v1/analyze/enrich/1b4fc8cc-1469-4a5e-a581-3ce4172ba709
```

**Response:**
```json
{
  "asset_value": "api.example.com",
  "classification": {
    "environment": "production",
    "criticality": "high",
    "category": "web",
    "reasoning": "Asset is classified as production/high because tags include 'production' and it is a customer-facing API subdomain.",
    "suggested_tags": ["api-endpoint", "customer-facing", "external-facing"]
  },
  "asset": {
    "tags": ["api-endpoint", "customer-facing", "external-facing", "high-criticality", "production", "web"],
    "metadata": {
      "enrichment": {
        "environment": "production",
        "criticality": "high",
        "category": "web",
        "enriched_at": "2026-06-26T18:24:52Z"
      }
    }
  }
}
```

**How it works:** The LLM classifies the asset into controlled vocabularies (environment: production/staging/development/internal/unknown, criticality: critical/high/medium/low, category: web/infrastructure/security/data/internal/unknown). All LLM output is validated against these sets before being written to the database — invalid values are rejected.

---

### Feature 4 — Report Generation

**Request:**
```bash
curl "http://localhost:8001/api/v1/analyze/report?tag=production"
```

**Response:**
```json
{
  "generated_at": "2026-06-26T18:32:28Z",
  "scope": {"tag": "production", "asset_type": null},
  "inventory": {
    "total_assets": 4,
    "by_type": {"subdomain": 1, "ip_address": 1, "certificate": 1, "domain": 1},
    "by_status": {"active": 3, "stale": 1}
  },
  "risk_counts": {"critical": 0, "high": 1, "medium": 1, "low": 0},
  "report": "## Executive Summary\nThe organization's production attack surface...\n\n## Asset Inventory\n...\n\n## Risk Analysis\n...\n\n## Recommendations\n1. Renew cert.example.com immediately...\n\n## Conclusion\n..."
}
```

**How it works:** Inventory statistics are computed in Python. Risk findings come from the rule engine. The LLM receives structured facts and writes a 5-section report (Executive Summary, Asset Inventory, Risk Analysis, Recommendations, Conclusion). Scoped reports (`?tag=production`) analyze only matching assets.

---

## Design Decisions

### 1. Anti-hallucination grounding strategy
The LLM is never given free access to asset data. In every feature:
- **Query (Ph.4):** LLM outputs filters only. Assets come from DB.
- **Risk (Ph.5):** Rules run first. LLM only narrates rule outputs.
- **Enrichment (Ph.6):** LLM outputs classification labels validated against enums.
- **Report (Ph.7):** LLM receives structured facts and writes narrative only.

### 2. Rule engine before LLM for risk scoring
Deterministic Python rules produce consistent, auditable, fast risk scores. The LLM is used only for the narrative — not the scoring decision. This means risk scores do not change between runs and can be reasoned about independently of LLM behavior.

### 3. Upsert deduplication at the database level
The `UNIQUE(type, value)` constraint on the `assets` table enforces deduplication at the database level — even if application code has a bug, Postgres will reject duplicates. The application layer checks for existing assets first and updates (merges tags, updates `last_seen`) rather than inserting.

### 4. Async throughout
FastAPI, SQLAlchemy, and LangChain are all used in async mode. This means the server handles other requests while waiting for Groq API responses (which can take 1–3 seconds). A synchronous design would block the entire server during LLM calls.

### 5. Separation of concerns
- Routes handle only HTTP concerns (request parsing, response formatting, error codes)
- Services handle business logic and database operations
- Analysis services handle LLM interaction
- Models define data shape
- Schemas define API contracts

### 6. Provider-agnostic LLM layer
The `get_llm()` factory in `base.py` supports Groq, Anthropic, and OpenAI via a single `LLM_PROVIDER` environment variable. Switching providers requires only a `.env` change — no code changes.

---

## Running Tests

```bash
# Run all tests inside Docker
docker exec -it intern-api-1 pytest tests/ -v

# Expected output: 34 passed
```

Tests cover:
- Risk rule engine: expired certs, dangerous ports, stale assets, severity ordering
- Schema validation: value normalization, tag cleaning, type validation, bulk limits

Tests are pure Python — no database or LLM calls required.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | (set by docker-compose) | PostgreSQL connection string |
| `API_KEY` | Yes | `dev-api-key-...` | Key required for write operations (`X-API-Key` header) |
| `LLM_PROVIDER` | Yes | `groq` | LLM provider: `groq`, `anthropic`, or `openai` |
| `GROQ_API_KEY` | If using Groq | — | API key from console.groq.com |
| `ANTHROPIC_API_KEY` | If using Anthropic | — | API key from console.anthropic.com |
| `OPENAI_API_KEY` | If using OpenAI | — | API key from platform.openai.com |
| `LLM_MODEL` | Yes | `llama-3.3-70b-versatile` | Model name for the chosen provider |
| `DEBUG` | No | `false` | Set to `true` to log all SQL queries |

> **Security note:** Never commit `.env` to version control. The `.gitignore` excludes it. Use `.env.example` as the template.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API framework | FastAPI 0.115 + Uvicorn |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 (async) |
| Migrations | Auto-create via `Base.metadata.create_all` on startup |
| AI / LLM | LangChain 0.3 + Groq (Llama 3.3 70B) |
| Validation | Pydantic v2 |
| Testing | pytest 8.3 + pytest-asyncio |
| Infrastructure | Docker + Docker Compose |
