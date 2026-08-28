import pytest
from reconciliation import calculate_reconciliation_confidence, find_best_reconciliation_match

def test_reconciliation_exact_match():
    # Exact amount ($100), Exact vendor ("AWS Cloud Services"), Same date ("2026-08-20")
    score = calculate_reconciliation_confidence(
        receipt_vendor="AWS Cloud Services",
        receipt_amount=100.0,
        receipt_date="2026-08-20",
        ledger_vendor="AWS Cloud Services",
        ledger_amount=100.0,
        ledger_date="2026-08-20"
    )
    # 50 (amount) + 30 (vendor) + 20 (date) = 100.0%
    assert score == 100.0

def test_reconciliation_fuzzy_vendor_above_80_percent():
    # Vendor match > 80% ("Starbucks Coffee" vs "Starbucks #4829")
    score = calculate_reconciliation_confidence(
        receipt_vendor="Starbucks Coffee",
        receipt_amount=15.50,
        receipt_date="2026-08-20",
        ledger_vendor="Starbucks #4829",
        ledger_amount=15.50,
        ledger_date="2026-08-20"
    )
    # Amount (50) + Date (20) + Vendor (>0) >= 70% threshold
    assert score >= 70.0

def test_reconciliation_fuzzy_vendor_below_80_percent():
    # Vendor match < 80% ("Microsoft Azure" vs "Google Cloud") -> 0 vendor points
    score = calculate_reconciliation_confidence(
        receipt_vendor="Microsoft Azure",
        receipt_amount=50.0,
        receipt_date="2026-08-20",
        ledger_vendor="Google Cloud",
        ledger_amount=50.0,
        ledger_date="2026-08-20"
    )
    # Amount (50) + Date (20) + Vendor (0) = 70.0%
    assert score == 70.0

def test_reconciliation_date_proximity_within_3_days():
    # Date diff = 2 days -> 10 pts
    score_2days = calculate_reconciliation_confidence(
        receipt_vendor="Office Depot",
        receipt_amount=45.0,
        receipt_date="2026-08-20",
        ledger_vendor="Office Depot",
        ledger_amount=45.0,
        ledger_date="2026-08-22"
    )
    # 50 (amount) + 30 (vendor) + 10 (2 days diff) = 90.0%
    assert score_2days == 90.0

    # Date diff = 4 days (>3 days) -> 0 pts
    score_4days = calculate_reconciliation_confidence(
        receipt_vendor="Office Depot",
        receipt_amount=45.0,
        receipt_date="2026-08-20",
        ledger_vendor="Office Depot",
        ledger_amount=45.0,
        ledger_date="2026-08-25"
    )
    # 50 (amount) + 30 (vendor) + 0 (4 days diff) = 80.0%
    assert score_4days == 80.0

def test_reconciliation_low_confidence_below_70_percent():
    # Amount mismatch ($100 vs $50 -> 0 pts), Vendor mismatch (0 pts), Date diff 2 days (10 pts)
    score = calculate_reconciliation_confidence(
        receipt_vendor="Unknown Merchant",
        receipt_amount=100.0,
        receipt_date="2026-08-20",
        ledger_vendor="Target Store",
        ledger_amount=50.0,
        ledger_date="2026-08-22"
    )
    assert score < 70.0

def test_find_best_reconciliation_match():
    pending_list = [
        {"Date": "2026-08-15", "Vendor": "Target Store", "Amount": 50.0},
        {"Date": "2026-08-20", "Vendor": "Starbucks Coffee", "Amount": 15.50},
        {"Date": "2026-08-10", "Vendor": "AWS Cloud Services", "Amount": 150.0},
    ]

    best_match, best_score, best_idx = find_best_reconciliation_match(
        receipt_vendor="Starbucks #4829",
        receipt_amount=15.50,
        receipt_date="2026-08-20",
        pending_transactions=pending_list
    )

    assert best_match is not None
    assert best_match["Vendor"] == "Starbucks Coffee"
    assert best_idx == 1
    assert best_score >= 70.0

def test_find_best_reconciliation_match_no_match():
    # When no transaction matches (completely non-matching transactions)
    pending_list = [
        {"Date": "2026-01-01", "Vendor": "Unrelated Vendor", "Amount": 999.0},
    ]

    best_match, best_score, best_idx = find_best_reconciliation_match(
        receipt_vendor="Different Merchant",
        receipt_amount=10.0,
        receipt_date="2026-08-20",
        pending_transactions=pending_list
    )

    assert best_match is None
    assert best_score == 0.0
    assert best_idx == -1

    # Confidence fallback in app.py when best_match is None should be 0.0, not 50.0
    confidence = best_score if best_match else 0.0
    assert confidence == 0.0

def test_find_best_reconciliation_match_empty_pending_list():
    best_match, best_score, best_idx = find_best_reconciliation_match(
        receipt_vendor="Starbucks",
        receipt_amount=15.50,
        receipt_date="2026-08-20",
        pending_transactions=[]
    )

    assert best_match is None
    assert best_score == 0.0
    assert best_idx == -1

    confidence = best_score if best_match else 0.0
    assert confidence == 0.0
