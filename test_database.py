import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import User, Receipt, LedgerTransaction
from schemas import ReceiptExtraction, LineItem, TaxBreakdown, TaxCategory
from tax_engine import verify_and_adjust_tax

# In-memory SQLite engine for unit tests
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_create_user_and_receipt(db_session):
    # 1. Create User
    user = User(email="testowner@business.com", name="Test Owner")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    assert user.id is not None

    # 2. Extract & verify receipt
    receipt_data = ReceiptExtraction(
        vendor_name="AWS Cloud Infrastructure",
        transaction_date=date(2026, 8, 10),
        currency="USD",
        subtotal_net=149.99,
        line_items=[LineItem(description="EC2 Compute Tier", quantity=1.0, unit_price=149.99, total_price=149.99)],
        tax_breakdown=[TaxBreakdown(tax_name="State Tax", tax_rate_percent=8.0, tax_amount=12.00)],
        total_tax_amount=12.00,
        total_gross_amount=161.99,
        category=TaxCategory.SOFTWARE,
        payment_method="Visa 5544"
    )
    tax_metrics = verify_and_adjust_tax(receipt_data)

    # 3. Save Receipt row
    db_receipt = Receipt(
        user_id=user.id,
        vendor_name=receipt_data.vendor_name,
        transaction_date=receipt_data.transaction_date,
        currency=receipt_data.currency,
        subtotal_net=receipt_data.subtotal_net,
        total_tax_amount=receipt_data.total_tax_amount,
        total_gross_amount=receipt_data.total_gross_amount,
        category=receipt_data.category.value,
        payment_method=receipt_data.payment_method,
        line_items=[i.model_dump() for i in receipt_data.line_items],
        tax_breakdown=[tb.model_dump() for tb in receipt_data.tax_breakdown],
        tax_analysis=tax_metrics,
        requires_manual_review=not tax_metrics["is_math_valid"]
    )
    db_session.add(db_receipt)
    db_session.commit()
    db_session.refresh(db_receipt)

    assert db_receipt.id is not None
    assert db_receipt.user_id == user.id

    # 4. Save Ledger Transaction row linked to receipt
    db_ledger = LedgerTransaction(
        user_id=user.id,
        receipt_id=db_receipt.id,
        transaction_date=receipt_data.transaction_date,
        vendor=receipt_data.vendor_name,
        amount=receipt_data.total_gross_amount,
        tax=receipt_data.total_tax_amount,
        category=receipt_data.category.value,
        status="Matched",
        confidence=98.0
    )
    db_session.add(db_ledger)
    db_session.commit()

    # 5. Query and verify relations
    fetched_user = db_session.query(User).filter(User.id == user.id).first()
    assert len(fetched_user.receipts) == 1
    assert fetched_user.receipts[0].vendor_name == "AWS Cloud Infrastructure"
    assert len(fetched_user.ledger_transactions) == 1
    assert fetched_user.ledger_transactions[0].amount == 161.99
