from __future__ import annotations
from backend.data_loader import data_store


def get_historical_awards(request_id: str) -> list[dict]:
    """Get historical awards for a specific request."""
    return data_store.historical_by_request.get(request_id, [])


def get_supplier_history(supplier_id: str) -> list[dict]:
    """Get all historical awards for a supplier."""
    return data_store.historical_by_supplier.get(supplier_id, [])


def get_supplier_performance_summary(supplier_id: str) -> dict:
    """Compute a summary of supplier's historical performance."""
    history = get_supplier_history(supplier_id)
    if not history:
        return {"has_history": False}

    awarded = [h for h in history if h.get("awarded") is True or h.get("awarded") == "True"]
    savings = [
        float(h["savings_pct"])
        for h in awarded
        if h.get("savings_pct") is not None and str(h["savings_pct"]) != "nan"
    ]
    compliant = sum(
        1 for h in awarded
        if h.get("policy_compliant") is True or h.get("policy_compliant") == "True"
    )
    lead_times = [
        int(h["lead_time_days"])
        for h in awarded
        if h.get("lead_time_days") is not None and str(h["lead_time_days"]) != "nan"
    ]

    return {
        "has_history": True,
        "total_awards": len(awarded),
        "total_evaluations": len(history),
        "avg_savings_pct": round(sum(savings) / len(savings), 2) if savings else 0,
        "compliance_rate": round(compliant / len(awarded), 2) if awarded else 0,
        "avg_lead_time_days": round(sum(lead_times) / len(lead_times), 1) if lead_times else 0,
    }
