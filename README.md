# Enterprise GenAI Proxy Gateway

A production-grade middleware gateway built with **FastAPI** that sits between enterprise employees and foundation LLMs (Groq, HuggingFace, OpenAI, etc.).

## Features

- **PII Masking** — Microsoft Presidio + spaCy `en_core_web_sm` detect and replace PERSON, EMAIL, PHONE, CREDIT_CARD, SSN, IBAN entities with reversible tokens before any prompt leaves your network.
- **LLM-as-a-Judge Guardrails** — Uses Groq/LiteLLM to classify prompts as `ALLOWED` or `BLOCKED` (non-work / policy violations). Fail-open: guardrail errors never block legitimate traffic.
- **Department Budget Enforcement** — SQLAlchemy (SQLite dev / PostgreSQL prod) tracks per-department token spend. HTTP 402 when a department exceeds its budget limit.
- **Redis Rate Limiting** — Fixed-window counter per department per minute. HTTP 429 + `Retry-After` header on excess. Fail-open if Redis is down.
- **Redis Response Cache** — SHA-256 keyed cache of LLM responses (TTL 1 hour). Identical masked prompts return instantly at $0 cost.
- **Provider-Agnostic Routing** — LiteLLM routes to Groq, OpenAI, HuggingFace with automatic fallback. Same `completion()` call regardless of provider.
- **Analytics Dashboard** — Served at `/dashboard`. Jinja2 + Chart.js. Shows total cost, tokens, active departments, and live RPM counters per department.

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API Framework** | FastAPI + Uvicorn | High-performance async HTTP server |
| **PII Detection** | Microsoft Presidio + spaCy | Entity extraction (PERSON, EMAIL, PHONE, CC, SSN) |
| **LLM Routing** | LiteLLM | Provider-agnostic interface to 100+ LLMs |
| **LLM Guardrails** | Groq (via LiteLLM) | "Judge" model for classifying prompt safety |
| **Database** | SQLAlchemy + PostgreSQL (prod) / SQLite (dev) | Token usage logging + API key storage |
| **Caching** | Redis | Rate limit counters + LLM response cache |
| **Dashboard** | Jinja2 + Chart.js (frontend) | Real-time analytics visualization |
| **Deployment** | Docker + Railway.com | Containerized deployment on managed platform |

## Project Structure

```
enterprise-genai-proxy-gateway/
│
├── main.py              ← FastAPI gateway — orchestrates all 8 pipeline steps
├── pii_masking.py       ← Microsoft Presidio + spaCy — mask & unmask PII
├── guardrails.py        ← LLM-as-a-judge — ALLOWED / BLOCKED classification
├── cost_tracker.py      ← Token usage logging + budget enforcement queries
├── database.py          ← SQLAlchemy models (TokenUsage, APIKey) + DB seeding
├── rate_limiter.py      ← Redis-backed rate limiting + response caching
│
├── templates/
│   └── dashboard.html   ← Analytics dashboard (Jinja2 + Chart.js)
│
├── Dockerfile           ← python:3.11-slim + spaCy model pre-baked
├── railway.json         ← Railway.com deployment config
├── requirements.txt     ← All Python dependencies
└── .env                 ← API keys (not committed — see .gitignore)
```

## Request Pipeline

```
POST /v1/chat/completions
  │
  ▼
1. API Key Auth        → Identifies department + budget_limit
2. Budget Enforcement  → HTTP 402 if spend ≥ limit
3. Redis Rate Limit    → HTTP 429 if > 20 RPM (fail-open)
4. LLM Guardrail       → HTTP 403 if BLOCKED (fail-open)
5. PII Masking         → Presidio replaces PII with tokens
6. LLM Routing         → LiteLLM → Groq / HuggingFace fallback
7. PII Unmasking       → Tokens restored in response
8. Cost Logging        → SQLAlchemy writes to DB
```

## Quick Start (Local)

```bash
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # Windows
# source .venv/bin/activate     # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 3. Configure environment
# Edit .env with your API keys:
#   GROQ_API_KEY=gsk_your_key
#   DEFAULT_MODEL=groq/llama-3.3-70b-versatile

# 4. Run the gateway
uvicorn main:app --reload

# Gateway: http://localhost:8000
# Dashboard: http://localhost:8000/dashboard
# API Docs: http://localhost:8000/docs
```



## Pre-Seeded API Keys

| Key | Department | Role | Budget |
|-----|-----------|------|--------|
| `sk-eng-1234` | Engineering | admin | $5.00 |
| `sk-eng-1235` | Engineering | standard | $5.00 |
| `sk-mkt-5678` | Marketing | standard | $5.00 |
| `sk-hr-9999` | HR | standard | $2.00 |
| `sk-fin-4321` | Finance | admin | $10.00 |

## Testing

```bash
python test_proxy.py
```
