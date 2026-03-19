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


def fetch_events(request_id):
    """Fetch cached processing events from the backend."""
    try:
        r = httpx.get(f"{API_BASE}/events/{request_id}", timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("events", [])
    except Exception:
        return []


def _format_price(value, currency=""):
    """Format a price with precision matching pricing.csv.

    Small values (< 1.0) get 4 decimal places; others get 2.
    """
    if not isinstance(value, (int, float)):
        return f"{currency} {value}" if currency else str(value)
    if abs(value) < 1.0 and value != 0:
        formatted = f"{value:,.4f}"
    else:
        formatted = f"{value:,.2f}"
    return f"{currency} {formatted}".strip()


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
        "stage4": 65,
        "verification": 75,
        "branch_b": 82,
        "branch_a": 85,
        "near_miss": 90,
        "pipeline": 95,
    }.get(event.get("stage"), 15)


def _max_progress_from_events(events, default=0):
    max_progress = default
    for event in events:
        if event.get("event_type") == "heartbeat":
            continue
        event_progress = _progress_from_event(event)
        if event_progress > max_progress:
            max_progress = event_progress
    return max_progress


def _load_live_events(request_id, live_events_store):
    """Prefer the backend event log, but keep the longer local cache as fallback."""
    cached_events = live_events_store.get(request_id) or []
    backend_events = fetch_events(request_id)
    events = backend_events if len(backend_events) >= len(cached_events) else cached_events
    live_events_store[request_id] = events
    return events


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


def _update_live_status(status_placeholder, progress_placeholder, event, progress_state):
    """Update the live status and progress bar.

    progress_state is a dict with key "max" tracking the highest progress seen,
    so the bar never goes backwards (e.g. on heartbeats).
    """
    # Skip heartbeats for progress — they carry the job-level status which
    # would reset the bar to 10 every 5 seconds.
    if event.get("event_type") != "heartbeat":
        new_progress = _progress_from_event(event)
        if new_progress > progress_state.get("max", 0):
            progress_state["max"] = new_progress
    progress_placeholder.progress(progress_state.get("max", 5))

    status = event.get("status")
    message = event.get("message", "Processing")

    if status == "failed":
        status_placeholder.error(message)
    elif status == "completed":
        status_placeholder.success(message)
    elif event.get("event_type") == "heartbeat":
        status_placeholder.info("Processing is still running...")
    else:
        status_placeholder.info(message)


def _stream_processing(request_id, status_placeholder, progress_placeholder, log_placeholder, start_if_needed=True):
    if start_if_needed:
        start_state = start_processing(request_id)
        if start_state.get("status") == "failed":
            return {
                "status": "failed",
                "error": start_state.get("error", "Failed to start processing."),
                "events": [],
                "result": None,
            }

    if create_connection is None:
        return _poll_processing(
            request_id,
            status_placeholder,
            progress_placeholder,
            log_placeholder,
            Exception("websocket-client not installed"),
        )

    events = []
    final_result = None
    final_error = None
    final_status = None
    ws = None
    ws_error = None
    progress_state = {"max": 5}

    status_placeholder.info("Connecting to live reasoning stream...")
    progress_placeholder.progress(5)

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

            _update_live_status(status_placeholder, progress_placeholder, event, progress_state)
            _render_live_reasoning(log_placeholder, events)

            if event.get("event_type") == "final_result":
                final_result = event.get("payload")

            if event.get("event_type") == "status" and event.get("status") in {"completed", "failed"}:
                final_status = event.get("status")
                if final_status == "failed":
                    final_error = (event.get("payload") or {}).get("error") or event.get("message")
                break
    except Exception as e:
        return _poll_processing(
            request_id,
            status_placeholder,
            progress_placeholder,
            log_placeholder,
            e,
        )
    finally:
        try:
            ws.close()
        except Exception:
            pass

    if final_status is None:
        return _poll_processing(
            request_id,
            status_placeholder,
            progress_placeholder,
            log_placeholder,
            Exception("Live stream closed before completion status was received"),
        )

    return {
        "status": final_status,
        "error": final_error,
        "events": events,
        "result": final_result,
    }


def _poll_processing(request_id, status_placeholder, progress_placeholder, log_placeholder, ws_error=None):
    if isinstance(ws_error, WebSocketBadStatusException):
        note = "WebSocket unavailable — using status polling."
    elif ws_error is not None:
        note = f"WebSocket failed ({ws_error}) — using status polling."
    else:
        note = "Using status polling."

    status_placeholder.warning(note)
    progress_placeholder.progress(10)
    log_placeholder.code(note, language="text")

    progress_max = 10
    polled_events = []

    for _ in range(180):
        result = get_result(request_id)

        # Also poll events to update the live reasoning log
        polled_events = fetch_events(request_id)
        if polled_events:
            _render_live_reasoning(log_placeholder, polled_events)
            progress_max = _max_progress_from_events(polled_events, default=progress_max)
            progress_placeholder.progress(progress_max)

        if _is_job_status_payload(result):
            status = result.get("status")
            if status == "failed":
                return {
                    "status": "failed",
                    "error": result.get("error", "Processing failed"),
                    "events": polled_events,
                    "result": None,
                }
            if status == "completed":
                # Fetch final result
                final = get_result(request_id)
                final_events = fetch_events(request_id)
                progress_placeholder.progress(100)
                return {
                    "status": "completed",
                    "error": None,
                    "events": final_events,
                    "result": final if not _is_job_status_payload(final) else None,
                }
            time.sleep(2)
            continue

        return {
            "status": "completed",
            "error": None,
            "events": polled_events,
            "result": result,
        }

    # Timeout — check one last time
    latest = get_result(request_id)
    latest_events = fetch_events(request_id)
    if _is_job_status_payload(latest):
        return {
            "status": latest.get("status", "failed"),
            "error": latest.get("error", "Processing did not finish in time."),
            "events": latest_events,
            "result": None,
        }

    return {
        "status": "completed",
        "error": None,
        "events": latest_events,
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
    result_state = get_result(selected_id)
    result_status = result_state.get("status") if _is_job_status_payload(result_state) else None
    is_processing = result_status in {"queued", "processing"}
    has_result = not _is_job_status_payload(result_state)
    live_action = st.session_state.get("live_action")
    action_mode = None
    if isinstance(live_action, dict) and live_action.get("request_id") == selected_id:
        action_mode = live_action.get("mode")
    is_live_action_running = action_mode == "process"

    # Refresh the event log on every render so replay/progress stay in sync.
    stored_events = _load_live_events(selected_id, live_events_store)
    has_events = bool(stored_events)

    col_btn, col_status = st.columns([1, 3])
    with col_btn:
        process_btn = st.button(
            "Processing..." if action_mode == "process" else "Process Request",
            type="primary",
            use_container_width=True,
            disabled=is_processing or has_result or is_live_action_running,
        )
    with col_status:
        live_status = st.empty()

    with st.expander("Live Reasoning", expanded=is_live_action_running or is_processing):
        live_progress = st.empty()
        live_log = st.empty()

    if process_btn:
        st.session_state["live_action"] = {"request_id": selected_id, "mode": "process"}
        st.rerun()

    cached = None
    try:
        if action_mode == "process":
            stream_state = _stream_processing(
                selected_id,
                live_status,
                live_progress,
                live_log,
                start_if_needed=(action_mode == "process"),
            )
            new_events = stream_state.get("events", [])
            if new_events:
                live_events_store[selected_id] = new_events
            if stream_state.get("status") == "failed":
                live_status.error(stream_state.get("error", "Processing failed"))
            else:
                cached = stream_state.get("result")
                if cached is None:
                    fallback = get_result(selected_id)
                    if not _is_job_status_payload(fallback):
                        cached = fallback
        else:
            # No button clicked — show static state
            if _is_job_status_payload(result_state):
                if is_processing:
                    live_status.info("Processing in background...")
                    live_progress.progress(
                        _max_progress_from_events(
                            stored_events,
                            default=10 if result_status == "processing" else 5,
                        )
                    )
                elif result_status == "failed":
                    live_status.error(f"Processing failed: {result_state.get('error', 'Unknown error')}")
                    progress = _max_progress_from_events(stored_events)
                    if progress:
                        live_progress.progress(progress)
                else:
                    live_status.caption("Click **Process Request** to start analysis.")
            else:
                live_status.success("Cached result loaded.")
                cached = result_state
                live_progress.progress(100)

            # Always show cached events if available (viewable from request history)
            _render_live_reasoning(live_log, stored_events)
    finally:
        if action_mode:
            current_action = st.session_state.get("live_action")
            if isinstance(current_action, dict) and current_action.get("request_id") == selected_id:
                st.session_state.pop("live_action", None)

    if not cached:
        return

    tab1, tab2, tab3, tab4 = st.tabs([
        "Interpretation", "Suppliers", "Escalations", "Audit Trail",
    ])

    with tab1:
        _render_interpretation(cached)

    with tab2:
        _render_suppliers(cached, selected_id)

    with tab3:
        _render_escalations(cached, selected_id)

    with tab4:
        _render_audit_trail(cached)


def _render_interpretation(result):
    interp = result.get("request_interpretation", {})
    validation = result.get("validation", {})
    policy = result.get("policy_evaluation", {})

    # ── Key metrics row ──
    st.markdown("### Request Specification")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        cat = interp.get("category_l1", "N/A")
        cat2 = interp.get("category_l2", "")
        st.metric("Category", f"{cat}" + (f" > {cat2}" if cat2 else ""))
    with m2:
        budget = interp.get("budget_amount", "N/A")
        currency = interp.get("currency", "")
        if budget and budget != "N/A":
            st.metric("Budget", f"{currency} {budget:,.2f}" if isinstance(budget, (int, float)) else f"{currency} {budget}")
        else:
            st.metric("Budget", "Not specified")
    with m3:
        qty = interp.get("quantity", "N/A")
        uom = interp.get("unit_of_measure", "")
        st.metric("Quantity", f"{qty} {uom}" if qty and qty != "N/A" else "N/A")
    with m4:
        deadline = interp.get("required_by_date", "N/A")
        st.metric("Required By", deadline if deadline else "N/A")

    st.markdown("---")

    # ── Two-column detail layout ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Delivery & Logistics")
        countries = interp.get("delivery_countries", [])
        if isinstance(countries, list) and countries:
            st.markdown(f"**Delivery Countries:** {', '.join(countries)}")
        else:
            st.markdown(f"**Delivery Countries:** {countries or 'N/A'}")
        st.markdown(f"**Data Residency Required:** {'Yes' if interp.get('data_residency_required') else 'No'}")
        st.markdown(f"**ESG Requirement:** {'Yes' if interp.get('esg_requirement') else 'No'}")
        st.markdown(f"**Contract Type:** {interp.get('contract_type', 'N/A')}")

        st.markdown("#### Supplier Preferences")
        pref = interp.get("preferred_supplier_stated", "")
        inc = interp.get("incumbent_supplier", "")
        st.markdown(f"**Preferred Supplier:** {pref if pref else 'None stated'}")
        st.markdown(f"**Incumbent:** {inc if inc else 'None'}")

    with col_right:
        st.markdown("#### Request Metadata")
        st.markdown(f"**Language:** {interp.get('request_language', 'N/A')}")
        st.markdown(f"**Channel:** {interp.get('request_channel', 'N/A')}")
        st.markdown(f"**Business Unit:** {interp.get('business_unit', 'N/A')}")
        if interp.get("requester_instruction"):
            st.markdown(f"**Requester Note:** {interp['requester_instruction']}")
        if interp.get("translated_text"):
            with st.expander("Translated Text"):
                st.markdown(interp["translated_text"])

        # Policy summary
        threshold = policy.get("approval_threshold", {})
        if threshold:
            st.markdown("#### Approval Policy")
            st.markdown(f"**Threshold Tier:** {threshold.get('applicable_threshold', 'N/A')}")
            st.markdown(f"**Quotes Required:** {threshold.get('quotes_required', 'N/A')}")
            if threshold.get("basis"):
                st.caption(threshold["basis"])

    # ── Validation issues ──
    issues = validation.get("issues_detected", [])
    if issues:
        st.markdown("---")
        st.markdown("### Validation Issues")
        for issue in issues:
            severity = issue.get("severity", "medium")
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
            st.markdown(f"{icon} **{issue.get('issue_id', '')}** [{severity.upper()}]: {issue.get('type', '')}")
            st.markdown(f"  {issue.get('description', '')}")
            if issue.get("action_required"):
                st.markdown(f"  *Action:* {issue['action_required']}")
    else:
        st.success("No validation issues detected")


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


def _render_suppliers(result, request_id=None):
    shortlist = result.get("supplier_shortlist", [])
    rec = result.get("recommendation", {})
    branch = result.get("branch", "A")
    relaxations = result.get("relaxations", [])
    provisional = _has_unresolved_blocking_escalations(result)
    reevaluated = result.get("reevaluated", False)

    # ── Status banner ──
    if reevaluated:
        st.success("**FINAL** — Re-evaluated after all escalations were resolved.")
    elif provisional:
        st.warning(
            "**PROVISIONAL** — Unresolved blocking escalations may change these rankings. "
            "See the Escalations tab."
        )

    # ── Recommendation summary ──
    st.markdown("### Recommendation")
    status = rec.get("status", "")
    if status == "proceed":
        st.success("**Can Proceed**")
    elif status == "cannot_proceed":
        st.error("**Cannot Proceed**")
    elif status == "requires_relaxation":
        st.warning("**Requires Constraint Relaxation**")

    rec_cols = st.columns(2)
    with rec_cols[0]:
        st.markdown(f"**Branch:** {'A — viable options exist' if branch == 'A' else 'B — constraint relaxation needed'}")
        if rec.get("reason"):
            st.markdown(f"**Reason:** {rec['reason']}")
    with rec_cols[1]:
        if rec.get("preferred_supplier_if_resolved"):
            st.markdown(f"**Top Pick:** {rec['preferred_supplier_if_resolved']}")
            st.markdown(f"**Rationale:** {rec.get('preferred_supplier_rationale', '')}")
        if rec.get("minimum_budget_required"):
            st.metric("Min Budget Required", f"{rec.get('minimum_budget_currency', '')} {rec['minimum_budget_required']:,.2f}")

    # ── Relaxations (Branch B) ──
    if relaxations:
        with st.expander(f"Constraint Relaxations Applied ({len(relaxations)})"):
            for r in relaxations:
                st.markdown(f"⚖️ **{r.get('constraint', '')}** ({r.get('weight_class', '')}): {r.get('description', '')} — *{r.get('suppliers_unlocked', 0)} suppliers unlocked*")

    # Split shortlist into spec-satisfying and constraint-relaxing
    spec_options = [s for s in shortlist if s.get("option_type") != "constraint_relaxing"]
    relaxed_options = [s for s in shortlist if s.get("option_type") == "constraint_relaxing"]

    if not shortlist:
        excluded = result.get("suppliers_excluded", [])
        if excluded or rec.get("status"):
            st.warning("No viable suppliers were found for this request after constraint evaluation.")
            if excluded:
                with st.expander(f"Excluded Suppliers ({len(excluded)})"):
                    for s in excluded:
                        st.markdown(f"❌ **{s.get('supplier_name', '')}** ({s.get('supplier_id', '')}): {s.get('reason', '')}")
        else:
            st.info("No ranked suppliers available yet. Process the request to see results.")
        return

    st.markdown("---")

    # ── Radar chart comparison ──
    st.markdown("### Supplier Comparison")
    if len(shortlist) >= 2:
        categories_radar = ["Price", "Lead Time", "Quality", "Risk (inv)", "ESG"]
        fig = go.Figure()

        for s in shortlist[:5]:
            max_price = max(e.get("total_price", 1) for e in shortlist if e.get("total_price")) or 1
            price_score = 100 * (1 - s.get("total_price", 0) / max_price) if max_price else 50
            lead = s.get("lead_time_days") or s.get("standard_lead_time_days", 30)
            lead_score = 100 * (1 - min(lead, 60) / 60)
            quality = s.get("quality_score", 50)
            risk_inv = 100 - s.get("risk_score", 50)
            esg = s.get("esg_score", 50)
            shipping_tag = f" ({s.get('shipping_type', 'std')})" if s.get("shipping_type") else ""
            option_tag = " [relaxed]" if s.get("option_type") == "constraint_relaxing" else ""

            fig.add_trace(go.Scatterpolar(
                r=[price_score, lead_score, quality, risk_inv, esg],
                theta=categories_radar,
                fill="toself",
                name=f"#{s.get('rank', '?')} {s.get('supplier_name', '')}{shipping_tag}{option_tag}",
            ))

        fig.update_layout(
            polar=dict(bgcolor="#1a1f2e", radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=True,
            paper_bgcolor="#0e1117",
            font=dict(color="white"),
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Specification-Satisfying Options (exactly 3 if available) ──
    n_spec = len(spec_options)
    st.markdown(f"### Specification-Satisfying Options ({min(n_spec, 3)} of 3)")
    if n_spec >= 3:
        st.caption("These options fully meet all requirements.")
    elif n_spec > 0:
        st.caption(f"Only {n_spec} supplier(s) fully satisfy the specification.")
    else:
        st.warning("No suppliers fully satisfy the specification. See constraint-relaxing options below.")
    for s in spec_options[:3]:
        _render_supplier_card(s)

    # ── Constraint-Relaxing Options (exactly 2 if available) ──
    n_relaxed = len(relaxed_options)
    st.markdown("---")
    st.markdown(f"### Constraint-Relaxing Options ({min(n_relaxed, 2)} of 2)")
    if n_relaxed >= 2:
        st.caption(
            "These options almost meet the spec. Specific constraints have been relaxed — review the trade-offs below."
        )
    elif n_relaxed == 1:
        st.caption("Only 1 supplier available under relaxed constraints.")
    else:
        st.caption("No additional suppliers available even with relaxed constraints.")
    for s in relaxed_options[:2]:
        _render_supplier_card(s, show_relaxed=True)

    # ── Excluded suppliers ──
    excluded = result.get("suppliers_excluded", [])
    if excluded:
        with st.expander(f"Excluded Suppliers ({len(excluded)})"):
            for s in excluded:
                st.markdown(f"❌ **{s.get('supplier_name', '')}** ({s.get('supplier_id', '')}): {s.get('reason', '')}")


def _render_supplier_card(s, show_relaxed=False):
    """Render a single supplier option card with shipping type and why_consider."""
    rank = s.get("rank", 0)
    rank_icon = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
    shipping = s.get("shipping_type", "standard")
    shipping_badge = "🚀 Expedited" if shipping == "expedited" else "📦 Standard"
    labels = [shipping_badge]
    if s.get("preferred"):
        labels.append("Preferred")
    if s.get("incumbent"):
        labels.append("Incumbent")
    if s.get("option_type") == "constraint_relaxing":
        labels.append("Constraint Relaxed")
    label_str = " ".join(f"`{l}`" for l in labels)

    st.markdown(f"### {rank_icon} {s.get('supplier_name', '')} {label_str}")

    # Why consider this option — comparative tradeoff line
    why = s.get("why_consider", "")
    if why:
        st.success(f"**Why consider:** {why}")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Price", _format_price(s.get("total_price", 0), s.get("currency", "")))
    with col2:
        st.metric("Unit Price", _format_price(s.get("unit_price", 0), s.get("currency", "")))
    with col3:
        lead = s.get("lead_time_days") or s.get("standard_lead_time_days", "N/A")
        st.metric("Lead Time", f"{lead}d ({shipping})")
    with col4:
        st.metric("Quality / Risk / ESG", f"{s.get('quality_score', 'N/A')} / {s.get('risk_score', 'N/A')} / {s.get('esg_score', 'N/A')}")

    # Show relaxed constraints for constraint-relaxing options
    if show_relaxed:
        constraints_relaxed = s.get("constraints_relaxed", [])
        relaxed_reqs = s.get("relaxed_requirements", [])
        if constraints_relaxed:
            st.warning("**Constraints relaxed:** " + " | ".join(constraints_relaxed))
        if relaxed_reqs:
            for req in relaxed_reqs:
                risk = req.get("risk_assessment", "Unknown")
                risk_icon = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(
                    risk.split(" ")[0] if risk else "", "⚪"
                )
                st.markdown(
                    f"  {risk_icon} **{req.get('requirement', '')}**: "
                    f"{req.get('original_value', 'N/A')} vs {req.get('supplier_value', 'N/A')} "
                    f"— {req.get('gap_description', '')}"
                )
        if s.get("recommended_action"):
            st.info(f"**Recommended action:** {s['recommended_action']}")

    st.markdown("---")


def _render_escalations(result, request_id=None):
    escalations = result.get("escalations", [])
    resolutions = result.get("escalation_resolutions", {})

    if not escalations:
        st.markdown("### Escalations")
        st.success("No escalations required for this request. All policies are satisfied.")
        return

    total = len(escalations)
    resolved_count = sum(
        1 for esc in escalations
        if resolutions.get(esc.get("escalation_id", ""), {}).get("resolved", False)
    )
    unresolved_blocking = sum(
        1 for esc in escalations
        if esc.get("blocking", False)
        and not resolutions.get(esc.get("escalation_id", ""), {}).get("resolved", False)
    )
    all_resolved = resolved_count == total

    # ── Status header ──
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.metric("Total Escalations", total)
    with col_m2:
        st.metric("Resolved", resolved_count)
    with col_m3:
        st.metric("Unresolved Blocking", unresolved_blocking)

    # ── Escalation cards ──
    for esc in escalations:
        esc_id = esc.get("escalation_id", "")
        blocking = esc.get("blocking", False)
        resolution = resolutions.get(esc_id, {})
        is_resolved = resolution.get("resolved", False)

        icon = "✅" if is_resolved else ("🔴" if blocking else "🟡")

        with st.expander(
            f"{icon} {esc_id} — {esc.get('rule', '')} | {'Resolved' if is_resolved else 'Unresolved'}",
            expanded=not is_resolved,
        ):
            st.markdown(f"**Trigger:** {esc.get('trigger', '')}")
            st.markdown(f"**Escalate To:** {esc.get('escalate_to', '')} | **Blocking:** {'Yes' if blocking else 'No'}")
            if is_resolved:
                st.success(f"Resolution: {resolution.get('resolution_summary', 'Resolved')}")

    # ── Re-evaluation banner ──
    if all_resolved and not result.get("reevaluated"):
        st.markdown("---")
        st.success("All escalations resolved!")
        if request_id:
            if st.button("Re-evaluate All Outputs", type="primary", use_container_width=True, key="reevaluate_btn"):
                try:
                    with st.spinner("Re-evaluating all output tabs... This may take up to 3 minutes."):
                        r = httpx.post(f"{API_BASE}/escalation/{request_id}/reevaluate", timeout=180)
                        r.raise_for_status()
                    st.rerun()
                except httpx.TimeoutException:
                    # Check if re-evaluation completed despite timeout
                    latest = get_result(request_id)
                    if not _is_job_status_payload(latest) and latest.get("reevaluated"):
                        st.rerun()
                    else:
                        st.error(
                            "Re-evaluation is taking longer than expected. "
                            "Please refresh the page in a moment to check results."
                        )
                except Exception as e:
                    st.error(f"Re-evaluation failed: {e}")
        return

    if result.get("reevaluated"):
        st.markdown("---")
        st.success(f"Re-evaluated at {result.get('reevaluated_at', 'unknown')}. All tabs show final results.")
        return

    # ── Chat interface for resolution ──
    st.markdown("---")
    st.markdown("### Resolution Chat")

    unified_chat_key = f"unified_esc_chat_{request_id}"
    if unified_chat_key not in st.session_state:
        st.session_state[unified_chat_key] = result.get("_unified_chat_history", [])

    # Show guidance when chat is empty
    if not st.session_state[unified_chat_key]:
        unresolved_list = [
            esc for esc in escalations
            if not resolutions.get(esc.get("escalation_id", ""), {}).get("resolved", False)
        ]
        if unresolved_list:
            parts = ["**Escalations needing resolution:**"]
            for esc in unresolved_list:
                parts.append(f"- **{esc.get('escalation_id', '')}** ({esc.get('rule', '')}): {esc.get('trigger', '')}")
            st.info("\n".join(parts))

    # Render chat history
    for msg in st.session_state[unified_chat_key]:
        role = msg.get("role", "human")
        with st.chat_message("user" if role == "human" else "assistant"):
            st.write(msg.get("content", ""))

    # Chat input
    if request_id and not all_resolved:
        user_msg = st.chat_input("Provide information or approve an escalation...", key="esc_chat_input")

        if user_msg:
            st.session_state[unified_chat_key].append({"role": "human", "content": user_msg})
            with st.chat_message("user"):
                st.write(user_msg)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
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
                        st.error(f"Failed to send: {e}")


def _render_audit_trail(result):
    audit = result.get("audit_trail", {})
    commits = audit.get("commit_log", [])

    st.markdown("### Commit Log")

    if not commits:
        st.info("No commits recorded yet.")
        return

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


_render_main_area(selected_id, requests_list, total)
