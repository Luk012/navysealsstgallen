from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from backend.data_loader import data_store

router = APIRouter()


class NewRequestBody(BaseModel):
    request_text: str


@router.get("/requests")
async def list_requests(
    page: int = Query(1, ge=1),
    # The Streamlit UI loads the full sample dataset for local filtering.
    page_size: int = Query(20, ge=1, le=500),
    category: str = Query(None),
    country: str = Query(None),
    scenario_tag: str = Query(None),
    search: str = Query(None),
):
    """List all purchase requests with filtering and pagination."""
    requests = data_store.requests_list

    # Apply filters
    if category:
        requests = [r for r in requests if r.get("category_l1") == category]
    if country:
        requests = [r for r in requests if r.get("country") == country]
    if scenario_tag:
        requests = [r for r in requests if scenario_tag in r.get("scenario_tags", [])]
    if search:
        search_lower = search.lower()
        requests = [
            r for r in requests
            if search_lower in r.get("request_id", "").lower()
            or search_lower in r.get("request_text", "").lower()
            or search_lower in r.get("title", "").lower()
        ]

    total = len(requests)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "requests": requests[start:end],
    }


@router.get("/requests/{request_id}")
async def get_request(request_id: str):
    """Get a single request by ID."""
    request = data_store.requests_by_id.get(request_id)
    if not request:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
    return request


def _next_request_id() -> str:
    existing_ids = list(data_store.requests_by_id.keys())
    max_num = 0
    for rid in existing_ids:
        try:
            num = int(rid.split("-")[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            continue
    return f"REQ-{max_num + 1:06d}"


@router.post("/requests")
async def create_request(body: NewRequestBody):
    """Create a new purchase request from free-text input."""
    text = body.request_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="request_text cannot be empty")

    request_id = _next_request_id()
    now = datetime.now(timezone.utc).isoformat()

    new_request = {
        "request_id": request_id,
        "created_at": now,
        "request_channel": "chat",
        "request_language": "en",
        "business_unit": "",
        "country": "",
        "site": "",
        "requester_id": "USR-CHAT",
        "requester_role": "Chat User",
        "submitted_for_id": "",
        "category_l1": "",
        "category_l2": "",
        "title": text[:80],
        "request_text": text,
        "currency": "",
        "budget_amount": None,
        "quantity": None,
        "unit_of_measure": "",
        "required_by_date": "",
        "preferred_supplier_mentioned": "",
        "incumbent_supplier": "",
        "contract_type_requested": "",
        "delivery_countries": [],
        "data_residency_constraint": False,
        "esg_requirement": False,
        "status": "new",
        "scenario_tags": ["user_submitted"],
    }

    # Add to in-memory data store
    data_store.requests_list.insert(0, new_request)
    data_store.requests_by_id[request_id] = new_request

    return new_request
