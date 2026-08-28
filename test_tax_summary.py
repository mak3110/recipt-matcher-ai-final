from tax_summary import generate_tax_report

def test_generate_tax_report():
    sample_ledger = [
        {
            "extracted_data": {"category": "Meals & Entertainment"},
            "tax_analysis": {"gross_amount": 100.80, "total_tax": 6.40, "deductible_spend": 50.40, "is_math_valid": True}
        },
        {
            "extracted_data": {"category": "Software & Subscriptions"},
            "tax_analysis": {"gross_amount": 150.00, "total_tax": 0.00, "deductible_spend": 150.00, "is_math_valid": True}
        },
        {
            "extracted_data": {"category": "Office Supplies & Hardware"},
            "tax_analysis": {"gross_amount": 129.60, "total_tax": 9.60, "deductible_spend": 129.60, "is_math_valid": True}
        }
    ]
    
    report = generate_tax_report(sample_ledger)
    summary = report["summary"]
    
    assert summary["total_receipts_scanned"] == 3
    assert summary["total_gross_expenditure"] == 380.40
    assert summary["total_tax_paid"] == 16.00
    assert summary["total_claimable_deductions"] == 330.00
    assert summary["flagged_discrepancies"] == 0
    assert "Meals & Entertainment" in report["breakdown_by_category"]
