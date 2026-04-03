import httpx
import os
import asyncio
import json

PROXY_URL = "http://localhost:8000/v1/chat/completions"

async def test_api():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("=================================================")
        print("--- Test 1: Valid work request with PII ---")
        print("=================================================")
        headers = {"X-API-Key": "sk-eng-1234", "Content-Type": "application/json"}
        payload = {
            "messages": [
                {"role": "user", "content": "My name is John Doe and my phone number is 555-019-9238. Can you help me write a Python script to sort an array? Mention my name in the response so I know you are talking to me."}
            ]
        }
        
        print(f"User Request: {payload['messages'][0]['content']}")
        print("Note: The proxy will swap John Doe with <PERSON_1> before sending to LLM, then swap it back on response.\n")
        resp = await client.post(PROXY_URL, headers=headers, json=payload)
        
        if resp.status_code == 200:
            print(f"OK Status: {resp.status_code}")
            print(f"LLM Response: {resp.json()['choices'][0]['message']['content']}")
        else:
             print(f"Error: {resp.status_code} - {resp.text}")

        print("\n=================================================")
        print("--- Test 2: Inappropriate/Non-work topic (Guardrails Check) ---")
        print("=================================================")
        headers2 = {"X-API-Key": "sk-mkt-5678", "Content-Type": "application/json"}
        payload2 = {
            "messages": [
                {"role": "user", "content": "Who should I vote for in the upcoming election? Tell me about your political views."}
            ]
        }
        
        print(f"User Request: {payload2['messages'][0]['content']}")
        print("Expectation: The LLM Guardrail judge should block this.\n")
        resp2 = await client.post(PROXY_URL, headers=headers2, json=payload2)
        print(f"HTTP Status: {resp2.status_code}")
        print(f"Guardrail Response: {resp2.text}")

        print("\n=================================================")
        print("--- Test 3: Checking Dashboard Database ---")
        print("=================================================")
        resp3 = await client.get("http://localhost:8000/dashboard")
        if resp3.status_code == 200:
            print("Dashboard is up and running. Metrics successfully saved to SQLite!")

        print("\n=================================================")
        print("--- Test 4: Invalid API Key Authentication ---")
        print("=================================================")
        headers_invalid = {"X-API-Key": "sk-fake-key", "Content-Type": "application/json"}
        resp_invalid = await client.post(PROXY_URL, headers=headers_invalid, json=payload2)
        print(f"HTTP Status: {resp_invalid.status_code}")
        print(f"Response: {resp_invalid.text}")

        print("\n=================================================")
        print("--- Test 5: Langflow Agent Routing ---")
        print("=================================================")
        payload_langflow = {
            "model": "agent/langflow",
            "messages": [
                {"role": "user", "content": "Hello! My employee ID is 555-123-4567. What processes should I follow?"}
            ]
        }
        print(f"User Request: {payload_langflow['messages'][0]['content']}")
        print("Routing to Langflow Webhook -> 60386824-95c4-45c4-b98d-8031477cecf1\n")
        try:
            resp_langflow = await client.post(PROXY_URL, headers=headers, json=payload_langflow)
            if resp_langflow.status_code == 200:
                print(f"OK Status: {resp_langflow.status_code}")
                print(f"Langflow Agent Response: {resp_langflow.json()['choices'][0]['message']['content']}")
            else:
                print(f"Error: {resp_langflow.status_code} - {resp_langflow.text}")
        except Exception as e:
            print(f"Make sure Langflow is running at http://localhost:7860 to test this! Error: {e}")
            
if __name__ == "__main__":
    asyncio.run(test_api())
