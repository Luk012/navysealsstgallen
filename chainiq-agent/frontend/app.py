import streamlit as st
import httpx
import plotly.graph_objects as go
import json
import time

try:
    from websocket import WebSocketBadStatusException, create_connection
except Exception:
    create_connection = None
    WebSocketBadStatusException = Exception

API_BASE = "http://localhost:8000/api"
WS_BASE = API_BASE.replace("http://", "ws://").replace("https://", "wss://")
JOB_STATES = {"not_started", "queued", "processing", "failed", "completed"}

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
    .chat-container {
        max-width: 800px;
        margin: 0 auto;
        padding: 20px 0;
    }
    .chat-message {
        padding: 12px 16px;
        border-radius: 12px;
        margin: 8px 0;
        max-width: 85%;
    }
    .chat-user {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        margin-left: auto;
        text-align: right;
    }
    .chat-assistant {
        background: #1a1f2e;
        border: 1px solid #333;
        color: #e0e0e0;
    }
</style>
""", unsafe_allow_html=True)


def submit_new_request(text):
    """Submit a new purchase request via the API and return the created request."""
    try:
        r = httpx.post(f"{API_BASE}/requests", json={"request_text": text}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def fetch_requests(page=1, page_size=20, category=None, country=None, scenario_tag=None, search=None):
    params = {"page": page, "page_size": page_size}
    if category: params["category"] = category
    if country: params["country"] = country
    if scenario_tag: params["scenario_tag"] = scenario_tag
    if search: params["search"] = search
    try:
        r = httpx.get(f"{API_BASE}/requests", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"total": 0, "requests": []}


def _extract_error_message(response):
    try:
        payload = response.json()
    except Exception:
        return response.text or str(response)

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        error = payload.get("error")
        if isinstance(error, str):
            return error

    return str(payload)


def _is_job_status_payload(payload):
    return isinstance(payload, dict) and payload.get("status") in JOB_STATES and "request_interpretation" not in payload


def get_result(request_id):
    try:
        r = httpx.get(f"{API_BASE}/results/{request_id}", timeout=10)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"status": "failed", "error": _extract_error_message(e.response)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def start_processing(request_id):
    try:
        r = httpx.post(f"{API_BASE}/process/{request_id}", timeout=10)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"status": "failed", "error": _extract_error_message(e.response)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def _build_ws_url(request_id):
    return f"{WS_BASE}/ws/process/{request_id}"


def _ws_candidates(request_id):
    primary = _build_ws_url(request_id)
    candidates = [primary]

    if primary.startswith("ws://localhost:"):
        candidates.append(primary.replace("ws://localhost:", "ws://127.0.0.1:", 1))
    if primary.startswith("wss://localhost:"):
        candidates.append(primary.replace("wss://localhost:", "wss://127.0.0.1:", 1))

    return candidates


def _progress_from_event(event):
    status = event.get("status")
    if status == "queued":
        return 5
    if status == "processing":
        return 10
    if status in {"completed", "failed"}:
        return 100

    return {
        "stage1": 20,
        "stage2": 40,
        "stage3": 55,
        "stage4": 75,
        "branch_b": 85,
        "branch_a": 90,
        "near_miss": 92,
        "pipeline": 95,
    }.get(event.get("stage"), 15)


def _payload_for_display(event):
    payload = event.get("payload")
    if not payload:
        return None

    if event.get("event_type") == "final_result":
        return {
            "branch": payload.get("branch"),
            "recommendation": payload.get("recommendation"),
            "escalations": payload.get("escalations"),
        }

    return payload


def _format_live_event(event):
    timestamp = event.get("timestamp", "").replace("T", " ").split(".")[0]
    stage = (event.get("stage") or "pipeline").upper()
    parts = [f"[{timestamp}] {stage} | {event.get('event_type', 'event')}"]

    if event.get("status"):
        parts.append(event["status"].upper())
    if event.get("iteration") is not None:
        parts.append(f"iteration {event['iteration']}")

    header = " | ".join(parts)
    message = event.get("message", "")
    payload = _payload_for_display(event)

    if payload is None:
        return f"{header}\n{message}".strip()

    return f"{header}\n{message}\n{json.dumps(payload, indent=2, ensure_ascii=True)}".strip()


def _render_live_reasoning(log_placeholder, events):
    if not events:
        log_placeholder.caption("Live reasoning will appear here once processing starts.")
        return

    rendered = "\n\n".join(_format_live_event(event) for event in events[-30:])
    log_placeholder.code(rendered, language="text")


def _update_live_status(status_placeholder, progress_placeholder, event):
    progress_placeholder.progress(_progress_from_event(event))

    status = event.get("status")
    message = event.get("message", "Processing")

    if status == "failed":
        status_placeholder.error(message)
    elif status == "completed":
        status_placeholder.success(message)
    elif event.get("event_type") == "heartbeat":
        status_placeholder.info("Processing is still running")
    else:
        status_placeholder.info(message)


def _stream_processing(request_id, status_placeholder, progress_placeholder, log_placeholder):
    start_state = start_processing(request_id)
    if start_state.get("status") == "failed":
        return {
            "status": "failed",
            "error": start_state.get("error", "Failed to start processing."),
            "events": [],
            "result": None,
        }

    if create_connection is None:
        return {
            "status": "failed",
            "error": "websocket-client is not installed. Reinstall requirements and restart Streamlit.",
            "events": [],
            "result": None,
        }

    events = []
    final_result = None
    final_error = None
    final_status = None
    ws = None
    ws_error = None

    for candidate in _ws_candidates(request_id):
        try:
            ws = create_connection(candidate, timeout=10)
            ws.settimeout(60)
            break
        except Exception as e:
            ws_error = e

    if ws is None:
        return _poll_processing(
            request_id,
            status_placeholder,
            progress_placeholder,
            log_placeholder,
            ws_error,
        )

    try:
        while True:
            raw_event = ws.recv()
            if not raw_event:
                break

            event = json.loads(raw_event)
            if event.get("event_type") != "heartbeat":
                events.append(event)

            _update_live_status(status_placeholder, progress_placeholder, event)
            _render_live_reasoning(log_placeholder, events)

            if event.get("event_type") == "final_result":
                final_result = event.get("payload")

            if event.get("event_type") == "status" and event.get("status") in {"completed", "failed"}:
                final_status = event.get("status")
                if final_status == "failed":
                    final_error = (event.get("payload") or {}).get("error") or event.get("message")
                break
    except Exception as e:
        final_status = "failed"
        final_error = str(e)
    finally:
        try:
            ws.close()
        except Exception:
            pass

    return {
        "status": final_status or "failed",
        "error": final_error,
        "events": events,
        "result": final_result,
    }


def _poll_processing(request_id, status_placeholder, progress_placeholder, log_placeholder, ws_error=None):
    events = []

    if isinstance(ws_error, WebSocketBadStatusException):
        note = "WebSocket endpoint is unavailable on the running backend. Restart the backend to enable live reasoning; using status polling for now."
    elif ws_error is not None:
        note = f"WebSocket connection failed ({ws_error}). Using status polling for now."
    else:
        note = "Using status polling."

    status_placeholder.warning(note)
    progress_placeholder.progress(10)
    log_placeholder.code(note, language="text")

    for _ in range(120):
        result = get_result(request_id)
        if _is_job_status_payload(result):
            status = result.get("status")
            progress_placeholder.progress(15 if status == "queued" else 60 if status == "processing" else 100)
            if status == "failed":
                return {
                    "status": "failed",
                    "error": result.get("error", "Processing failed"),
                    "events": events,
                    "result": None,
                }
            if status == "completed":
                break
            time.sleep(2)
            continue

        return {
            "status": "completed",
            "error": None,
            "events": events,
            "result": result,
        }

    latest = get_result(request_id)
    if _is_job_status_payload(latest):
        return {
            "status": latest.get("status", "failed"),
            "error": latest.get("error", "Processing did not finish in time."),
            "events": events,
            "result": None,
        }

    return {
        "status": "completed",
        "error": None,
        "events": events,
        "result": latest,
    }


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


def _render_main_area(selected_id, requests_list, total):
    if not selected_id:
        st.markdown("# ChainIQ Sourcing Agent")
        st.markdown("### Audit-Ready Autonomous Procurement Sourcing")

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

        st.markdown("---")

        # ── Chat Interface for New Purchase Requests ──
        st.markdown("## New Purchase Request")
        st.markdown(
            "Describe what you need to purchase in plain language. "
            "Include details like category, quantity, budget, delivery country, and timeline."
        )

        # Initialize chat history in session state
        if "chat_messages" not in st.session_state:
            st.session_state["chat_messages"] = [
                {
                    "role": "assistant",
                    "content": (
                        "Welcome to ChainIQ! I'm your procurement sourcing assistant.\n\n"
                        "Tell me what you need to purchase and I'll find the best suppliers for you. "
                        "For example:\n\n"
                        '*"We need 200 consulting days of cybersecurity advisory for our offices in Germany and Switzerland. '
                        'Budget is around 300,000 EUR. We need this delivered by end of Q2."*\n\n'
                        "Type your purchase request below to get started."
                    ),
                }
            ]

        # Render chat history
        for msg in st.session_state["chat_messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input
        user_input = st.chat_input("Describe your purchase request...")

        if user_input:
            # Add user message to chat
            st.session_state["chat_messages"].append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)

            # Submit to backend
            with st.chat_message("assistant"):
                with st.spinner("Creating your purchase request..."):
                    result = submit_new_request(user_input)

                if "error" in result:
                    error_msg = f"Failed to create request: {result['error']}"
                    st.error(error_msg)
                    st.session_state["chat_messages"].append({"role": "assistant", "content": error_msg})
                else:
                    request_id = result["request_id"]
                    success_msg = (
                        f"Your purchase request has been created as **{request_id}**.\n\n"
                        f"**Summary:** {result.get('title', '')}\n\n"
                        "I'll now start the sourcing analysis — matching suppliers, checking policies, "
                        "and ranking the best options for you."
                    )
                    st.markdown(success_msg)
                    st.session_state["chat_messages"].append({"role": "assistant", "content": success_msg})

                    # Auto-select and navigate to the new request
                    st.session_state["selected_request"] = request_id
                    st.rerun()

        return

    try:
        req_detail = httpx.get(f"{API_BASE}/requests/{selected_id}", timeout=10).json()
    except Exception:
        st.error("Failed to fetch request details")
        st.stop()

    st.markdown(f"# {selected_id}")

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

    with st.expander("Original Request Text", expanded=True):
        st.markdown(f"> {req_detail.get('request_text', 'N/A')}")

    live_events_store = st.session_state.setdefault("live_events", {})
    stored_events = live_events_store.get(selected_id, [])
    result_state = get_result(selected_id)
    result_status = result_state.get("status") if _is_job_status_payload(result_state) else None
    is_processing = result_status in {"queued", "processing"}

    col_btn, col_watch, col_status = st.columns([1, 1, 2])
    with col_btn:
        process_btn = st.button(
            "Process Request",
            type="primary",
            use_container_width=True,
            disabled=is_processing,
        )
    with col_watch:
        watch_btn = st.button(
            "Watch Live",
            use_container_width=True,
            disabled=not is_processing,
        )
    with col_status:
        live_status = st.empty()

    st.markdown("### Live Reasoning")
    live_progress = st.empty()
    live_log = st.empty()
    _render_live_reasoning(live_log, stored_events)

    cached = None
    if process_btn or watch_btn:
        stream_state = _stream_processing(selected_id, live_status, live_progress, live_log)
        live_events_store[selected_id] = stream_state.get("events", [])

        if stream_state.get("status") == "failed":
            live_status.error(stream_state.get("error", "Processing failed"))
        else:
            cached = stream_state.get("result")
            if cached is None:
                fallback = get_result(selected_id)
                if not _is_job_status_payload(fallback):
                    cached = fallback
    else:
        if _is_job_status_payload(result_state):
            if result_status in {"queued", "processing"}:
                live_status.info("Processing in background. Click `Watch Live` to follow the reasoning.")
                live_progress.progress(10 if result_status == "processing" else 5)
            elif result_status == "failed":
                live_status.error(f"Processing failed: {result_state.get('error', 'Unknown error')}")
            else:
                live_status.caption("No cached result yet.")
        else:
            live_status.success("Cached result loaded.")
            cached = result_state

    if not cached:
        return

    _render_results(cached) if callable(globals().get("_render_results")) else None

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Interpretation", "Policy", "Suppliers", "Recommendation",
        "Escalations", "Near-Miss Options", "Audit Trail",
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
        _render_escalations(cached, selected_id)

    with tab6:
        _render_near_miss(cached, selected_id)

    with tab7:
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


def _has_unresolved_blocking_escalations(result):
    escalations = result.get("escalations", [])
    resolutions = result.get("escalation_resolutions", {})
    for esc in escalations:
        if esc.get("blocking", False):
            esc_id = esc.get("escalation_id", "")
            resolution = resolutions.get(esc_id, {})
            if not resolution.get("resolved", False):
                return True
    return False


def _render_suppliers(result):
    shortlist = result.get("supplier_shortlist", [])
    excluded = result.get("suppliers_excluded", [])
    provisional = _has_unresolved_blocking_escalations(result)
    reevaluated = result.get("reevaluated", False)

    if reevaluated:
        st.success(
            "**FINAL RESULTS** — These rankings have been re-evaluated after all escalations were resolved."
        )
    elif provisional:
        st.warning(
            "**PROVISIONAL RESULTS** — There are unresolved blocking escalations that may "
            "change these rankings. Review the Escalations tab to resolve them before proceeding."
        )

    if shortlist:
        if reevaluated:
            heading = "Ranked Supplier Comparison (FINAL)"
        elif provisional:
            heading = "Ranked Supplier Comparison (PROVISIONAL)"
        else:
            heading = "Ranked Supplier Comparison"
        st.markdown(f"### {heading}")

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
    provisional = _has_unresolved_blocking_escalations(result)
    reevaluated = result.get("reevaluated", False)

    if reevaluated:
        st.success("**Status: FINAL — Re-evaluated after escalation resolution**")
        st.caption(f"Re-evaluated at {result.get('reevaluated_at', 'unknown')}")
    elif provisional:
        st.warning("**Status: PROVISIONAL — Pending Escalation Resolution**")
        st.info(
            "This recommendation is provisional. Blocking escalations must be resolved "
            "before this recommendation can be considered final. Go to the Escalations tab "
            "to resolve them, then re-evaluate."
        )
        # List unresolved blocking escalations
        unresolved = []
        resolutions = result.get("escalation_resolutions", {})
        for esc in result.get("escalations", []):
            if esc.get("blocking") and not resolutions.get(esc.get("escalation_id", ""), {}).get("resolved"):
                unresolved.append(f"- **{esc.get('escalation_id', '')}**: {esc.get('trigger', '')}")
        if unresolved:
            st.markdown("**Unresolved blocking escalations:**\n" + "\n".join(unresolved))
    else:
        status = rec.get("status", "")
        if status == "proceed":
            st.success("**Status: Can Proceed**")
        elif status == "cannot_proceed":
            st.error("**Status: Cannot Proceed**")
        elif status == "requires_relaxation":
            st.warning("**Status: Requires Constraint Relaxation**")

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


def _render_escalations(result, request_id=None):
    escalations = result.get("escalations", [])
    resolutions = result.get("escalation_resolutions", {})

    if not escalations:
        st.success("No escalations required")
        return

    # --- Escalation overview cards ---
    st.markdown("### Escalation Overview")
    total = len(escalations)
    resolved_count = sum(
        1 for esc in escalations
        if resolutions.get(esc.get("escalation_id", ""), {}).get("resolved", False)
    )
    blocking_count = sum(1 for esc in escalations if esc.get("blocking", False))
    unresolved_blocking = sum(
        1 for esc in escalations
        if esc.get("blocking", False)
        and not resolutions.get(esc.get("escalation_id", ""), {}).get("resolved", False)
    )

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("Total", total)
    with col_m2:
        st.metric("Resolved", resolved_count)
    with col_m3:
        st.metric("Blocking", blocking_count)
    with col_m4:
        st.metric("Unresolved Blocking", unresolved_blocking)

    # Compact escalation cards
    for esc in escalations:
        esc_id = esc.get("escalation_id", "")
        blocking = esc.get("blocking", False)
        resolution = resolutions.get(esc_id, {})
        is_resolved = resolution.get("resolved", False)

        if is_resolved:
            icon = "✅"
        elif blocking:
            icon = "🔴"
        else:
            icon = "🟡"

        with st.expander(f"{icon} {esc_id} — {esc.get('rule', '')} | {'Resolved' if is_resolved else 'Unresolved'}", expanded=not is_resolved):
            st.markdown(f"**Trigger:** {esc.get('trigger', '')}")
            st.markdown(f"**Escalate To:** {esc.get('escalate_to', '')} | **Blocking:** {'Yes' if blocking else 'No'}")
            if is_resolved:
                st.success(f"Resolution: {resolution.get('resolution_summary', 'Resolved')}")

    all_resolved = resolved_count == total

    # --- Re-evaluation banner ---
    if all_resolved and not result.get("reevaluated"):
        st.markdown("---")
        st.success("All escalations have been resolved!")
        st.info(
            "The current output (Interpretation, Policy, Suppliers, Recommendation) was generated "
            "before these escalations were resolved and may be out of date. Click **Re-evaluate** "
            "to refresh all tabs based on the escalation resolutions."
        )
        if request_id:
            if st.button("Re-evaluate All Outputs", type="primary", use_container_width=True, key="reevaluate_btn"):
                try:
                    with st.spinner("Re-evaluating all outputs based on escalation resolutions..."):
                        r = httpx.post(
                            f"{API_BASE}/escalation/{request_id}/reevaluate",
                            timeout=60,
                        )
                        r.raise_for_status()
                    st.rerun()
                except Exception as e:
                    st.error(f"Re-evaluation failed: {e}")
        return

    if result.get("reevaluated"):
        st.markdown("---")
        st.success(
            f"Output was re-evaluated at {result.get('reevaluated_at', 'unknown')} "
            "to reflect all escalation resolutions. All tabs now show final results."
        )
        return

    # --- Unified chat interface ---
    st.markdown("---")
    st.markdown("### Escalation Resolution Chat")
    st.caption(
        "Use this chat to discuss and resolve all escalations. "
        "The assistant will identify which escalation(s) your message addresses."
    )

    # Load unified chat history
    unified_chat_key = f"unified_esc_chat_{request_id}"
    if unified_chat_key not in st.session_state:
        st.session_state[unified_chat_key] = result.get("_unified_chat_history", [])

    # Display chat messages
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state[unified_chat_key]:
            role = msg.get("role", "human")
            with st.chat_message("user" if role == "human" else "assistant"):
                st.write(msg.get("content", ""))

    # Show initial guidance if chat is empty
    if not st.session_state[unified_chat_key] and unresolved_blocking > 0:
        unresolved_list = [
            esc for esc in escalations
            if not resolutions.get(esc.get("escalation_id", ""), {}).get("resolved", False)
        ]
        guidance_parts = ["**Unresolved escalations to address:**"]
        for esc in unresolved_list:
            esc_id = esc.get("escalation_id", "")
            guidance_parts.append(
                f"- **{esc_id}** ({esc.get('rule', '')}): {esc.get('trigger', '')}"
            )
        st.info("\n".join(guidance_parts))

    # Input area
    if request_id and not all_resolved:
        col_input, col_send = st.columns([5, 1])
        with col_input:
            user_msg = st.text_input(
                "Message",
                key="unified_esc_input",
                label_visibility="collapsed",
                placeholder="Provide resolution, clarification, or approval for any escalation...",
            )
        with col_send:
            send_btn = st.button("Send", key="unified_esc_send", use_container_width=True)

        # Manual resolve buttons for individual escalations
        st.markdown("**Quick resolve:**")
        resolve_cols = st.columns(min(len(escalations), 4))
        for idx, esc in enumerate(escalations):
            esc_id = esc.get("escalation_id", "")
            is_resolved = resolutions.get(esc_id, {}).get("resolved", False)
            if not is_resolved:
                col = resolve_cols[idx % len(resolve_cols)]
                with col:
                    if st.button(f"Resolve {esc_id}", key=f"resolve_{esc_id}", use_container_width=True):
                        try:
                            r = httpx.post(
                                f"{API_BASE}/escalation/{request_id}/{esc_id}/resolve",
                                timeout=10,
                            )
                            r.raise_for_status()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to resolve {esc_id}: {e}")

        if send_btn and user_msg:
            try:
                r = httpx.post(
                    f"{API_BASE}/escalation/{request_id}/chat-unified",
                    json={"message": user_msg},
                    timeout=30,
                )
                r.raise_for_status()
                updated = r.json()
                st.session_state[unified_chat_key] = updated.get("chat_history", [])
                st.rerun()
            except Exception as e:
                st.error(f"Failed to send message: {e}")


def _render_near_miss(result, request_id=None):
    near_miss = result.get("near_miss_suppliers", [])

    if not near_miss:
        st.info("No near-miss options identified. All viable suppliers are shown in the Suppliers tab.")
        return

    st.markdown("### Near-Miss Supplier Options")
    st.warning(
        "The suppliers below do **not** fully satisfy the specification. "
        "They are presented for human review because the gaps are small enough to potentially accept."
    )

    for nm in near_miss:
        supplier_id = nm.get("supplier_id", "")
        supplier_name = nm.get("supplier_name", "")
        decision = nm.get("human_decision")

        # Decision badge
        if decision == "approved":
            badge = "✅ APPROVED"
        elif decision == "rejected":
            badge = "❌ REJECTED"
        else:
            badge = "⏳ PENDING REVIEW"

        st.markdown(f"### {supplier_name} ({supplier_id}) — {badge}")

        # Relaxed requirements breakdown
        relaxed = nm.get("relaxed_requirements", [])
        if relaxed:
            st.markdown("**Requirements not met:**")
            for req in relaxed:
                risk = req.get("risk_assessment", "Unknown")
                risk_color = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(
                    risk.split(" ")[0] if risk else "", "⚪"
                )
                st.markdown(f"""
{risk_color} **{req.get('requirement', '')}**
- **Required:** {req.get('original_value', 'N/A')}
- **Supplier offers:** {req.get('supplier_value', 'N/A')}
- **Gap:** {req.get('gap_description', 'N/A')}
- **Risk:** {req.get('risk_assessment', 'N/A')}
""")

        if nm.get("overall_near_miss_rationale"):
            st.info(f"**Rationale:** {nm['overall_near_miss_rationale']}")

        if nm.get("recommended_action"):
            st.markdown(f"**Recommended action:** {nm['recommended_action']}")

        # Approve/Reject buttons (only if no decision yet)
        if decision is None and request_id:
            col_approve, col_reject = st.columns(2)
            with col_approve:
                if st.button(f"Approve", key=f"approve_{supplier_id}", use_container_width=True, type="primary"):
                    try:
                        r = httpx.post(
                            f"{API_BASE}/near-miss/{request_id}/{supplier_id}/decide",
                            json={"decision": "approved"},
                            timeout=10,
                        )
                        r.raise_for_status()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to approve: {e}")
            with col_reject:
                if st.button(f"Reject", key=f"reject_{supplier_id}", use_container_width=True):
                    try:
                        r = httpx.post(
                            f"{API_BASE}/near-miss/{request_id}/{supplier_id}/decide",
                            json={"decision": "rejected"},
                            timeout=10,
                        )
                        r.raise_for_status()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to reject: {e}")

        st.markdown("---")


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


_render_main_area(selected_id, requests_list, total)
