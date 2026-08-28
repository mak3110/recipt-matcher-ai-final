import os
import json
import logging
import io
from PIL import Image
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from jose import jwt
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError

try:
    from google.genai.errors import APIError
    from google.api_core.exceptions import GoogleAPIError
except ImportError:
    APIError = Exception
    GoogleAPIError = Exception

from database import engine, Base, get_db
from models import User, Receipt, LedgerTransaction
from schemas import CFORequest, UserCreate, UserLogin, TokenResponse
from ocr_service import extract_receipt_data, reexamine_discrepancy
from tax_engine import verify_and_adjust_tax
from tax_summary import generate_tax_report
from cfo_advisor import get_cfo_advice
from auth import hash_password, verify_password, create_access_token, get_current_user

# Initialize logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("receipt_matcher.log", mode="a", encoding="utf-8")
    ]
)
logger = logging.getLogger("receipt_matcher")

# Load environment variables from api.env if present
load_dotenv("api.env")

# Ensure tables exist
Base.metadata.create_all(bind=engine)

def get_user_or_ip_key(request: Request) -> str:
    if hasattr(request.state, "user") and request.state.user:
        user_id = getattr(request.state.user, "id", None) or getattr(request.state.user, "email", None)
        if user_id:
            return f"user:{user_id}"
            
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            from auth import SECRET_KEY, ALGORITHM
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_identity = payload.get("sub")
            if user_identity:
                return f"user:{user_identity}"
        except Exception:
            pass
            
    return get_remote_address(request)

limiter = Limiter(key_func=get_user_or_ip_key)

app = FastAPI(title="AI Receipt & Tax Auditor")
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "You have reached your scan limit. Please try again later."}
    )

app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)

API_KEY = os.getenv("GEMINI_API_KEY")

@app.get("/")
def read_root():
    return {"status": "healthy", "message": "AI Receipt & Tax Auditor API is active."}

@app.post("/api/v1/signup", response_model=TokenResponse)
async def signup(user_data: UserCreate, db: Session = Depends(get_db)):
    try:
        existing = db.query(User).filter(User.email == user_data.email).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User with this email already exists.")
        
        hashed_pwd = hash_password(user_data.password)
        new_user = User(
            email=user_data.email,
            name=user_data.name or user_data.email.split("@")[0],
            hashed_password=hashed_pwd
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        token = create_access_token(data={"sub": new_user.email})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {"id": new_user.id, "email": new_user.email, "name": new_user.name}
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Database Error in signup: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database service temporarily unavailable.")
    except Exception as e:
        db.rollback()
        logger.error("Unexpected Error in signup: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal error occurred during user registration.")

@app.post("/api/v1/login", response_model=TokenResponse)
async def login(user_data: UserLogin, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == user_data.email).first()
        if not user or not verify_password(user_data.password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password credentials.")
        
        token = create_access_token(data={"sub": user.email})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {"id": user.id, "email": user.email, "name": user.name}
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.error("Database Error in login: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database service temporarily unavailable.")
    except Exception as e:
        logger.error("Unexpected Error in login: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal error occurred during login.")

@app.post("/api/v1/process-receipt")
@limiter.limit("5/minute")
@limiter.limit("50/day")
async def process_receipt(
    request: Request = None,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        print(f"[PROCESS_RECEIPT ERROR] Invalid file type: {file.content_type}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file type. Upload JPG, PNG, or WEBP.")
    
    # Read file & log file receipt details
    contents = await file.read()
    logger.info("RECEIVED FILE: filename=%s, content_type=%s, size=%d bytes", getattr(file, "filename", None), getattr(file, "content_type", None), len(contents))
    print(f"\n[PROCESS_RECEIPT] File received: filename={getattr(file, 'filename', None)}, content_type={getattr(file, 'content_type', None)}, size={len(contents)} bytes")
    
    if len(contents) > 100 * 1024 * 1024:
        print("[PROCESS_RECEIPT ERROR] File size exceeds 100MB limit")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds maximum limit of 100MB.")
    
    # Verify file is a real image (JPEG/PNG/WEBP), check image size, resize down if wider than 2000px, and convert to JPEG at 85% quality
    try:
        image = Image.open(io.BytesIO(contents))
        image.verify()
        if image.format not in ["JPEG", "PNG", "WEBP"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported image format. Upload JPEG, PNG, or WEBP.")
            
        image = Image.open(io.BytesIO(contents))
        if image.mode != "RGB":
            image = image.convert("RGB")
            
        max_dim = 2000
        if image.width > max_dim or image.height > max_dim:
            image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        contents = buffer.getvalue()
        print(f"[PROCESS_RECEIPT] Image processed & compressed to size={len(contents)} bytes")
    except Exception as e:
        print(f"[PROCESS_RECEIPT ERROR] Image processing error: {type(e).__name__}: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or corrupt image file.")

    api_key = os.getenv("GEMINI_API_KEY") or API_KEY
    if not api_key:
        print("[PROCESS_RECEIPT ERROR] GEMINI_API_KEY is not configured")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gemini API Key is not configured on the server.")
    
    print(f"DEBUG: main.py process_receipt using API Key starting with: {api_key[:5]}...")
    
    try:
        # 1. Structured OCR Extraction
        extracted_data = extract_receipt_data(contents, api_key)
        
        # 2. Deterministic Tax Computation & Deductibility
        tax_metrics = verify_and_adjust_tax(extracted_data)
        
        # 3. If math discrepancy detected, re-examine image
        if not tax_metrics["is_math_valid"]:
            reexamined_data = reexamine_discrepancy(
                contents,
                api_key,
                subtotal_net=extracted_data.subtotal_net,
                total_tax_amount=extracted_data.total_tax_amount,
                total_gross_amount=extracted_data.total_gross_amount
            )
            reexamined_tax_metrics = verify_and_adjust_tax(reexamined_data)
            extracted_data = reexamined_data
            tax_metrics = reexamined_tax_metrics

        # 4. Save Receipt record to Database mapped to current_user
        db_receipt = Receipt(
            user_id=current_user.id,
            vendor_name=extracted_data.vendor_name,
            transaction_date=extracted_data.transaction_date,
            currency=extracted_data.currency,
            subtotal_net=extracted_data.subtotal_net,
            total_tax_amount=extracted_data.total_tax_amount,
            total_gross_amount=extracted_data.total_gross_amount,
            category=extracted_data.category.value if hasattr(extracted_data.category, 'value') else str(extracted_data.category),
            payment_method=extracted_data.payment_method,
            line_items=[item.model_dump() for item in extracted_data.line_items],
            tax_breakdown=[tb.model_dump() for tb in extracted_data.tax_breakdown],
            tax_analysis=tax_metrics,
            requires_manual_review=not tax_metrics["is_math_valid"]
        )
        db.add(db_receipt)
        db.commit()
        db.refresh(db_receipt)

        # 5. Save corresponding Ledger Transaction to Database mapped to current_user
        db_ledger = LedgerTransaction(
            user_id=current_user.id,
            receipt_id=db_receipt.id,
            transaction_date=extracted_data.transaction_date,
            vendor=extracted_data.vendor_name,
            amount=extracted_data.total_gross_amount,
            tax=extracted_data.total_tax_amount,
            category=extracted_data.category.value if hasattr(extracted_data.category, 'value') else str(extracted_data.category),
            status="Matched" if tax_metrics["is_math_valid"] else "Review Needed",
            confidence=98.0 if tax_metrics["is_math_valid"] else 85.0
        )
        db.add(db_ledger)
        db.commit()

        print(f"[PROCESS_RECEIPT SUCCESS] Receipt ID={db_receipt.id} processed successfully")
        return {
            "status": "success",
            "receipt_id": db_receipt.id,
            "extracted_data": extracted_data.model_dump(),
            "tax_analysis": tax_metrics,
            "requires_manual_review": not tax_metrics["is_math_valid"]
        }
        
    except (APIError, GoogleAPIError) as e:
        db.rollback()
        err_msg = str(e)
        print(f"\n[PROCESS_RECEIPT 502 EXCEPTION] AI Generation/API Error: {type(e).__name__}: {err_msg}")
        logger.error("AI Generation Error in process-receipt: %s", e, exc_info=True)
        err_lower = err_msg.lower()
        if "not found" in err_lower or "404" in err_lower:
            detail = f"AI vision model not found or deprecated: {err_msg}"
        elif "quota" in err_lower or "resource_exhausted" in err_lower or "429" in err_lower:
            detail = f"AI API quota or rate limit exceeded: {err_msg}"
        elif "key" in err_lower or "unauthorized" in err_lower or "permission" in err_lower or "401" in err_lower or "403" in err_lower:
            detail = f"AI API key or authentication failure: {err_msg}"
        elif "safety" in err_lower or "blocked" in err_lower:
            detail = f"AI vision processing blocked by content safety filters: {err_msg}"
        else:
            detail = f"AI vision service failed: {err_msg}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    except (json.JSONDecodeError, ValidationError) as e:
        db.rollback()
        print(f"\n[PROCESS_RECEIPT 502 EXCEPTION] AI Output Parsing Error: {type(e).__name__}: {e}")
        logger.error("AI Output Parsing Error in process-receipt: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI vision service returned an unparseable response format: {e}")
    except SQLAlchemyError as e:
        db.rollback()
        print(f"\n[PROCESS_RECEIPT 503 EXCEPTION] Database Exception: {type(e).__name__}: {e}")
        logger.error("Database Exception in process-receipt: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database service temporarily unavailable.")
    except Exception as e:
        db.rollback()
        print(f"\n[PROCESS_RECEIPT ERROR] Unexpected Exception: {type(e).__name__}: {e}")
        logger.error("Unexpected Internal Error in process-receipt: %s", e, exc_info=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal error occurred while processing the receipt.")

@app.get("/api/v1/ledger")
async def get_ledger(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        transactions = db.query(LedgerTransaction).filter(LedgerTransaction.user_id == current_user.id).all()
        return [
            {
                "id": t.id,
                "Date": str(t.transaction_date),
                "Vendor": t.vendor,
                "Amount": t.amount,
                "Tax": t.tax,
                "Category": t.category,
                "Status": t.status,
                "Confidence": t.confidence
            }
            for t in transactions
        ]
    except SQLAlchemyError as e:
        logger.error("Database Exception in get_ledger: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database service temporarily unavailable.")
    except Exception as e:
        logger.error("Unexpected Error in get_ledger: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal error occurred while fetching ledger transactions.")

@app.get("/api/v1/receipts")
async def get_receipts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        receipts = db.query(Receipt).filter(Receipt.user_id == current_user.id).all()
        return [
            {
                "id": r.id,
                "extracted_data": {
                    "vendor_name": r.vendor_name,
                    "transaction_date": str(r.transaction_date),
                    "currency": r.currency,
                    "subtotal_net": r.subtotal_net,
                    "total_tax_amount": r.total_tax_amount,
                    "total_gross_amount": r.total_gross_amount,
                    "category": r.category,
                    "payment_method": r.payment_method,
                    "line_items": r.line_items,
                    "tax_breakdown": r.tax_breakdown
                },
                "tax_analysis": r.tax_analysis,
                "requires_manual_review": r.requires_manual_review
            }
            for r in receipts
        ]
    except SQLAlchemyError as e:
        logger.error("Database Exception in get_receipts: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database service temporarily unavailable.")
    except Exception as e:
        logger.error("Unexpected Error in get_receipts: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal error occurred while fetching receipts.")

@app.post("/api/v1/cfo-chat")
async def cfo_chat(
    request: CFORequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    api_key = API_KEY or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gemini API Key is not configured on the server.")
        
    try:
        db_receipts = db.query(Receipt).filter(Receipt.user_id == current_user.id).all()
        ledger = [
            {
                "Date": str(r.transaction_date),
                "Vendor": r.vendor_name,
                "Amount": r.total_gross_amount,
                "Tax": r.total_tax_amount,
                "Category": r.category,
                "PaymentMethod": r.payment_method,
                "RequiresReview": r.requires_manual_review
            }
            for r in db_receipts
        ]
            
        advice = get_cfo_advice(request.query, ledger, api_key)
        return {"advice": advice, "status": "success"}
    except (APIError, GoogleAPIError) as e:
        err_msg = str(e)
        logger.error("AI Generation Error in cfo-chat: %s", e, exc_info=True)
        err_lower = err_msg.lower()
        if "not found" in err_lower or "404" in err_lower:
            detail = f"CFO AI model not found or deprecated: {err_msg}"
        elif "quota" in err_lower or "429" in err_lower:
            detail = f"CFO AI API quota exceeded: {err_msg}"
        else:
            detail = f"CFO AI service failed: {err_msg}"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    except SQLAlchemyError as e:
        logger.error("Database Error in cfo-chat: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database service temporarily unavailable.")
    except Exception as e:
        logger.error("Unexpected Error in cfo-chat: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal error occurred while consulting the CFO assistant.")

@app.post("/api/v1/tax-report")
async def get_tax_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        db_receipts = db.query(Receipt).filter(Receipt.user_id == current_user.id).all()
        ledger_records = [
            {
                "extracted_data": {
                    "category": r.category,
                    "vendor_name": r.vendor_name,
                    "transaction_date": str(r.transaction_date)
                },
                "tax_analysis": r.tax_analysis or {
                    "gross_amount": r.total_gross_amount,
                    "total_tax": r.total_tax_amount,
                    "deductible_spend": r.total_gross_amount * (0.50 if r.category == "Meals & Entertainment" else 1.0),
                    "is_math_valid": not r.requires_manual_review
                }
            }
            for r in db_receipts
        ]
            
        report = generate_tax_report(ledger_records)
        return {"status": "success", "report": report}
    except SQLAlchemyError as e:
        logger.error("Database Error in tax-report: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database service temporarily unavailable.")
    except Exception as e:
        logger.error("Unexpected Error in tax-report: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An internal error occurred while generating the tax report.")

@app.post("/api/scan")
async def scan_receipt(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    res = await process_receipt(file, current_user=current_user, db=db)
    extracted = res["extracted_data"]
    extracted["tax_analysis"] = res["tax_analysis"]
    extracted["requires_manual_review"] = res["requires_manual_review"]
    extracted["receipt_id"] = res.get("receipt_id")
    return extracted
