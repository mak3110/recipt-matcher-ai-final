import os
import logging
import io
from PIL import Image
from google import genai
from google.genai import types
from schemas import ReceiptExtraction

logger = logging.getLogger("receipt_matcher")

SYSTEM_PROMPT = """You are an expert forensic accountant and OCR engine. Your job is to extract structured bookkeeping and tax data from receipt or invoice images with zero tolerance for arithmetic error.

Extraction Rules:
1. Vendor: Identify the primary merchant or legal entity issuing the document into vendor_name.
2. Date: Extract the transaction date in YYYY-MM-DD format into transaction_date. If ambiguous (e.g., 04/05/2026), use the vendor's regional date convention. If completely missing, use the current year context.
3. Currency: Detect the 3-letter ISO code (e.g., USD, EUR, INR, GBP) into currency. Default to USD if uncertain.
4. Financial Arithmetic:
   - subtotal_net: Sum of all taxable/non-taxable items BEFORE taxes and fees.
   - total_tax_amount: Sum of all sales tax, VAT, GST, or state/local charges.
   - total_gross_amount: The absolute final amount paid. Ensure subtotal_net + total_tax_amount ≈ total_gross_amount.
   - If line-item discounts exist, subtract them from the net subtotal before calculating the final gross.
5. Line Items: Extract each individual product or service, its quantity, unit cost, and line total into line_items.
6. Tax Classification: You MUST select EXACTLY ONE of the following strict category strings for category:
   - "Software & Subscriptions"
   - "Travel & Transportation"
   - "Meals & Entertainment"
   - "Office Supplies & Hardware"
   - "Advertising & Marketing"
   - "Utilities & Rent"
   - "Uncategorized"

Output strictly valid JSON matching the provided schema."""

REEXAMINE_PROMPT_TEMPLATE = """A mathematical discrepancy was flagged during primary parsing. 

Image Context: An expense document.
Detected Subtotal: {subtotal_net}
Detected Tax: {total_tax_amount}
Reported Gross: {total_gross_amount}

Re-examine the image to resolve the difference. Check for:
- Included tips, gratuities, or service charges (add to gross/net accordingly).
- Applied coupons, store credits, or bottle deposits.
- Dual-rate taxes (e.g., city tax + state tax) that were missed in the initial scan.
- OCR optical misreads (e.g., confusing '8' and '3', or misplacing decimal points).

Return the corrected JSON schema with corrected totals."""

def extract_receipt_data(image_bytes: bytes, api_key: str) -> ReceiptExtraction:
    if not api_key:
        raise ValueError("API Key is missing in ocr_service")
        
    clean_key = api_key.strip().strip('"').strip("'")
    
    print(f"DEBUG: about to create genai.Client — key length={len(clean_key) if clean_key else 0}, key prefix={clean_key[:6] if clean_key else 'EMPTY'}")
    print(f"DEBUG: GOOGLE_APPLICATION_CREDENTIALS={os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
    print(f"DEBUG: GOOGLE_CLOUD_PROJECT={os.getenv('GOOGLE_CLOUD_PROJECT')}")
    print(f"DEBUG: GOOGLE_GENAI_USE_VERTEXAI={os.getenv('GOOGLE_GENAI_USE_VERTEXAI')}")
    
    client = genai.Client(api_key=clean_key)
    
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    logger.info("Using Gemini model: %s", model_name)
    print(f"DEBUG: extract_receipt_data using model '{model_name}' & key starting with: {clean_key[:5]}...")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=ReceiptExtraction,
        temperature=0.0
    )
    
    image = Image.open(io.BytesIO(image_bytes))
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[image],
            config=config
        )
        raw_text = getattr(response, "text", None)
        logger.info("Raw response text from Gemini:\n%s", raw_text)
        print(f"[DEBUG GEMINI RAW RESPONSE]:\n{raw_text}")
        return ReceiptExtraction.model_validate_json(raw_text)
    except Exception as e:
        logger.error("Error during Gemini extract_receipt_data: %s", e, exc_info=True)
        print(f"[DEBUG GEMINI ERROR in extract_receipt_data]: {type(e).__name__}: {e}")
        raise

def reexamine_discrepancy(image_bytes: bytes, api_key: str, subtotal_net: float, total_tax_amount: float, total_gross_amount: float) -> ReceiptExtraction:
    if not api_key:
        raise ValueError("API Key is missing in ocr_service")
        
    clean_key = api_key.strip().strip('"').strip("'")
    
    print(f"DEBUG: about to create genai.Client — key length={len(clean_key) if clean_key else 0}, key prefix={clean_key[:6] if clean_key else 'EMPTY'}")
    print(f"DEBUG: GOOGLE_APPLICATION_CREDENTIALS={os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
    print(f"DEBUG: GOOGLE_CLOUD_PROJECT={os.getenv('GOOGLE_CLOUD_PROJECT')}")
    print(f"DEBUG: GOOGLE_GENAI_USE_VERTEXAI={os.getenv('GOOGLE_GENAI_USE_VERTEXAI')}")
    
    client = genai.Client(api_key=clean_key)
    
    prompt = REEXAMINE_PROMPT_TEMPLATE.format(
        subtotal_net=subtotal_net,
        total_tax_amount=total_tax_amount,
        total_gross_amount=total_gross_amount
    )
    
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    config = types.GenerateContentConfig(
        system_instruction=prompt,
        response_mime_type="application/json",
        response_schema=ReceiptExtraction,
        temperature=0.0
    )
    
    image = Image.open(io.BytesIO(image_bytes))
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[image],
            config=config
        )
        raw_text = getattr(response, "text", None)
        logger.info("Raw response text from Gemini (re-examine):\n%s", raw_text)
        print(f"[DEBUG GEMINI RAW REEXAMINE RESPONSE]:\n{raw_text}")
        return ReceiptExtraction.model_validate_json(raw_text)
    except Exception as e:
        logger.error("Error during Gemini reexamine_discrepancy: %s", e, exc_info=True)
        print(f"[DEBUG GEMINI ERROR in reexamine_discrepancy]: {type(e).__name__}: {e}")
        raise
