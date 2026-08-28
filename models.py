from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    receipts = relationship("Receipt", back_populates="user", cascade="all, delete-orphan")
    ledger_transactions = relationship("LedgerTransaction", back_populates="user", cascade="all, delete-orphan")

class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    vendor_name = Column(String, nullable=False, index=True)
    transaction_date = Column(Date, nullable=False)
    currency = Column(String, default="USD")
    subtotal_net = Column(Float, nullable=False)
    total_tax_amount = Column(Float, nullable=False)
    total_gross_amount = Column(Float, nullable=False)
    category = Column(String, nullable=False, index=True)
    payment_method = Column(String, default="Unknown")
    
    line_items = Column(JSON, default=list)
    tax_breakdown = Column(JSON, default=list)
    tax_analysis = Column(JSON, default=dict)
    requires_manual_review = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="receipts")
    ledger_transactions = relationship("LedgerTransaction", back_populates="receipt")

class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=True, index=True)
    
    transaction_date = Column(Date, nullable=False)
    vendor = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    tax = Column(Float, default=0.0)
    category = Column(String, nullable=False)
    status = Column(String, default="Matched")
    confidence = Column(Float, default=95.0)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="ledger_transactions")
    receipt = relationship("Receipt", back_populates="ledger_transactions")
