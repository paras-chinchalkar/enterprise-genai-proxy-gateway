import chainlit as cl
import httpx
import json
import os

PROXY_URL = os.environ.get("PROXY_URL", "http://localhost:8000/v1/chat/completions")
API_KEY = "sk-eng-1234" # Default engineering department key

@cl.on_chat_start
async def start_chat():
    cl.user_session.set("message_history", [])
    
    await cl.Message(
        content="Welcome to the Enterprise GenAI Proxy Demo! \n"
                "I am your assistant. Any messages you send me are properly routed through the secure Enterprise Gateway.\n\n"
                "Things happening in the background:\n"
                "- **Guardrails:** Non-work topics are blocked.\n"
                "- **Privacy:** PII is automatically masked before reaching the LLM.\n"
                "- **Billing:** Token costs are tracked per department.\n\n"
                "Try saying: *'My name is John Doe and my phone number is 555-019-9238. Write a python script.'*"
    ).send()

@cl.on_message
async def main(message: cl.Message):
    # Retrieve chat history
    message_history = cl.user_session.get("message_history")
    message_history.append({"role": "user", "content": message.content})
    
    # Show loading indicator
    msg = cl.Message(content="")
    await msg.send()
    
    headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "groq/llama-3.3-70b-versatile", # Default model
        "messages": message_history
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(PROXY_URL, headers=headers, json=payload)
            
            if response.status_code == 403:
                # Guardrails blocked
                error_detail = response.json().get("detail", response.text)
                await cl.Message(
                    content=f"🚨 **Blocked by Guardrails:** {error_detail}"
                ).send()
                message_history.pop() # Remove blocked message from history
                return
                
            response.raise_for_status()
            
            data = response.json()
            completion_text = data["choices"][0]["message"]["content"]
            
            # Extract Metrics
            usage = data.get("usage", {})
            total_tokens = usage.get("total_tokens", 0)
            cost = usage.get("estimated_cost", 0.0)
            model_used = data.get("model", "N/A")
            
            # Add assistant message to history
            message_history.append({"role": "assistant", "content": completion_text})
            cl.user_session.set("message_history", message_history)
            
            # Stream the main content (simulated streaming since API is blocking)
            msg.content = completion_text
            await msg.update()
            
            # Send the metrics as small elements or a secondary message
            metrics_content = (
                f"**Proxy Diagnostics**\n"
                f"- **Model:** {model_used}\n"
                f"- **Tokens:** {total_tokens}\n"
                f"- **Estimated Cost:** ${cost:.6f}"
            )
            await cl.Message(
                content=metrics_content,
                author="System"
            ).send()

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP Error: {e.response.status_code} - {e.response.text}"
        await cl.Message(content=f"❌ Error communicating with proxy.\n```\n{error_msg}\n```").send()
    except Exception as e:
        await cl.Message(content=f"❌ An error occurred: {str(e)}\n\nMake sure the FastAPI proxy is running on `http://localhost:8000`!").send()
