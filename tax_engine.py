from schemas import ReceiptExtraction, TaxCategory
from typing import Dict, Any

def verify_and_adjust_tax(receipt: ReceiptExtraction) -> Dict[str, Any]:
    calculated_total = round(receipt.subtotal_net + receipt.total_tax_amount, 2)
    reported_total = round(receipt.total_gross_amount, 2)
    
    # Calculate math discrepancy
    discrepancy = abs(calculated_total - reported_total)
    math_valid = discrepancy <= 0.05  # Allow minor rounding drift
    
    # Apply category-specific deductibility rules (e.g., US 50% Meals rule)
    deductible_percentage = 1.0
    if receipt.category == TaxCategory.MEALS or (isinstance(receipt.category, str) and receipt.category == TaxCategory.MEALS.value):
        deductible_percentage = 0.50  # US IRS Schedule C standard limit for Meals & Entertainment
    
    deductible_amount = round(receipt.total_gross_amount * deductible_percentage, 2)
    claimable_tax = round(receipt.total_tax_amount * deductible_percentage, 2)
    
    return {
        "is_math_valid": math_valid,
        "discrepancy": discrepancy,
        "gross_amount": receipt.total_gross_amount,
        "net_amount": receipt.subtotal_net,
        "total_tax": receipt.total_tax_amount,
        "deductible_spend": deductible_amount,
        "claimable_tax": claimable_tax,
        "deductible_rate": f"{int(deductible_percentage * 100)}%"
    }
