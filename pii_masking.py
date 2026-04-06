from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
import re

configuration = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]
}
provider = NlpEngineProvider(nlp_configuration=configuration)
nlp_engine = provider.create_engine()

analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
anonymizer = AnonymizerEngine()

def mask_pii(text: str) -> tuple[str, dict]:
    if not text:
        return text, {}
        
    results = analyzer.analyze(text=text, entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IBAN_CODE"], language='en')
    results = sorted(results, key=lambda x: x.start, reverse=True)
    
    masked_text = text
    mapping = {}
    counters = {}
    
    for res in results:
        entity_type = res.entity_type
        original_value = text[res.start:res.end]
        
        if entity_type not in counters:
            counters[entity_type] = 1
        else:
            counters[entity_type] += 1
            
        token = f"<{entity_type}_{counters[entity_type]}>"
        mapping[token] = original_value
        masked_text = masked_text[:res.start] + token + masked_text[res.end:]
        
    return masked_text, mapping

def unmask_pii(text: str, mapping: dict) -> str:
    if not text:
        return text
        
    unmasked_text = text
    for token, original_value in mapping.items():
        unmasked_text = unmasked_text.replace(token, original_value)
        
    return unmasked_text
