import os
from litellm import completion

def check_topic_guardrails(prompt: str) -> bool:
    if not prompt or len(prompt) < 3:
        return True
        
    system_prompt = (
        "You are an enterprise AI guardrail. "
        "Your job is to evaluate whether a user's prompt is strictly related to professional work, technology, general inquiries, or software development "
        "and is definitively free of controversial politics, hate speech, inflammatory topics, or sexually explicit content. "
        "Return ONLY the word 'ALLOWED' if it is acceptable. "
        "Return ONLY the word 'BLOCKED' if it is not acceptable."
    )
    
    model = os.getenv("DEFAULT_MODEL", "huggingface/HuggingFaceH4/zephyr-7b-beta")
    
    try:
        response = completion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=10,
        )
        
        result_text = response.choices[0].message.content.strip().upper()
        
        if "BLOCKED" in result_text:
            return False
        return True
            
    except Exception as e:
        print(f"Guardrail failure: {e}")
        return True
