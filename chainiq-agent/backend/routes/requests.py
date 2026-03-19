from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from backend.data_loader import data_store

router = APIRouter()


@router.get("/requests")
async def list_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
