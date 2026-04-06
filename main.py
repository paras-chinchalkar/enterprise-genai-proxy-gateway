from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os
import pathlib
from dotenv import load_dotenv

from database import get_db, Base, engine, APIKey
from cost_tracker import log_usage, get_department_stats, check_budget_exceeded
from pii_masking import mask_pii, unmask_pii
from guardrails import check_topic_guardrails
from litellm import completion
import litellm
from fastapi.security import APIKeyHeader
import httpx
import uuid
import time

litellm.cache = litellm.Cache(type="local")

load_dotenv()

app = FastAPI(title="Enterprise GenAI Proxy Gateway")

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

def verify_api_key(api_key: str = Depends(header_scheme), db: Session = Depends(get_db)):
    key_entry = db.query(APIKey).filter(APIKey.key == api_key).first()
    if not key_entry:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return key_entry

@app.post("/v1/chat/completions")
async def proxy_completions(request: Request, client_key: APIKey = Depends(verify_api_key), db: Session = Depends(get_db)):
    department = client_key.department
    budget_limit = client_key.budget_limit
    
    if check_budget_exceeded(db, department, budget_limit):
        raise HTTPException(status_code=402, detail=f"Budget limit of ${budget_limit:.2f} exceeded for department {department}.")
        
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
        
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="Messages array is required")
        
    last_user_message = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    
    is_safe = check_topic_guardrails(last_user_message)
    if not is_safe:
        raise HTTPException(
            status_code=403, 
            detail="Request blocked by Enterprise Topic Guardrails (Non-work/Inappropriate topic detected)."
        )
        
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
    
    if model_to_use == "agent/langflow":
        langflow_url = "http://localhost:7860/api/v1/run/60386824-95c4-45c4-b98d-8031477cecf1"
        langflow_api_key = os.getenv("LANGFLOW_API_KEY", "")
        
        last_masked_prompt = next((m["content"] for m in reversed(masked_messages) if m["role"] == "user"), "")
        
        payload = {
            "output_type": "chat",
            "input_type": "chat",
            "input_value": last_masked_prompt,
            "session_id": str(uuid.uuid4())
        }
        headers = {"x-api-key": langflow_api_key} if langflow_api_key else {}
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                langflow_res = await client.post(langflow_url, json=payload, headers=headers)
                langflow_res.raise_for_status()
            langflow_data = langflow_res.json()
            response_text = langflow_data["outputs"][0]["outputs"][0]["results"]["message"]["text"]
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Langflow Upstream Error: {str(e)}")
            
        unmasked_text = unmask_pii(response_text, global_mapping)
        
        prompt_tokens = len(last_masked_prompt) // 4
        completion_tokens = len(unmasked_text) // 4
        total_tokens = prompt_tokens + completion_tokens
        cost = 0.0
        
        log_usage(
            db=db, 
            department=department, 
            model=model_to_use, 
            prompt_tokens=prompt_tokens, 
            completion_tokens=completion_tokens, 
            total_tokens=total_tokens, 
            estimated_cost=cost
        )
        
        res_dict = {
            "id": f"langflow-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_to_use,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": unmasked_text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens, "estimated_cost": cost}
        }
        return res_dict

    else:
        if "/" not in model_to_use:
            provider = DEFAULT_MODEL.split("/")[0]
            model_to_use = f"{provider}/{model_to_use}"
            
        try:
            response = completion(
                model=model_to_use,
                messages=masked_messages,
                temperature=body.get("temperature", 0.7),
                max_tokens=body.get("max_tokens", None),
                fallbacks=["huggingface/HuggingFaceH4/zephyr-7b-beta"],
                caching=True
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM Upstream Error: {str(e)}")
    
        response_text = response.choices[0].message.content
        unmasked_text = unmask_pii(response_text, global_mapping)
        response.choices[0].message.content = unmasked_text
        
        prompt_tokens = getattr(response.usage, 'prompt_tokens', 0)
        completion_tokens = getattr(response.usage, 'completion_tokens', 0)
        total_tokens = getattr(response.usage, 'total_tokens', 0)
        
        cost = 0.0
        if hasattr(response, '_hidden_params') and 'response_cost' in response._hidden_params:
          cost = response._hidden_params['response_cost'] or 0.0
        
        log_usage(
            db=db, 
            department=department, 
            model=model_to_use, 
            prompt_tokens=prompt_tokens, 
            completion_tokens=completion_tokens, 
            total_tokens=total_tokens, 
            estimated_cost=cost
        )
        
        res_dict = response.model_dump()
        if "usage" in res_dict and res_dict["usage"] is not None:
            res_dict["usage"]["estimated_cost"] = cost
        return res_dict

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request, db: Session = Depends(get_db)):
    stats = get_department_stats(db)
    total_cost = sum(s['total_cost'] for s in stats)
    total_tokens = sum(s['total_tokens'] for s in stats)
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html", 
        context={"stats": stats, "total_cost": total_cost, "total_tokens": total_tokens}
    )
