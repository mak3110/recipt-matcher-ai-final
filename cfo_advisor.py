import os
import logging
from google import genai
from google.genai import types
from typing import List, Dict, Any

logger = logging.getLogger("receipt_matcher")

CFO_SYSTEM_PROMPT = """You are a virtual CFO and tax advisor for a small business owner. You have access to the user's parsed receipts database.

Guidelines:
- Reference specific vendors, transaction dates, and amounts when answering.
- Summarize deductibility rules (e.g., reminding them that business meals are subject to the 50% IRS limit).
- Highlight potential tax savings, duplicate charges, or suspicious uncategorized expenses.
- Keep explanations concise, practical, and devoid of heavy accounting jargon.
- Always include a brief disclaimer that you are an AI assistant and that tax filings should be reviewed by a certified CPA."""

def get_cfo_advice(user_query: str, ledger: List[Dict[str, Any]], api_key: str) -> str:
    clean_key = api_key.strip().strip('"').strip("'")
    client = genai.Client(api_key=clean_key)
    
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    logger.info("Using Gemini model for CFO Advice: %s", model_name)
    
    config = types.GenerateContentConfig(
        system_instruction=CFO_SYSTEM_PROMPT
    )
    
    context_prompt = f"""
    Current Parsed Receipts Ledger Database:
    {ledger}

    User Question: {user_query}
    
    Provide your concise, actionable Virtual CFO guidance based on the receipt ledger above.
    """
    
    response = client.models.generate_content(
        model=model_name,
        contents=context_prompt,
        config=config
    )
    return getattr(response, "text", "")
