import streamlit as st
import pandas as pd
import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from schemas import TaxCategory
from reconciliation import calculate_reconciliation_confidence, find_best_reconciliation_match
from tax_summary import generate_tax_report

# Load environment variables from api.env if it exists
load_dotenv("api.env")

# Backend URL configuration (checks BACKEND_URL env var, defaults to http://localhost:8000)
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
if "vercel.app" in BACKEND_URL:
    BACKEND_URL = "http://localhost:8000"

# Set page configuration with a modern layout
st.set_page_config(
    page_title="ReceiptMatcher AI Dashboard",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium CSS styling for modern visuals
st.markdown("""
<style>
    /* Responsive typography & layouts */
    h1 {
        font-size: 2.2rem !important;
        font-weight: 800 !important;
    }
    h2 {
        font-size: 1.6rem !important;
    }
    h3 {
        font-size: 1.3rem !important;
    }
    
    /* Premium Glassmorphic / Modern Light UI */
    .metric-container {
        background: rgba(255, 255, 255, 0.7);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        border-radius: 16px;
        padding: 20px;
        border: 1px solid rgba(226, 232, 240, 0.8);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.04), 0 4px 6px -2px rgba(0, 0, 0, 0.02);
        margin-bottom: 20px;
        transition: transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out;
    }
    .metric-container:hover {
        transform: translateY(-2px);
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.06), 0 10px 10px -5px rgba(0, 0, 0, 0.03);
    }
    .badge-matched {
        background-color: #d1fae5;
        color: #065f46;
        padding: 6px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 14px;
        display: inline-block;
        border: 1px solid #a7f3d0;
    }
    .badge-review {
        background-color: #fef3c7;
        color: #78350f;
        padding: 6px 12px;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 14px;
        display: inline-block;
        border: 1px solid #fde68a;
    }
    .card-title {
        color: #64748b;
        font-size: 14px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 5px;
    }
    .card-value {
        color: #0f172a;
        font-size: 28px;
        font-weight: 700;
    }
    /* Customize Streamlit elements */
    .stProgress > div > div > div > div {
        background-color: #3b82f6;
    }
    
    /* Mobile-specific adjustments */
    @media (max-width: 640px) {
        h1 {
            font-size: 1.5rem !important;
        }
        h2 {
            font-size: 1.25rem !important;
        }
        h3 {
            font-size: 1.1rem !important;
        }
        .metric-container {
            padding: 12px;
            margin-bottom: 12px;
            border-radius: 12px;
        }
        .card-value {
            font-size: 20px;
        }
        .card-title {
            font-size: 10px;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 5px;
        }
        .stTabs [data-baseweb="tab"] {
            padding-left: 6px;
            padding-right: 6px;
            font-size: 11px;
        }
    }
</style>
""", unsafe_allow_html=True)

# Initialize Auth State
if "token" not in st.session_state:
    st.session_state.token = None
if "user" not in st.session_state:
    st.session_state.user = None

def get_auth_headers():
    if st.session_state.token:
        return {"Authorization": f"Bearer {st.session_state.token}"}
    return {}

# Fetch persistent ledger records from backend database
def load_db_ledger():
    try:
        res = requests.get(f"{BACKEND_URL}/api/v1/ledger", headers=get_auth_headers(), timeout=3)
        if res.status_code == 200 and isinstance(res.json(), list) and len(res.json()) > 0:
            return res.json()
    except Exception:
        pass
    return [
        {"Date": "2026-07-10", "Vendor": "AWS Cloud Services", "Amount": 149.99, "Tax": 12.00, "Category": TaxCategory.SOFTWARE.value, "Status": "Matched", "Confidence": 98.0},
        {"Date": "2026-07-12", "Vendor": "Uber Trip LLC", "Amount": 24.50, "Tax": 1.50, "Category": TaxCategory.TRAVEL.value, "Status": "Matched", "Confidence": 95.0},
        {"Date": "2026-07-15", "Vendor": "Starbucks Coffee", "Amount": 18.20, "Tax": 1.20, "Category": TaxCategory.MEALS.value, "Status": "Matched", "Confidence": 91.0},
        {"Date": "2026-07-16", "Vendor": "Office Depot Store", "Amount": 45.00, "Tax": 3.60, "Category": TaxCategory.OFFICE_SUPPLIES.value, "Status": "Matched", "Confidence": 96.0},
    ]

# Initialize Session States
if "ledger" not in st.session_state:
    st.session_state.ledger = load_db_ledger()

if "pending_reconcile" not in st.session_state:
    st.session_state.pending_reconcile = [
        {"Date": "2026-07-18", "Vendor": "Pending Wire - AWS", "Amount": 125.50},
        {"Date": "2026-07-17", "Vendor": "Pending Visa - Uber", "Amount": 24.50},
        {"Date": "2026-07-16", "Vendor": "Pending ACH - Rent", "Amount": 250.00},
    ]

# Calculations for metrics
df_ledger = pd.DataFrame(st.session_state.ledger)
total_expenses = df_ledger["Amount"].sum()
matched_count = len(df_ledger[df_ledger["Status"] == "Matched"])
avg_confidence = df_ledger["Confidence"].mean()

# SIDEBAR: Branding, Quota & Export Features
with st.sidebar:
    st.image("https://img.icons8.com/color/96/000000/invoice.png", width=64)
    st.title("ReceiptMatcher AI")
    st.caption("Hyper-focused direct receipt reconciliation")
    
    st.markdown("---")
    st.markdown("### 🔐 Account Session")
    if st.session_state.token and st.session_state.user:
        st.success(f"👤 Logged in as **{st.session_state.user.get('email')}**")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.token = None
            st.session_state.user = None
            st.session_state.ledger = load_db_ledger()
            st.rerun()
    else:
        st.info("Currently using Demo Mode. Sign in to sync your receipts!")
        auth_tab1, auth_tab2 = st.tabs(["Login", "Sign Up"])
        
        with auth_tab1:
            login_email = st.text_input("Email", key="login_email")
            login_password = st.text_input("Password", type="password", key="login_pass")
            if st.button("Sign In", key="btn_login", use_container_width=True):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/login", json={"email": login_email, "password": login_password})
                    if res.status_code == 200:
                        data = res.json()
                        st.session_state.token = data.get("access_token")
                        st.session_state.user = data.get("user")
                        st.session_state.ledger = load_db_ledger()
                        st.success("Signed in successfully!")
                        st.rerun()
                    else:
                        try:
                            error_detail = res.json().get("detail", "Login failed")
                        except Exception:
                            error_detail = res.text
                        st.error(f"Backend error ({res.status_code}): {error_detail}")
                except Exception as e:
                    st.error(f"Login error: {e}")
                    
        with auth_tab2:
            signup_email = st.text_input("Email", key="signup_email")
            signup_password = st.text_input("Password", type="password", key="signup_pass")
            signup_name = st.text_input("Full Name", key="signup_name")
            if st.button("Create Account", key="btn_signup", use_container_width=True):
                try:
                    res = requests.post(f"{BACKEND_URL}/api/v1/signup", json={"email": signup_email, "password": signup_password, "name": signup_name})
                    if res.status_code == 200:
                        data = res.json()
                        st.session_state.token = data.get("access_token")
                        st.session_state.user = data.get("user")
                        st.session_state.ledger = load_db_ledger()
                        st.success("Account created successfully!")
                        st.rerun()
                    else:
                        try:
                            error_detail = res.json().get("detail", "Signup failed")
                        except Exception:
                            error_detail = res.text
                        st.error(f"Backend error ({res.status_code}): {error_detail}")
                except Exception as e:
                    st.error(f"Signup error: {e}")

    st.markdown("---")
    st.markdown("### 👑 Account Status")
    st.success("Premium Account Active")
    st.caption("Plan price: **$14.00/month**")
    
    # Monthly scans quota
    st.markdown("### 📊 Quota Utilization")
    scans_made = len(st.session_state.ledger)
    st.progress(min(scans_made / 100, 1.0))
    st.caption(f"Scans made: **{scans_made} / Unlimited**")
    
    st.markdown("---")
    st.markdown("### 💾 Premium Multi-Format Export")
    # CSV download
    csv_data = df_ledger.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Export Ledger to CSV",
        data=csv_data,
        file_name=f"ledger_export_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True
    )
    
    # Mock Excel download
    st.button("📥 Export Ledger to Excel (XLSX)", use_container_width=True)

# MAIN INTERFACE
st.title("📊 Receipt Reconcile Dashboard")
st.caption("Auto-extract layout metadata and match physical receipt invoices securely to your business ledger.")

# Top Metrics Row
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
with col_m1:
    st.markdown(f"""
    <div class="metric-container">
        <div class="card-title">Total Tracked Expenses</div>
        <div class="card-value">${total_expenses:.2f}</div>
    </div>
    """, unsafe_allow_html=True)
with col_m2:
    st.markdown(f"""
    <div class="metric-container">
        <div class="card-title">Reconciled Transactions</div>
        <div class="card-value">{matched_count}</div>
    </div>
    """, unsafe_allow_html=True)
with col_m3:
    st.markdown(f"""
    <div class="metric-container">
        <div class="card-title">Avg Parse Accuracy</div>
        <div class="card-value">{avg_confidence:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)
with col_m4:
    st.markdown(f"""
    <div class="metric-container">
        <div class="card-title">Pending Reconciliations</div>
        <div class="card-value">{len(st.session_state.pending_reconcile)}</div>
    </div>
    """, unsafe_allow_html=True)

# Main Navigation Tabs
tab_scan, tab_ledger, tab_insights, tab_cfo = st.tabs(["📷 Scan & Reconcile", "📋 Visual Ledger", "📈 Expense Insights", "💬 Virtual CFO Assistant"])

# Tab 1: Scan & Reconcile
with tab_scan:
    st.markdown("### Upload or Capture Receipt")
    
    col_input, col_preview = st.columns([1, 1])
    
    with col_input:
        input_type = st.radio("Choose input method:", ["Camera Capture", "File Upload"], horizontal=True)
        uploaded_file = None
        if input_type == "Camera Capture":
            uploaded_file = st.camera_input("Scan your paper receipt")
        else:
            uploaded_file = st.file_uploader("Upload receipt image", type=["png", "jpg", "jpeg", "webp"])
            
    with col_preview:
        if uploaded_file is not None:
            st.image(uploaded_file, caption="Receipt Preview", use_container_width=True)

    if uploaded_file is not None:
        st.markdown("---")
        st.markdown("### 🤖 Extraction & Matching Pipeline")
        
        with st.spinner("Processing invoice structure via Vision API..."):
            try:
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                response = requests.post(
                    f"{BACKEND_URL}/api/v1/process-receipt", 
                    files=files, 
                    headers=get_auth_headers(),
                    timeout=60
                )
                
                if response.status_code == 200:
                    data = response.json()
                    st.success("Analysis Complete!")
                    
                    # Extract nested extracted_data dictionary from response (with direct data fallback)
                    extracted = data.get('extracted_data', {}) if isinstance(data.get('extracted_data'), dict) and len(data.get('extracted_data')) > 0 else data
                    
                    vendor = extracted.get('vendor_name') or extracted.get('vendor', 'Unknown')
                    amount = float(extracted.get('total_gross_amount') if extracted.get('total_gross_amount') is not None else extracted.get('amount', 0.0))
                    date_val = str(extracted.get('transaction_date') or extracted.get('date', 'N/A'))
                    tax_val = float(extracted.get('total_tax_amount') if extracted.get('total_tax_amount') is not None else extracted.get('tax', 0.0))
                    net_val = float(extracted.get('subtotal_net') if extracted.get('subtotal_net') is not None else (amount - tax_val))
                    category = extracted.get('category', 'Uncategorized')
                    currency = extracted.get('currency', 'USD')
                    payment_method = extracted.get('payment_method', 'Unknown')
                    tax_breakdown = extracted.get('tax_breakdown', [])

                    # Display Extraction Metrics
                    col_ext1, col_ext2, col_ext3, col_ext4 = st.columns(4)
                    with col_ext1:
                        st.metric("Extracted Vendor", vendor)
                    with col_ext2:
                        st.metric("Gross Amount", f"{currency} ${amount:.2f}")
                    with col_ext3:
                        st.metric("Expense Date", date_val)
                    with col_ext4:
                        st.metric("Category", category)
                    
                    st.caption(f"**Subtotal (Net):** ${net_val:.2f} | **Total Tax:** ${tax_val:.2f} | **Payment:** {payment_method}")
                    
                    tax_analysis = data.get('tax_analysis')
                    if tax_analysis:
                        math_status = "🟢 Math Validated" if tax_analysis.get('is_math_valid') else "🔴 Discrepancy Found"
                        st.info(f"**Tax Engine Verification:** {math_status} | **Deductible Spend:** ${tax_analysis.get('deductible_spend', 0.0):.2f} ({tax_analysis.get('deductible_rate', '100%')}) | **Claimable Tax:** ${tax_analysis.get('claimable_tax', 0.0):.2f}")
                    
                    if tax_breakdown:
                        st.json({"Tax Breakdown": tax_breakdown})
                    
                    # Perform fuzzy reconciliation matching against pending bank ledger
                    best_match, best_score, best_idx = find_best_reconciliation_match(
                        receipt_vendor=vendor,
                        receipt_amount=amount,
                        receipt_date=date_val,
                        pending_transactions=st.session_state.pending_reconcile
                    )
                    
                    options = []
                    pending_map = {}
                    for idx, txn in enumerate(st.session_state.pending_reconcile):
                        score = calculate_reconciliation_confidence(
                            receipt_vendor=vendor,
                            receipt_amount=amount,
                            receipt_date=date_val,
                            ledger_vendor=txn["Vendor"],
                            ledger_amount=txn["Amount"],
                            ledger_date=txn["Date"]
                        )
                        opt_str = f"Pending Match - {txn['Date']} - {txn['Vendor']} - ${txn['Amount']:.2f} (Confidence: {score:.1f}%)"
                        options.append(opt_str)
                        pending_map[opt_str] = (idx, score)
                    
                    options.append("Add as manual ledger item")
                    
                    default_idx = len(options) - 1
                    if best_match and best_idx >= 0:
                        opt_str = f"Pending Match - {best_match['Date']} - {best_match['Vendor']} - ${best_match['Amount']:.2f} (Confidence: {best_score:.1f}%)"
                        if opt_str in pending_map:
                            default_idx = best_idx
                            
                    st.markdown("#### Match to Live Ledger Transaction")
                    selected_match = st.radio("Select transaction to reconcile:", options, index=default_idx)
                    
                    # Calculate selected transaction's confidence score and status
                    if selected_match in pending_map:
                        pending_idx, selected_confidence = pending_map[selected_match]
                        confidence = selected_confidence
                    else:
                        pending_idx = None
                        confidence = best_score if best_match else 0.0

                    if confidence >= 70.0:
                        status = "Matched"
                        badge_html = '<div class="badge-matched">🟢 Matched</div>'
                    else:
                        status = "Review Needed"
                        badge_html = '<div class="badge-review">🟡 Review Needed</div>'

                    # Output status and accuracy row
                    st.markdown(f"""
                    **Status Verification:** {badge_html} &nbsp;&nbsp;|&nbsp;&nbsp; **Match Confidence Score:** **{confidence:.1f}%**
                    """, unsafe_allow_html=True)
                    
                    if confidence < 70.0:
                        if not best_match:
                            st.warning("⚠️ No matching bank transaction found. This will be logged as a manual entry pending review.")
                        else:
                            st.warning(f"⚠️ Confidence score ({confidence:.1f}%) is below the 70% threshold. Status flagged as 'Review Needed'.")

                    # Reconciliation Action
                    if st.button("Complete Reconciliation", type="primary"):
                        if selected_match != "Add as manual ledger item" and pending_idx is not None:
                            st.session_state.pending_reconcile.pop(pending_idx)
                            
                        new_item = {
                            "Date": date_val if date_val != 'N/A' else datetime.now().strftime('%Y-%m-%d'),
                            "Vendor": vendor,
                            "Amount": amount,
                            "Tax": tax_val,
                            "Category": category,
                            "Status": status,
                            "Confidence": confidence
                        }
                        st.session_state.ledger.append(new_item)
                        st.balloons()
                        st.success(f"Reconciliation successfully logged with status '{status}' ({confidence:.1f}% confidence)!")
                        st.rerun()
                        
                else:
                    try:
                        error_detail = response.json().get("detail", "Unknown error")
                    except Exception:
                        error_detail = response.text
                    st.error(f"Backend error ({response.status_code}): {error_detail}")
            except Exception as e:
                st.error(f"Failed to connect to FastAPI backend: {e}")

# Tab 2: Visual Ledger Table
with tab_ledger:
    st.markdown("### Visual Transaction Ledger")
    
    # Filter Controls
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        categories = ["All"] + [cat.value for cat in TaxCategory]
        selected_cat = st.selectbox("Filter by Category", categories)
    with col_f2:
        search_query = st.text_input("🔍 Search Vendor or Status", "").strip().lower()
        
    # Apply filters
    filtered_df = df_ledger.copy()
    if selected_cat != "All":
        filtered_df = filtered_df[filtered_df["Category"] == selected_cat]
    if search_query:
        filtered_df = filtered_df[
            filtered_df["Vendor"].str.lower().str.contains(search_query) | 
            filtered_df["Status"].str.lower().str.contains(search_query)
        ]
        
    # Format and display
    formatted_df = filtered_df.copy()
    formatted_df["Amount"] = formatted_df["Amount"].map("${:,.2f}".format)
    formatted_df["Tax"] = formatted_df["Tax"].map("${:,.2f}".format)
    formatted_df["Confidence"] = formatted_df["Confidence"].map("{:.1f}%".format)
    
    st.dataframe(formatted_df, use_container_width=True, hide_index=True)
    
    # Re-display pending bank transactions below visual ledger
    st.markdown("---")
    st.markdown("### 🕒 Pending Ledger (Unreconciled Bank Transactions)")
    if len(st.session_state.pending_reconcile) > 0:
        df_pending = pd.DataFrame(st.session_state.pending_reconcile)
        df_pending["Amount"] = df_pending["Amount"].map("${:,.2f}".format)
        st.dataframe(df_pending, use_container_width=True, hide_index=True)
    else:
        st.info("All bank transactions successfully reconciled!")

# Tab 3: Insights & Analytics
with tab_insights:
    st.markdown("### Expense Insights & Analytics")
    
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.markdown("#### Expenses by Category")
        cat_data = df_ledger.groupby("Category")["Amount"].sum().reset_index()
        st.bar_chart(cat_data.set_index("Category"))
        
    with col_chart2:
        st.markdown("#### Reconciled Match Distribution")
        # Category breakdown listing
        for index, row in cat_data.iterrows():
            st.markdown(f"**{row['Category']}**: ${row['Amount']:.2f}")
            st.progress(float(row['Amount']) / float(total_expenses))

    st.markdown("---")
    st.markdown("### 📊 Accountant-Ready Schedule C / VAT Tax Report")
    
    # Fetch tax report from backend API (with local calculation fallback)
    tax_report = None
    try:
        res_tax = requests.post(f"{BACKEND_URL}/api/v1/tax-report", headers=get_auth_headers(), timeout=3)
        if res_tax.status_code == 200:
            tax_report = res_tax.json().get("report")
    except Exception:
        pass
        
    if not tax_report:
        formatted_records = []
        for item in st.session_state.ledger:
            formatted_records.append({
                "extracted_data": {"category": item.get("Category", "Uncategorized")},
                "tax_analysis": {
                    "gross_amount": float(item.get("Amount", 0.0)),
                    "total_tax": float(item.get("Tax", 0.0)),
                    "deductible_spend": float(item.get("Amount", 0.0)) * (0.50 if item.get("Category") in [TaxCategory.MEALS.value, "Meals & Entertainment", "Meals"] else 1.0),
                    "is_math_valid": True
                }
            })
        tax_report = generate_tax_report(formatted_records)

    sum_data = tax_report["summary"]
    
    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    with col_r1:
        st.metric("Total Receipts Scanned", sum_data["total_receipts_scanned"])
    with col_r2:
        st.metric("Gross Expenditure", f"${sum_data['total_gross_expenditure']:.2f}")
    with col_r3:
        st.metric("Tax Paid", f"${sum_data['total_tax_paid']:.2f}")
    with col_r4:
        st.metric("Claimable Deductions", f"${sum_data['total_claimable_deductions']:.2f}")
        
    st.markdown("#### Category Tax Breakdown")
    st.json(tax_report["breakdown_by_category"])

# Tab 4: Virtual CFO Assistant
with tab_cfo:
    st.markdown("### 💬 Virtual CFO & Tax Advisor")
    st.caption("Ask tax deductibility rules, check duplicate charges, or optimize tax savings based on your parsed receipt database.")
    
    if "cfo_chat_history" not in st.session_state:
        st.session_state.cfo_chat_history = []
        
    for msg in st.session_state.cfo_chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    cfo_prompt = st.chat_input("Ask your Virtual CFO (e.g. How much tax deduction can I claim for my meal receipts?)")
    if cfo_prompt:
        st.session_state.cfo_chat_history.append({"role": "user", "content": cfo_prompt})
        with st.chat_message("user"):
            st.markdown(cfo_prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Consulting Virtual CFO..."):
                try:
                    payload = {"query": cfo_prompt}
                    res = requests.post(f"{BACKEND_URL}/api/v1/cfo-chat", json=payload, headers=get_auth_headers())
                    if res.status_code == 200:
                        ans = res.json().get("advice", "")
                        st.markdown(ans)
                        st.session_state.cfo_chat_history.append({"role": "assistant", "content": ans})
                    else:
                        try:
                            error_detail = res.json().get("detail", "Unknown error")
                        except Exception:
                            error_detail = res.text
                        st.error(f"Backend error ({res.status_code}): {error_detail}")
                except Exception as e:
                    st.error(f"Connection error: {e}")

