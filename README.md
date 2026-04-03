# Enterprise GenAI Proxy Gateway

A middle-layer API built with FastAPI that sits between enterprise employees and foundation LLMs (Groq, HuggingFace, OpenAI, etc.).

## Features
- **PII Masking**: Automatically strips out sensitive data using Microsoft Presidio before sending requests to LLMs, and seamlessly re-injects the data on the return trip.
- **Cost Tracking & Rate Limiting**: Intercepts LiteLLM metrics to track tokens and cost spent per department. Includes an aesthetic UI Dashboard to visualize usage.
- **Topic Guardrails**: Implements a high-speed LLM-as-a-judge mechanism to evaluate prompts and prevent the usage of APIs for non-work or political queries.

## Architecture
See `ARCHITECTURE_AND_STEPS.md` for a comprehensive breakdown of the application architecture and the step-by-step processes used to build this system.

## Quick Start

1. **Install Dependencies**
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

2. **Configure Environment**
Create a `.env` file (or edit the existing one) to include your API Keys:
```env
GROQ_API_KEY=gsk_your_key
DEFAULT_MODEL=groq/llama-3.3-70b-versatile
```

3. **Run the Proxy**
```bash
uvicorn main:app --reload
```
The server will start on port `8000`. You can test it by running `python test_proxy.py` in a separate terminal.

4. **View the Dashboard**
Navigate to [http://localhost:8000/dashboard](http://localhost:8000/dashboard) to see your real-time token tracking by department.
