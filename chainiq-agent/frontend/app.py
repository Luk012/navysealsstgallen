import streamlit as st
import httpx
import plotly.graph_objects as go
import json
import time

API_BASE = "http://localhost:8000/api"

st.set_page_config(
    page_title="ChainIQ Sourcing Agent",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: linear-gradient(135deg, #1a1f2e 0%, #252b3b 100%);
        border: 1px solid #333;
        border-radius: 12px;
        padding: 16px;
        margin: 4px 0;
    }
    .status-pass { color: #00d97e; font-weight: bold; }
    .status-fail { color: #e63757; font-weight: bold; }
    .status-warn { color: #f6c343; font-weight: bold; }
    .supplier-card {
        background: #1a1f2e;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
    }
    .rank-badge {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        display: inline-block;
    }
    .escalation-card {
        background: #2d1b1b;
        border: 1px solid #e63757;
        border-radius: 8px;
        padding: 12px;
        margin: 8px 0;
    }
    .commit-entry {
        border-left: 3px solid #6366f1;
        padding-left: 12px;
        margin: 8px 0;
    }
</style>
""", unsafe_allow_html=True)


def fetch_requests(page=1, page_size=20, category=None, country=None, scenario_tag=None, search=None):
    params = {"page": page, "page_size": page_size}
    if category: params["category"] = category
    if country: params["country"] = country
    if scenario_tag: params["scenario_tag"] = scenario_tag
    if search: params["search"] = search
    try:
        r = httpx.get(f"{API_BASE}/requests", params=params, timeout=10)
        return r.json()
    except Exception:
        return {"total": 0, "requests": []}


def process_request(request_id):
    try:
        r = httpx.post(f"{API_BASE}/process/{request_id}", timeout=120)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_result(request_id):
    try:
        r = httpx.get(f"{API_BASE}/results/{request_id}", timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


# ── Sidebar ──
with st.sidebar:
    st.markdown("## ChainIQ Sourcing Agent")
    st.markdown("---")

    # Filters
    st.markdown("### Filters")
    search = st.text_input("Search", placeholder="Request ID or keyword")
    category_filter = st.selectbox("Category", ["All", "IT", "Facilities", "Professional Services", "Marketing"])
    scenario_filter = st.selectbox("Scenario", [
        "All", "standard", "threshold", "lead_time", "missing_info",
        "contradictory", "restricted", "multilingual", "capacity", "multi_country"
    ])

    cat = category_filter if category_filter != "All" else None
    scen = scenario_filter if scenario_filter != "All" else None

    data = fetch_requests(page_size=304, category=cat, scenario_tag=scen, search=search or None)
    requests_list = data.get("requests", [])
    total = data.get("total", 0)

    st.markdown(f"**{total} requests found**")
    st.markdown("---")

    # Request list
    selected_id = None
    for req in requests_list[:50]:  # Show first 50
        rid = req["request_id"]
        tags = req.get("scenario_tags", [])
        cat_label = req.get("category_l1", "")[:3]
        country = req.get("country", "")

        tag_colors = {
            "standard": "🟢", "threshold": "🟡", "lead_time": "🔴",
            "missing_info": "🟠", "contradictory": "🔴", "restricted": "🔴",
            "multilingual": "🔵", "capacity": "🟡", "multi_country": "🟣"
        }
        tag_icons = " ".join(tag_colors.get(t, "") for t in tags)

        if st.button(f"{rid} | {cat_label} | {country} {tag_icons}", key=rid, use_container_width=True):
            st.session_state["selected_request"] = rid

    selected_id = st.session_state.get("selected_request")


# ── Main Area ──
if not selected_id:
    st.markdown("# ChainIQ Sourcing Agent")
    st.markdown("### Audit-Ready Autonomous Procurement Sourcing")
    st.markdown("Select a request from the sidebar to begin analysis.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Requests", total)
    with col2:
        it_count = len([r for r in requests_list if r.get("category_l1") == "IT"])
        st.metric("IT Requests", it_count)
    with col3:
        edge_count = len([r for r in requests_list if any(t in r.get("scenario_tags", []) for t in ["contradictory", "restricted", "threshold"])])
        st.metric("Edge Cases", edge_count)
    with col4:
        multi_count = len([r for r in requests_list if "multilingual" in r.get("scenario_tags", [])])
        st.metric("Multilingual", multi_count)
else:
    # Fetch request details
    try:
        req_detail = httpx.get(f"{API_BASE}/requests/{selected_id}", timeout=10).json()
    except Exception:
        st.error("Failed to fetch request details")
        st.stop()

    st.markdown(f"# {selected_id}")

    # Request overview
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"**Category:** {req_detail.get('category_l1', '')} > {req_detail.get('category_l2', '')}")
    with col2:
        budget = req_detail.get("budget_amount")
        currency = req_detail.get("currency", "")
        st.markdown(f"**Budget:** {currency} {budget:,.2f}" if budget else "**Budget:** Not specified")
    with col3:
        st.markdown(f"**Country:** {req_detail.get('country', '')}")
    with col4:
        tags = req_detail.get("scenario_tags", [])
        st.markdown(f"**Tags:** {', '.join(tags)}")

    # Original request text
    with st.expander("Original Request Text", expanded=True):
        st.markdown(f"> {req_detail.get('request_text', 'N/A')}")

    # Process button
    col_btn, col_status = st.columns([1, 3])
    with col_btn:
        process_btn = st.button("Process Request", type="primary", use_container_width=True)

    # Check for cached result
    cached = get_result(selected_id)

    if process_btn:
        with st.spinner("Processing through 4-stage pipeline..."):
            progress = st.progress(0)
            status = st.empty()

            status.markdown("**Stage 1:** Intake & Extraction...")
            progress.progress(10)

            result = process_request(selected_id)

            if "error" in result:
                st.error(f"Processing failed: {result['error']}")
                st.stop()

            progress.progress(100)
            status.markdown("**Complete!**")
            time.sleep(0.5)
            progress.empty()
            status.empty()

        cached = result

    if cached:
        _render_results(cached) if callable(globals().get("_render_results")) else None

        # Results tabs
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "Interpretation", "Policy", "Suppliers", "Recommendation", "Escalations", "Audit Trail"
        ])

        with tab1:
            _render_interpretation(cached)

        with tab2:
            _render_policy(cached)

        with tab3:
            _render_suppliers(cached)

        with tab4:
            _render_recommendation(cached)

        with tab5:
            _render_escalations(cached)

        with tab6:
            _render_audit_trail(cached)


def _render_interpretation(result):
    interp = result.get("request_interpretation", {})
    validation = result.get("validation", {})

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Extracted Fields")
        for key, value in interp.items():
            if value is not None:
                st.markdown(f"**{key.replace('_', ' ').title()}:** {value}")

    with col2:
        st.markdown("### Validation Issues")
        issues = validation.get("issues_detected", [])
        if not issues:
            st.success("No validation issues detected")
        for issue in issues:
            severity = issue.get("severity", "medium")
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
            st.markdown(f"{icon} **{issue.get('issue_id', '')}** [{severity.upper()}]: {issue.get('type', '')}")
            st.markdown(f"  {issue.get('description', '')}")
            if issue.get("action_required"):
                st.markdown(f"  *Action:* {issue['action_required']}")


def _render_policy(result):
    policy = result.get("policy_evaluation", {})

    # Threshold
    threshold = policy.get("approval_threshold", {})
    if threshold:
        st.markdown("### Approval Threshold")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Threshold Tier", threshold.get("applicable_threshold", "N/A"))
        with col2:
            st.metric("Quotes Required", threshold.get("quotes_required", "N/A"))
        with col3:
            st.metric("Deviation Approval", threshold.get("deviation_approval", "N/A"))
        if threshold.get("basis"):
            st.info(threshold["basis"])

    # Preferred supplier
    pref = policy.get("preferred_supplier", {})
    if pref:
        st.markdown("### Preferred Supplier Analysis")
        st.markdown(f"**Supplier:** {pref.get('supplier_name', 'N/A')}")
        col1, col2, col3 = st.columns(3)
        with col1:
            is_pref = pref.get("is_preferred", False)
            st.markdown(f"Preferred: {'✅' if is_pref else '❌'}")
        with col2:
            is_rest = pref.get("is_restricted", False)
            st.markdown(f"Restricted: {'🔴 Yes' if is_rest else '✅ No'}")
        with col3:
            covers = pref.get("covers_delivery", False)
            st.markdown(f"Covers Delivery: {'✅' if covers else '❌'}")

    # Category rules
    cat_rules = policy.get("category_rules_applied", [])
    if cat_rules:
        st.markdown("### Category Rules")
        for rule in cat_rules:
            applies = rule.get("applies", False)
            st.markdown(f"{'✅' if applies else '⬜'} **{rule.get('rule_id', '')}**: {rule.get('note', '')}")

    # Geography rules
    geo_rules = policy.get("geography_rules_applied", [])
    if geo_rules:
        st.markdown("### Geography Rules")
        for rule in geo_rules:
            applies = rule.get("applies", False)
            st.markdown(f"{'✅' if applies else '⬜'} **{rule.get('rule_id', '')}**: {rule.get('note', '')}")


def _render_suppliers(result):
    shortlist = result.get("supplier_shortlist", [])
    excluded = result.get("suppliers_excluded", [])

    if shortlist:
        st.markdown("### Ranked Supplier Comparison")

        # Radar chart for top suppliers
        if len(shortlist) >= 2:
            categories_radar = ["Price", "Lead Time", "Quality", "Risk (inv)", "ESG"]
            fig = go.Figure()

            for s in shortlist[:3]:
                # Normalize scores for radar
                max_price = max(e.get("total_price", 1) for e in shortlist) or 1
                price_score = 100 * (1 - s.get("total_price", 0) / max_price) if max_price else 50
                lead_score = 100 * (1 - min(s.get("standard_lead_time_days", 30), 60) / 60)
                quality = s.get("quality_score", 50)
                risk_inv = 100 - s.get("risk_score", 50)
                esg = s.get("esg_score", 50)

                fig.add_trace(go.Scatterpolar(
                    r=[price_score, lead_score, quality, risk_inv, esg],
                    theta=categories_radar,
                    fill="toself",
                    name=f"#{s['rank']} {s['supplier_name']}",
                ))

            fig.update_layout(
                polar=dict(bgcolor="#1a1f2e", radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=True,
                paper_bgcolor="#0e1117",
                font=dict(color="white"),
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)

        # Detailed supplier cards
        for s in shortlist:
            rank = s.get("rank", 0)
            rank_color = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

            st.markdown(f"### {rank_color} {s.get('supplier_name', '')}")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Price", f"{s.get('currency', '')} {s.get('total_price', 0):,.2f}")
            with col2:
                st.metric("Unit Price", f"{s.get('currency', '')} {s.get('unit_price', 0):,.2f}")
            with col3:
                st.metric("Lead Time (std)", f"{s.get('standard_lead_time_days', 'N/A')}d")
            with col4:
                st.metric("Lead Time (exp)", f"{s.get('expedited_lead_time_days', 'N/A')}d")

            col5, col6, col7, col8 = st.columns(4)
            with col5:
                st.metric("Quality", s.get("quality_score", "N/A"))
            with col6:
                st.metric("Risk", s.get("risk_score", "N/A"))
            with col7:
                st.metric("ESG", s.get("esg_score", "N/A"))
            with col8:
                labels = []
                if s.get("preferred"): labels.append("Preferred")
                if s.get("incumbent"): labels.append("Incumbent")
                st.markdown(" ".join(f"`{l}`" for l in labels) if labels else "")

            if s.get("recommendation_note"):
                st.info(s["recommendation_note"])

            st.markdown("---")

    if excluded:
        st.markdown("### Excluded Suppliers")
        for s in excluded:
            st.markdown(f"❌ **{s.get('supplier_name', '')}** ({s.get('supplier_id', '')}): {s.get('reason', '')}")


def _render_recommendation(result):
    rec = result.get("recommendation", {})
    branch = result.get("branch", "A")
    relaxations = result.get("relaxations", [])

    status = rec.get("status", "")
    if status == "proceed":
        st.success(f"**Status: Can Proceed**")
    elif status == "cannot_proceed":
        st.error(f"**Status: Cannot Proceed**")
    elif status == "requires_relaxation":
        st.warning(f"**Status: Requires Constraint Relaxation**")

    st.markdown(f"**Branch:** {'A (viable options exist)' if branch == 'A' else 'B (constraint relaxation needed)'}")

    if rec.get("reason"):
        st.markdown(f"**Reason:** {rec['reason']}")

    if rec.get("preferred_supplier_if_resolved"):
        st.markdown(f"**Recommended Supplier:** {rec['preferred_supplier_if_resolved']}")
        st.markdown(f"**Rationale:** {rec.get('preferred_supplier_rationale', '')}")

    if rec.get("minimum_budget_required"):
        st.metric("Minimum Budget Required", f"{rec.get('minimum_budget_currency', '')} {rec['minimum_budget_required']:,.2f}")

    # Branch B relaxations
    if relaxations:
        st.markdown("### Constraint Relaxations Applied")
        for r in relaxations:
            st.markdown(f"⚖️ **{r.get('constraint', '')}** ({r.get('weight_class', '')})")
            st.markdown(f"  {r.get('description', '')}")
            st.markdown(f"  *Suppliers unlocked:* {r.get('suppliers_unlocked', 0)}")


def _render_escalations(result):
    escalations = result.get("escalations", [])

    if not escalations:
        st.success("No escalations required")
        return

    for esc in escalations:
        blocking = esc.get("blocking", False)
        icon = "🔴" if blocking else "🟡"

        st.markdown(f"""
{icon} **{esc.get('escalation_id', '')}** — Rule: {esc.get('rule', '')}

**Trigger:** {esc.get('trigger', '')}

**Escalate To:** {esc.get('escalate_to', '')}

**Blocking:** {'Yes' if blocking else 'No'}

---
""")


def _render_audit_trail(result):
    audit = result.get("audit_trail", {})

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Policies Checked")
        for p in audit.get("policies_checked", []):
            st.markdown(f"- `{p}`")

        st.markdown("### Data Sources")
        for ds in audit.get("data_sources_used", []):
            st.markdown(f"- {ds}")

    with col2:
        st.markdown("### Suppliers Evaluated")
        for sid in audit.get("supplier_ids_evaluated", []):
            st.markdown(f"- `{sid}`")

        if audit.get("historical_awards_consulted"):
            st.markdown("### Historical Awards")
            st.info(audit.get("historical_award_note", "Consulted"))

    # Commit log
    commits = audit.get("commit_log", [])
    if commits:
        st.markdown("### Commit Log (Audit Trail)")
        for c in commits:
            status_icon = "✅" if c.get("approval_status") == "approved" else "❌"
            st.markdown(f"""
<div class="commit-entry">
{status_icon} <strong>{c.get('commit_id', '')}</strong> | Stage: {c.get('stage', '')} | Iteration: {c.get('iteration', '')}

<strong>Field:</strong> <code>{c.get('field_path', '')}</code>

<strong>Change:</strong> {c.get('old_value', 'null')} → {c.get('new_value', 'null')}

<strong>Justification:</strong> {c.get('justification', '')}

<strong>Approval:</strong> {c.get('approval_rationale', '')}
</div>
""", unsafe_allow_html=True)

    # Raw PRS (collapsible)
    prs = result.get("prs", {})
    if prs:
        with st.expander("Raw PRS (JSON)"):
            st.json(prs)

    # Full result JSON
    with st.expander("Full Result (JSON)"):
        st.json(result)
