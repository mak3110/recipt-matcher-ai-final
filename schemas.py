from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from enum import Enum

class TaxCategory(str, Enum):
    SOFTWARE = "Software & Subscriptions"
    TRAVEL = "Travel & Transportation"
    MEALS = "Meals & Entertainment"
    OFFICE_SUPPLIES = "Office Supplies & Hardware"
    ADVERTISING = "Advertising & Marketing"
    UTILITIES = "Utilities & Rent"
    UNCATEGORIZED = "Uncategorized"

class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = 1.0
    unit_price: Optional[float] = 0.0
    total_price: float

class TaxBreakdown(BaseModel):
    tax_name: str = Field(description="e.g., VAT 20%, Sales Tax, CGST, SGST")
    tax_rate_percent: Optional[float] = None
    tax_amount: float

class ReceiptExtraction(BaseModel):
    vendor_name: str
    transaction_date: date
    currency: str = Field(default="USD", min_length=3, max_length=3)
    subtotal_net: float = Field(description="Total before tax")
    line_items: List[LineItem] = Field(default_factory=list, description="Extracted individual items")
    tax_breakdown: List[TaxBreakdown] = Field(default_factory=list)
    total_tax_amount: float
    total_gross_amount: float = Field(description="Final paid amount (Net + Tax)")
    category: TaxCategory
    payment_method: Optional[str] = Field(default="Unknown", description="e.g., Visa 1234, Cash")

class CFORequest(BaseModel):
    query: str
    ledger: List[dict] = Field(default_factory=list)

class UserCreate(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

# Alias for backwards compatibility if needed
ReceiptData = ReceiptExtraction


