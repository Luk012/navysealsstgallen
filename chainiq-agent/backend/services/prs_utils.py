from __future__ import annotations

from numbers import Real
from typing import Any


PRS_FIELD_META_KEYS = {"value", "confidence", "evidence", "source"}
NUMERIC_FIELDS = {
    "quantity",
    "budget_amount",
    "days_until_required",
    "estimated_total_value",
    "quotes_required",
}
BOOLEAN_FIELDS = {
    "data_residency_required",
    "esg_requirement",
    "preferred_supplier_eligible",
}


def unwrap_field_value(value: Any) -> Any:
    """Unwrap nested PRS-style field payloads emitted by the LLM."""
    while isinstance(value, dict) and "value" in value and set(value).issubset(PRS_FIELD_META_KEYS):
        value = value["value"]
    return value


def coerce_number(value: Any, default: float | int | None = None) -> float | int | None:
    """Convert common numeric payload shapes to a number."""
    value = unwrap_field_value(value)

    if value is None:
        return default
    if isinstance(value, Real) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if not cleaned:
            return default
        try:
            return float(cleaned) if "." in cleaned else int(cleaned)
        except ValueError:
            return default

    return default


def coerce_bool(value: Any, default: bool = False) -> bool:
    value = unwrap_field_value(value)

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False

    return default


def normalize_prs_field_value(field_name: str, value: Any) -> Any:
    """Normalize LLM-proposed values before writing them back into the PRS."""
    value = unwrap_field_value(value)

    if field_name in NUMERIC_FIELDS:
        return coerce_number(value, default=value)
    if field_name in BOOLEAN_FIELDS:
        return coerce_bool(value, default=bool(value))

    return value
