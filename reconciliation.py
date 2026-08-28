import datetime
from typing import Tuple, Dict, Any, Optional, List
from rapidfuzz import fuzz

def parse_date(date_input: Any) -> Optional[datetime.date]:
    if isinstance(date_input, datetime.date):
        return date_input
    if isinstance(date_input, str) and date_input not in ('N/A', '', 'None'):
        try:
            return datetime.datetime.strptime(date_input, "%Y-%m-%d").date()
        except ValueError:
            try:
                return datetime.datetime.fromisoformat(date_input).date()
            except ValueError:
                pass
    return None

def calculate_reconciliation_confidence(
    receipt_vendor: str,
    receipt_amount: float,
    receipt_date: Any,
    ledger_vendor: str,
    ledger_amount: float,
    ledger_date: Any
) -> float:
    """
    Calculates a reconciliation confidence score (0-100%) between an OCR receipt and a bank/ledger transaction.
    - Amount Match: Up to 50 points (Exact match = 50 pts, within 1% or $1.00 = 25 pts)
    - Vendor Match: Up to 30 points (Fuzzy match >= 80% using rapidfuzz token_sort_ratio)
    - Date Proximity: Up to 20 points (Within 3 days: 0 days = 20 pts, 1 day = 15 pts, 2 days = 10 pts, 3 days = 5 pts)
    """
    score = 0.0

    # 1. Amount Match (Max 50 points)
    try:
        r_amt = float(receipt_amount)
        l_amt = float(ledger_amount)
        amt_diff = abs(r_amt - l_amt)
        if amt_diff < 0.01:
            score += 50.0
        elif amt_diff <= 1.00 or (r_amt > 0 and (amt_diff / r_amt) <= 0.02):
            score += 25.0
    except (TypeError, ValueError):
        pass

    # 2. Vendor Similarity using rapidfuzz (Max 30 points if >= 80% match)
    v1 = str(receipt_vendor or "").strip().lower()
    v2 = str(ledger_vendor or "").strip().lower()
    if v1 and v2:
        similarity = fuzz.token_sort_ratio(v1, v2)
        if similarity >= 80:
            score += (similarity / 100.0) * 30.0

    # 3. Date Proximity Check (Max 20 points if within 3 days)
    r_date = parse_date(receipt_date)
    l_date = parse_date(ledger_date)
    if r_date and l_date:
        days_diff = abs((r_date - l_date).days)
        if days_diff == 0:
            score += 20.0
        elif days_diff == 1:
            score += 15.0
        elif days_diff == 2:
            score += 10.0
        elif days_diff == 3:
            score += 5.0

    return min(100.0, round(score, 1))

def find_best_reconciliation_match(
    receipt_vendor: str,
    receipt_amount: float,
    receipt_date: Any,
    pending_transactions: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], float, int]:
    """
    Evaluates list of pending ledger transactions and returns (best_match_txn, best_confidence_score, best_index).
    """
    best_match = None
    best_score = 0.0
    best_index = -1

    for idx, txn in enumerate(pending_transactions):
        txn_vendor = txn.get("Vendor") or txn.get("vendor") or txn.get("vendor_name") or ""
        txn_amount = txn.get("Amount") or txn.get("amount") or 0.0
        txn_date = txn.get("Date") or txn.get("date") or txn.get("transaction_date") or ""

        score = calculate_reconciliation_confidence(
            receipt_vendor=receipt_vendor,
            receipt_amount=receipt_amount,
            receipt_date=receipt_date,
            ledger_vendor=txn_vendor,
            ledger_amount=txn_amount,
            ledger_date=txn_date
        )
        if score > best_score:
            best_score = score
            best_match = txn
            best_index = idx

    return best_match, best_score, best_index
