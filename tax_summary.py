from typing import List, Dict, Any
from collections import defaultdict

def generate_tax_report(ledger_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregates all receipts into Schedule C / VAT tax categories."""
    category_summary = defaultdict(lambda: {"gross_spend": 0.0, "deductible_spend": 0.0, "tax_paid": 0.0, "count": 0})
    
    total_gross = 0.0
    total_tax = 0.0
    total_deductible = 0.0
    discrepancy_count = 0

    for item in ledger_records:
        extracted = item.get("extracted_data", {})
        analysis = item.get("tax_analysis", {})
        
        category = extracted.get("category", "Uncategorized")
        gross = analysis.get("gross_amount", 0.0)
        tax = analysis.get("total_tax", 0.0)
        deductible = analysis.get("deductible_spend", 0.0)
        
        category_summary[category]["gross_spend"] = round(category_summary[category]["gross_spend"] + gross, 2)
        category_summary[category]["deductible_spend"] = round(category_summary[category]["deductible_spend"] + deductible, 2)
        category_summary[category]["tax_paid"] = round(category_summary[category]["tax_paid"] + tax, 2)
        category_summary[category]["count"] += 1
        
        total_gross += gross
        total_tax += tax
        total_deductible += deductible
        
        if not analysis.get("is_math_valid", True):
            discrepancy_count += 1

    return {
        "summary": {
            "total_receipts_scanned": len(ledger_records),
            "total_gross_expenditure": round(total_gross, 2),
            "total_tax_paid": round(total_tax, 2),
            "total_claimable_deductions": round(total_deductible, 2),
            "flagged_discrepancies": discrepancy_count
        },
        "breakdown_by_category": dict(category_summary)
    }
