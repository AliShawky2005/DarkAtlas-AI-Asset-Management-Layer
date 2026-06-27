# DarkAtlas — AI Asset Management Layer

> **Buguard AI Internship Assessment — Track B: AI Applications**

A LangChain-powered analysis layer for Buguard's DarkAtlas Attack Surface Management platform. This system ingests internet-facing assets, deduplicates them, and exposes an entire suite of AI-driven analysis features. 

**This implementation completes all base requirements AND all 6 bonus requirements!**

---

## 🌟 Key Features & Bonuses Implemented

1. **Multi-tenancy (Bonus 1):** Complete database isolation using `organization_id` and the `X-Org-Id` header.
2. **Role-Based Access Control (Bonus 2):** Secure API key management with `bcrypt` hashing, supporting `admin` and `reader` roles via `X-API-Key`.
3. **Graph Visualization (Bonus 3):** An interactive, live D3.js force-directed graph to visualize your assets and their relationships (`GET /graph`).
4. **Caching & Rate Limiting (Bonus 4):** `slowapi` enforces strict rate limits (60/min globally, 10/min for LLMs). Expensive LLM operations are cached for 5 minutes using `cachetools`.
5. **ReAct AI Agent (Bonus 5):** An autonomous LangGraph agent (`POST /api/v1/agent/chat`) equipped with 5 tools to query the database and perform analysis dynamically.
6. **LLM Evaluation Harness (Bonus 6):** An automated "LLM-as-a-judge" module (`POST /api/v1/eval/*`) to score the AI on relevance, clarity, and hallucination detection.
7. **Core AI Analysis (Track B):** Natural Language Querying, Risk Scoring, Automated Classification & Enrichment, and automated Report Generation.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
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
git clone https://github.com/AliShawky2005/DarkAtlas-AI-Asset-Management-Layer.git
cd DarkAtlas-AI-Asset-Management-Layer
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
[DarkAtlas] Tables synced. API v2.0.0 ready.
```

### 3. Access the Application

- **API Documentation (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs) (or 8001 depending on your local Docker bindings)
- **Graph Visualization UI:** [http://localhost:8000/graph](http://localhost:8000/graph)

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                        HTTP Client                          │
└─────────────────────┬───────────────────────────────────────┘
                      │   X-API-Key (RBAC Auth)
                      │   X-Org-Id (Multi-tenancy)
┌─────────────────────▼───────────────────────────────────────┐
│                    FastAPI (port 8000)                      │
│                                                             │
│   /assets/*         /analyze/*             /agent/*         │
│   ┌──────────────┐  ┌──────────────────┐   ┌────────────┐   │
│   │ Import API   │  │ NL Query (Ph.4)  │   │ LangGraph  │   │
│   │ List / Get   │  │ Risk Score (Ph.5)│   │ ReAct Agent│   │
│   └──────┬───────┘  │ Enrichment (Ph.6)│   └──────┬─────┘   │
│          │          │ Report Gen (Ph.7)│          │         │
│          │          └────────┬─────────┘          │         │
└──────────┼───────────────────┼────────────────────┼─────────┘    
           │                   │                    │
┌──────────▼───────────────────▼─┐        ┌─────────▼─────────┐
│         PostgreSQL             │        │    Groq API       │
│   assets + organizations       │        │ Llama 3.3 70B     │
│   api_keys                     │        └───────────────────┘
└────────────────────────────────┘
```

**Anti-Hallucination Design:** The LLM never queries the database directly and never returns raw asset data from memory. It translates queries into strict JSON filters, writes summaries based on strict Python rule-engine outputs, and makes classifications from strict Enums. All database facts remain 100% accurate.

---

## API Endpoints

### 1. Authentication & Tenancy
All endpoints require an `X-API-Key` header.
- **Admin Role:** Can import assets, enrich data, create new keys, and access eval endpoints.
- **Reader Role:** Read-only access to `/assets`, `/analyze`, and `/agent`.

*To create an org or key, hit `POST /api/v1/orgs` and `POST /api/v1/auth/keys` using the `API_KEY` defined in your `.env`.*

### 2. Asset Management (`/api/v1/assets`)
- `POST /import`: Bulk import assets (deduplicates on `type` + `value` + `organization_id`).
- `GET /`: List and filter assets.

### 3. AI Analysis (`/api/v1/analyze`)
- `POST /query`: Natural language to DB query ("Show me active databases").
- `GET /risk`: Rule-engine risk assessment with an AI executive summary.
- `POST /enrich/{id}`: AI classification of asset environment, criticality, and category.
- `GET /report`: Full automated markdown security report generation.

### 4. AI Agent (`/api/v1/agent`)
- `POST /chat`: Talk to an autonomous ReAct agent equipped with 5 tools to query the database and perform analysis dynamically.

### 5. Evaluation Harness (`/api/v1/eval`)
- `POST /risk`, `POST /report`, `POST /query`: Triggers an "LLM-as-a-judge" to evaluate the AI outputs on relevance, clarity, and hallucination metrics.

---

## Running Tests

We have **43 automated tests** covering risk rules, schemas, and the evaluation harness.

```bash
# Run all tests inside Docker
docker-compose exec -T api pytest tests/ -v
```

Tests are pure Python — no database or LLM calls required.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | (set by docker) | PostgreSQL connection string |
| `API_KEY` | Yes | `dev-api-key...` | Master Admin Key (`X-API-Key` header) |
| `DEFAULT_ORG_ID`| Yes | `default` | Fallback Org ID if `X-Org-Id` isn't provided |
| `LLM_PROVIDER` | Yes | `groq` | LLM provider: `groq`, `anthropic`, or `openai` |
| `GROQ_API_KEY` | If Groq | — | API key from console.groq.com |
| `LLM_MODEL` | Yes | `llama-3.3-70b...`| Model name for the chosen provider |
| `RATE_LIMIT_*` | Yes | `60/minute` | Global and LLM rate limit configurations |
