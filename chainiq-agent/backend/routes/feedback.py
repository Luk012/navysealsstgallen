from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.routes.process import _results_cache, _run_pipeline
from backend.data_loader import data_store

router = APIRouter()


class FeedbackRequest(BaseModel):
    feedback_text: str
    accepted_relaxations: list[str] = []
    rejected_relaxations: list[str] = []


@router.post("/feedback/{request_id}")
async def submit_feedback(request_id: str, feedback: FeedbackRequest):
    """Submit user feedback for Branch B relaxation and re-process."""
    if request_id not in _results_cache:
        raise HTTPException(status_code=404, detail="No result found. Process the request first.")

    previous = _results_cache[request_id]
    if previous.get("branch") != "B":
        raise HTTPException(status_code=400, detail="Feedback only applicable for Branch B results.")

    request = data_store.requests_by_id.get(request_id)
    if not request:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

    # Re-process with feedback context
    # For now, re-run the pipeline (a more sophisticated version would
    # update the PRS with feedback and re-run only Stage 4)
    result = await _run_pipeline(request)
    result["user_feedback"] = feedback.model_dump()
    _results_cache[request_id] = result
    return result
