import io
import asyncio
import pytest
from PIL import Image
from main import app
from database import Base, engine, SessionLocal
from models import User
from auth import create_access_token
from schemas import ReceiptExtraction, LineItem, TaxBreakdown, TaxCategory

Base.metadata.create_all(bind=engine)

def get_or_create_user(email):
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name="Rate Limit User", hashed_password="hashedpassword")
        db.add(user)
        db.commit()
        db.refresh(user)
    db.close()
    return user

def create_dummy_png_bytes():
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def build_multipart_payload():
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    file_bytes = create_dummy_png_bytes()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="receipt.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type

async def call_asgi_app_with_body(app_instance, path, body_bytes, headers=None):
    headers = headers or []
    scope = {
        'type': 'http',
        'method': 'POST',
        'path': path,
        'headers': headers,
        'query_string': b'',
        'client': ('127.0.0.1', 54321),
        'server': ('127.0.0.1', 8000),
    }

    status_code = None
    res_body = b""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {'type': 'http.request', 'body': body_bytes, 'more_body': False}
        return {'type': 'http.request', 'body': b'', 'more_body': False}
        
    async def send(message):
        nonlocal status_code, res_body
        if message['type'] == 'http.response.start':
            status_code = message['status']
        elif message['type'] == 'http.response.body':
            res_body += message.get('body', b'')

    await app_instance(scope, receive, send)
    return status_code, res_body.decode("utf-8")

def test_rate_limiter_5_per_minute_enforced(monkeypatch):
    async def run():
        # Mock OCR extraction to avoid calling external Gemini API
        import datetime
        def mock_extract(contents, api_key):
            return ReceiptExtraction(
                vendor_name="Rate Limit Store",
                transaction_date=datetime.date(2026, 8, 20),
                currency="USD",
                subtotal_net=10.0,
                total_tax_amount=1.0,
                total_gross_amount=11.0,
                category=TaxCategory.OFFICE_SUPPLIES,
                payment_method="Card",
                line_items=[LineItem(description="Item", quantity=1.0, unit_price=10.0, total_price=10.0)],
                tax_breakdown=[TaxBreakdown(tax_name="VAT", tax_rate_percent=10.0, tax_amount=1.0)]
            )
            
        monkeypatch.setattr("main.extract_receipt_data", mock_extract)
        monkeypatch.setattr("main.API_KEY", "mock_key")

        email = "ratelimit_user1@example.com"
        get_or_create_user(email)
        token = create_access_token(data={"sub": email})
        
        body_bytes, content_type = build_multipart_payload()
        auth_headers = [
            (b'authorization', f"Bearer {token}".encode("utf-8")),
            (b'content-type', content_type.encode("utf-8")),
            (b'content-length', str(len(body_bytes)).encode("utf-8")),
        ]
        
        # Dispatch 5 requests for user1
        for i in range(5):
            st, res = await call_asgi_app_with_body(app, "/api/v1/process-receipt", body_bytes, headers=auth_headers)
            assert st == 200, f"Request {i+1} failed with status {st}: {res}"

        # 6th request should hit 429 RateLimitExceeded
        st, res = await call_asgi_app_with_body(app, "/api/v1/process-receipt", body_bytes, headers=auth_headers)
        assert st == 429, f"6th request returned status {st}: {res}"
        assert "You have reached your scan limit. Please try again later." in res

    asyncio.run(run())

def test_rate_limiter_different_users_have_separate_buckets(monkeypatch):
    async def run():
        import datetime
        def mock_extract(contents, api_key):
            return ReceiptExtraction(
                vendor_name="Rate Limit Store",
                transaction_date=datetime.date(2026, 8, 20),
                currency="USD",
                subtotal_net=10.0,
                total_tax_amount=1.0,
                total_gross_amount=11.0,
                category=TaxCategory.OFFICE_SUPPLIES,
                payment_method="Card",
                line_items=[LineItem(description="Item", quantity=1.0, unit_price=10.0, total_price=10.0)],
                tax_breakdown=[TaxBreakdown(tax_name="VAT", tax_rate_percent=10.0, tax_amount=1.0)]
            )
            
        monkeypatch.setattr("main.extract_receipt_data", mock_extract)
        monkeypatch.setattr("main.API_KEY", "mock_key")

        email2 = "ratelimit_user2@example.com"
        get_or_create_user(email2)
        token2 = create_access_token(data={"sub": email2})
        
        body_bytes, content_type = build_multipart_payload()
        auth_headers2 = [
            (b'authorization', f"Bearer {token2}".encode("utf-8")),
            (b'content-type', content_type.encode("utf-8")),
            (b'content-length', str(len(body_bytes)).encode("utf-8")),
        ]
        
        # user2 should succeed because they have a separate rate limit bucket
        st, res = await call_asgi_app_with_body(app, "/api/v1/process-receipt", body_bytes, headers=auth_headers2)
        assert st == 200, f"Request for user2 failed with status {st}: {res}"

    asyncio.run(run())
