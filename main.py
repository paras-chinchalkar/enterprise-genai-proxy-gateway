"""
main.py — Enterprise GenAI Proxy Gateway

Request Pipeline (in order):
  1. API Key Auth          → identifies department + budget_limit
  2. Budget Enforcement    → HTTP 402 if dept spend >= limit (SQLite/Postgres)
  3. Redis Rate Limiting   → HTTP 429 if dept exceeds RPM (Redis, fail-open)
  4. LLM-as-Judge Guardrail→ HTTP 403 if prompt is non-work/inappropriate
  5. PII Masking           → Presidio replaces PERSON/EMAIL/PHONE/CC/SSN with tokens
  6. LLM Routing           → LiteLLM dispatches to Groq/OpenAI/HuggingFace
  7. PII Unmasking         → Restores original values in the response
  8. Cost Logging          → Writes tokens + cost to DB per department
"""

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os
import hashlib
import json
import pathlib
import time
from dotenv import load_dotenv
import litellm
from litellm import completion
from fastapi.security import APIKeyHeader
from database import get_db, APIKey
from cost_tracker import check_budget_exceeded, log_usage, get_department_stats, get_department_request_count
from rate_limiter import check_rate_limit, get_redis_cache, set_redis_cache
from guardrails import check_topic_guardrails
from pii_masking import mask_pii, unmask_pii

load_dotenv()

# --- LiteLLM local cache (fallback when Redis unavailable) ---
litellm.cache = litellm.Cache(type="local")

app = FastAPI(
    title="Enterprise GenAI Proxy Gateway",
    description="Secure middleware for enterprise LLM access with PII masking, guardrails, and cost tracking.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates_dir = pathlib.Path(__file__).parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "groq/llama-3.3-70b-versatile")

header_scheme = APIKeyHeader(name="X-API-Key")


# ─────────────────────────────────────────────────────────────────────────────
# Auth Dependency
# ─────────────────────────────────────────────────────────────────────────────

def verify_api_key(api_key: str = Depends(header_scheme), db: Session = Depends(get_db)):
    key_entry = db.query(APIKey).filter(APIKey.key == api_key).first()
    if not key_entry:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return key_entry


# ─────────────────────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Meta"])
async def health_check():
    """Liveness probe. Returns gateway status + Redis connectivity."""
    from rate_limiter import _get_redis
    redis_ok = _get_redis() is not None
    return {
        "status": "ok",
        "gateway": "Enterprise GenAI Proxy Gateway",
        "version": "1.0.0",
        "redis": "connected" if redis_ok else "unavailable (fail-open)",
        "default_model": DEFAULT_MODEL,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main Proxy Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/v1/chat/completions", tags=["Proxy"])
async def proxy_completions(
    request: Request,
    client_key: APIKey = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    department = client_key.department
    budget_limit = client_key.budget_limit

    # ── Step 2: Budget Enforcement ────────────────────────────────────────────
    if check_budget_exceeded(db, department, budget_limit):
        raise HTTPException(
            status_code=402,
            detail=f"Budget limit of ${budget_limit:.2f} exceeded for department '{department}'.",
        )

    # ── Step 3: Redis Rate Limiting ───────────────────────────────────────────
    is_allowed, rate_headers = check_rate_limit(department)
    if not is_allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded for department '{department}'. Max {os.getenv('RATE_LIMIT_RPM', '20')} requests/min."},
            headers=rate_headers,
        )

    # ── Parse Body ────────────────────────────────────────────────────────────
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="'messages' array is required")

    last_user_message = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )

    # ── Step 4: LLM-as-Judge Guardrail ───────────────────────────────────────
    is_safe = check_topic_guardrails(last_user_message)
    if not is_safe:
        raise HTTPException(
            status_code=403,
            detail="Request blocked by Enterprise Topic Guardrails: Non-work or policy-violating topic detected.",
        )

    # ── Step 5: PII Masking ───────────────────────────────────────────────────
    masked_messages = []
    global_mapping = {}

    for msg in messages:
        if msg["role"] == "user":
            masked_text, mapping = mask_pii(msg["content"])
            masked_messages.append({"role": "user", "content": masked_text})
            global_mapping.update(mapping)
        else:
            masked_messages.append(msg)

    model_to_use = body.get("model", DEFAULT_MODEL)

    # ── Step 6: LLM Routing via LiteLLM ──────────────────────────────────────
    if "/" not in model_to_use:
        provider = DEFAULT_MODEL.split("/")[0]
        model_to_use = f"{provider}/{model_to_use}"

    # Check Redis response cache (keyed by masked prompt + model)
    cache_key_raw = json.dumps({"model": model_to_use, "messages": masked_messages}, sort_keys=True)
    cache_key = "llm_cache:" + hashlib.sha256(cache_key_raw.encode()).hexdigest()
    cached_response = get_redis_cache(cache_key)

    if cached_response:
        cached_data = json.loads(cached_response)
        # Unmask PII in cached response
        cached_data["choices"][0]["message"]["content"] = unmask_pii(
            cached_data["choices"][0]["message"]["content"], global_mapping
        )
        cached_data["_cache_hit"] = True
        return cached_data

    try:
        response = completion(
            model=model_to_use,
            messages=masked_messages,
            temperature=body.get("temperature", 0.7),
            max_tokens=body.get("max_tokens", None),
            fallbacks=["huggingface/HuggingFaceH4/zephyr-7b-beta"],
            caching=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM Upstream Error: {str(e)}")

    # ── Step 7: PII Unmasking ─────────────────────────────────────────────────
    response_text = response.choices[0].message.content
    unmasked_text = unmask_pii(response_text, global_mapping)
    response.choices[0].message.content = unmasked_text

    prompt_tokens = getattr(response.usage, "prompt_tokens", 0)
    completion_tokens = getattr(response.usage, "completion_tokens", 0)
    total_tokens = getattr(response.usage, "total_tokens", 0)

    cost = 0.0
    if hasattr(response, "_hidden_params") and "response_cost" in response._hidden_params:
        cost = response._hidden_params["response_cost"] or 0.0

    # ── Step 8: Cost Logging ──────────────────────────────────────────────────
    log_usage(
        db=db, department=department, model=model_to_use,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        total_tokens=total_tokens, estimated_cost=cost,
    )

    res_dict = response.model_dump()
    if "usage" in res_dict and res_dict["usage"] is not None:
        res_dict["usage"]["estimated_cost"] = cost

    # Cache the masked response in Redis (store masked text — unmask on hit)
    res_dict_to_cache = dict(res_dict)
    res_dict_to_cache["choices"][0]["message"]["content"] = response_text  # store masked
    set_redis_cache(cache_key, json.dumps(res_dict_to_cache), ttl=3600)

    return res_dict


# ─────────────────────────────────────────────────────────────────────────────
# Analytics Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse, tags=["Observability"])
async def get_dashboard(request: Request, db: Session = Depends(get_db)):
    stats = get_department_stats(db)
    total_cost = sum(s["total_cost"] for s in stats)
    total_tokens = sum(s["total_tokens"] for s in stats)

    # Enrich stats with Redis rate-limit counters
    for s in stats:
        s["requests_this_minute"] = get_department_request_count(s["department"])

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "stats": stats,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Department Stats API (JSON — for React or external dashboards)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/stats", tags=["Observability"])
async def get_stats_api(db: Session = Depends(get_db)):
    """Machine-readable department stats endpoint for external dashboards / React UIs."""
    stats = get_department_stats(db)
    total_cost = sum(s["total_cost"] for s in stats)
    total_tokens = sum(s["total_tokens"] for s in stats)
    for s in stats:
        s["requests_this_minute"] = get_department_request_count(s["department"])
    return {
        "departments": stats,
        "totals": {"total_cost": total_cost, "total_tokens": total_tokens},
    }
