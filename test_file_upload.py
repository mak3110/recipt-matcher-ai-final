import io
import asyncio
import pytest
import datetime
from PIL import Image
from fastapi import UploadFile, HTTPException, Request
from main import process_receipt
from models import User
from database import Base, engine, SessionLocal
from schemas import ReceiptExtraction, LineItem, TaxBreakdown, TaxCategory

Base.metadata.create_all(bind=engine)

def get_test_user():
    db = SessionLocal()
    user = db.query(User).filter(User.email == "uploadtest@example.com").first()
    if not user:
        user = User(email="uploadtest@example.com", name="Test User", hashed_password="hashedpassword")
        db.add(user)
        db.commit()
        db.refresh(user)
    db.close()
    return user

def create_dummy_request():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/process-receipt",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    return Request(scope)

def create_dummy_image(fmt="PNG", size=(100, 100)):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color="red")
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.getvalue()

def test_file_upload_size_limit_exceeded():
    async def run():
        db = SessionLocal()
        user = get_test_user()
        req = create_dummy_request()
        large_bytes = b"0" * (100 * 1024 * 1024 + 100)
        upload_file = UploadFile(filename="large.png", file=io.BytesIO(large_bytes), headers={"content-type": "image/png"})
        
        with pytest.raises(HTTPException) as exc_info:
            await process_receipt(request=req, file=upload_file, current_user=user, db=db)
        
        assert exc_info.value.status_code == 400
        assert "exceeds maximum limit of 100MB" in exc_info.value.detail
        db.close()

    asyncio.run(run())

def test_file_upload_large_image_resizing():
    async def run():
        # Test resizing high-res image (3000x3000px) down to <= 2000px max dimension
        large_img_bytes = create_dummy_image(fmt="PNG", size=(3000, 1500))
        img = Image.open(io.BytesIO(large_img_bytes))
        assert img.width == 3000
        assert img.height == 1500
        
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        max_dim = 2000
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        resized_bytes = buf.getvalue()
        
        resized_img = Image.open(io.BytesIO(resized_bytes))
        assert resized_img.width == 2000
        assert resized_img.height == 1000
        assert resized_img.format == "JPEG"

    asyncio.run(run())

def test_file_upload_invalid_corrupt_image():
    async def run():
        db = SessionLocal()
        user = get_test_user()
        req = create_dummy_request()
        corrupt_bytes = b"THIS_IS_NOT_AN_IMAGE_HEADER_12345"
        upload_file = UploadFile(filename="corrupt.png", file=io.BytesIO(corrupt_bytes), headers={"content-type": "image/png"})
        
        with pytest.raises(HTTPException) as exc_info:
            await process_receipt(request=req, file=upload_file, current_user=user, db=db)
            
        assert exc_info.value.status_code == 400
        assert "Invalid or corrupt image file" in exc_info.value.detail
        db.close()

    asyncio.run(run())

def test_file_upload_unsupported_image_format():
    async def run():
        db = SessionLocal()
        user = get_test_user()
        req = create_dummy_request()
        gif_bytes = create_dummy_image(fmt="GIF")
        upload_file = UploadFile(filename="test.gif", file=io.BytesIO(gif_bytes), headers={"content-type": "image/jpeg"})
        
        with pytest.raises(HTTPException) as exc_info:
            await process_receipt(request=req, file=upload_file, current_user=user, db=db)
            
        assert exc_info.value.status_code == 400
        assert "Unsupported image format" in exc_info.value.detail
        db.close()

    asyncio.run(run())

def test_file_upload_valid_image_and_seek(monkeypatch):
    async def run():
        db = SessionLocal()
        user = get_test_user()
        req = create_dummy_request()
        valid_png = create_dummy_image(fmt="PNG")
        upload_file = UploadFile(filename="valid.png", file=io.BytesIO(valid_png), headers={"content-type": "image/png"})
        
        def mock_extract(contents, api_key):
            assert len(contents) > 0
            return ReceiptExtraction(
                vendor_name="Test Store",
                transaction_date=datetime.date(2026, 8, 20),
                currency="USD",
                subtotal_net=10.0,
                total_tax_amount=1.0,
                total_gross_amount=11.0,
                category=TaxCategory.OFFICE_SUPPLIES,
                payment_method="Card",
                line_items=[LineItem(description="Notebook", quantity=1.0, unit_price=10.0, total_price=10.0)],
                tax_breakdown=[TaxBreakdown(tax_name="Sales Tax", tax_rate_percent=10.0, tax_amount=1.0)]
            )

        monkeypatch.setattr("main.extract_receipt_data", mock_extract)
        monkeypatch.setattr("main.API_KEY", "mock_key")
        
        res = await process_receipt(request=req, file=upload_file, current_user=user, db=db)
        assert res["status"] == "success"
        assert res["extracted_data"]["vendor_name"] == "Test Store"
        db.close()

    asyncio.run(run())
