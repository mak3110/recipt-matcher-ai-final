import pytest
from schemas import ReceiptExtraction, LineItem, TaxBreakdown, TaxCategory
from tax_engine import verify_and_adjust_tax

@pytest.fixture
def test_cases():
    return {
        "restaurant_dual_tax": ReceiptExtraction(
            vendor_name="Bistro Deluxe Steakhouse",
            transaction_date="2026-08-18",
            currency="USD",
            subtotal_net=94.40,
            line_items=[
                LineItem(description="Ribeye Steak 12oz", quantity=2.0, unit_price=30.00, total_price=60.00),
                LineItem(description="18% Gratuity / Tip", quantity=1.0, unit_price=14.40, total_price=14.40)
            ],
            tax_breakdown=[
                TaxBreakdown(tax_name="State Sales Tax 6%", tax_rate_percent=6.0, tax_amount=4.80),
                TaxBreakdown(tax_name="Local Meals Tax 2%", tax_rate_percent=2.0, tax_amount=1.60)
            ],
            total_tax_amount=6.40,
            total_gross_amount=100.80,
            category=TaxCategory.MEALS
        ),
        "eu_saas_reverse_charge": ReceiptExtraction(
            vendor_name="CloudScale Global B.V.",
            transaction_date="2026-08-01",
            currency="EUR",
            subtotal_net=150.00,
            line_items=[LineItem(description="Cloud Node", quantity=1.0, unit_price=150.00, total_price=150.00)],
            tax_breakdown=[TaxBreakdown(tax_name="Reverse Charge VAT", tax_rate_percent=0.0, tax_amount=0.00)],
            total_tax_amount=0.00,
            total_gross_amount=150.00,
            category=TaxCategory.SOFTWARE
        )
    }

def test_meal_deductibility_50_percent(test_cases):
    receipt = test_cases["restaurant_dual_tax"]
    result = verify_and_adjust_tax(receipt)
    
    assert result["is_math_valid"] is True
    assert result["deductible_rate"] == "50%"
    assert result["deductible_spend"] == 50.40  # 50% of 100.80
    assert result["claimable_tax"] == 3.20      # 50% of 6.40

def test_reverse_charge_vat(test_cases):
    receipt = test_cases["eu_saas_reverse_charge"]
    result = verify_and_adjust_tax(receipt)
    
    assert result["is_math_valid"] is True
    assert result["deductible_spend"] == 150.00
    assert result["total_tax"] == 0.00
