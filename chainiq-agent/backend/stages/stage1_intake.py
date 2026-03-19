from __future__ import annotations
from datetime import datetime, timezone
from backend.models.prs import PRS, PRSField
from backend.services.llm import call_llm_json
from backend.data_loader import data_store
from backend.config import MODEL_EXTRACTION
from backend.prompts.stage1_prompt import STAGE1_SYSTEM, build_stage1_user_message


async def run_stage1(request: dict, emit=None) -> PRS:
    """Stage 1: Parse free-text request and extract structured PRS fields."""
    categories = data_store.categories_df.to_dict("records")

    user_msg = build_stage1_user_message(request, categories)
    extracted = await call_llm_json(MODEL_EXTRACTION, STAGE1_SYSTEM, user_msg)

    prs = PRS(request_id=request["request_id"])
    prs.created_at = request.get("created_at", "")
    prs.processed_at = datetime.now(timezone.utc).isoformat()
    prs.original_request_text = request.get("request_text", "")

    # Map extracted fields to PRS
    field_mapping = {
        "category_l1": "category_l1",
        "category_l2": "category_l2",
        "quantity": "quantity",
        "unit_of_measure": "unit_of_measure",
        "budget_amount": "budget_amount",
        "currency": "currency",
        "delivery_countries": "delivery_countries",
        "required_by_date": "required_by_date",
        "days_until_required": "days_until_required",
        "data_residency_required": "data_residency_required",
        "esg_requirement": "esg_requirement",
        "preferred_supplier_stated": "preferred_supplier_stated",
        "incumbent_supplier": "incumbent_supplier",
        "requester_instruction": "requester_instruction",
        "contract_type": "contract_type",
        "request_language": "request_language",
        "request_channel": "request_channel",
        "business_unit": "business_unit",
        "translated_text": "translated_text",
    }

    for ext_key, prs_key in field_mapping.items():
        if ext_key in extracted:
            field_data = extracted[ext_key]
            if isinstance(field_data, dict) and "value" in field_data:
                setattr(prs, prs_key, PRSField(
                    value=field_data["value"],
                    confidence=field_data.get("confidence", 0.8),
                    evidence=field_data.get("evidence", ""),
                    source=field_data.get("source", "extracted"),
                ))
            else:
                # LLM returned a plain value instead of metadata dict
                setattr(prs, prs_key, PRSField(
                    value=field_data,
                    confidence=0.8,
                    evidence="",
                    source="extracted",
                ))

    # Enrich with structured fields from the request that may be more reliable
    _enrich_from_structured(prs, request)

    # Store discrepancies if detected
    if "discrepancies" in extracted:
        disc = extracted["discrepancies"]
        if isinstance(disc, dict) and "value" in disc:
            disc = disc["value"]
        if disc:
            prs.detected_anomalies = PRSField(
                value=disc,
                confidence=0.9,
                evidence="Stage 1 discrepancy detection",
                source="extracted",
            )

    if emit:
        await emit(
            event_type="extraction",
            stage="stage1",
            message="Stage 1 extracted structured request fields",
            payload={
                "category_l1": prs.category_l1.value,
                "category_l2": prs.category_l2.value,
                "quantity": prs.quantity.value,
                "unit_of_measure": prs.unit_of_measure.value,
                "budget_amount": prs.budget_amount.value,
                "currency": prs.currency.value,
                "delivery_countries": prs.delivery_countries.value,
                "required_by_date": prs.required_by_date.value,
                "preferred_supplier_stated": prs.preferred_supplier_stated.value,
                "detected_anomalies": prs.detected_anomalies.value,
            },
        )

    return prs


def _enrich_from_structured(prs: PRS, request: dict):
    """Override LLM extraction with structured fields when available and reliable."""
    # These structured fields from the request JSON are ground truth
    structured_overrides = {
        "category_l1": request.get("category_l1"),
        "category_l2": request.get("category_l2"),
        "currency": request.get("currency"),
        "quantity": request.get("quantity"),
        "budget_amount": request.get("budget_amount"),
        "required_by_date": request.get("required_by_date"),
        "request_language": request.get("request_language"),
        "request_channel": request.get("request_channel"),
        "business_unit": request.get("business_unit"),
    }

    for field_name, struct_value in structured_overrides.items():
        if struct_value is None:
            continue
        field = getattr(prs, field_name)
        if isinstance(field, PRSField):
            # Keep LLM extraction if structured field matches; flag if different
            if field.value is not None and field.value != struct_value:
                # Discrepancy — keep structured as primary but note the conflict
                field.evidence = f"Structured: {struct_value}, LLM extracted: {field.value}"
            field.value = struct_value
            field.confidence = 1.0
            field.source = "extracted"

    # Delivery countries from structured data
    if request.get("delivery_countries"):
        prs.delivery_countries = PRSField(
            value=request["delivery_countries"],
            confidence=1.0,
            evidence="structured field",
            source="extracted",
        )

    # Boolean fields
    if request.get("data_residency_constraint") is not None:
        prs.data_residency_required = PRSField(
            value=request["data_residency_constraint"],
            confidence=1.0,
            evidence="structured field",
            source="extracted",
        )
    if request.get("esg_requirement") is not None:
        prs.esg_requirement = PRSField(
            value=request["esg_requirement"],
            confidence=1.0,
            evidence="structured field",
            source="extracted",
        )

    # Preferred/incumbent suppliers
    if request.get("preferred_supplier_mentioned"):
        prs.preferred_supplier_stated = PRSField(
            value=request["preferred_supplier_mentioned"],
            confidence=1.0,
            evidence="structured field",
            source="extracted",
        )
    if request.get("incumbent_supplier"):
        prs.incumbent_supplier = PRSField(
            value=request["incumbent_supplier"],
            confidence=1.0,
            evidence="structured field",
            source="extracted",
        )

    # Compute days_until_required
    if prs.required_by_date.value and prs.created_at:
        try:
            req_date = datetime.fromisoformat(prs.required_by_date.value)
            created = datetime.fromisoformat(prs.created_at.replace("Z", "+00:00"))
            if req_date.tzinfo is None:
                req_date = req_date.replace(tzinfo=timezone.utc)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            days = (req_date - created).days
            prs.days_until_required = PRSField(
                value=days, confidence=1.0, evidence="computed", source="derived"
            )
        except (ValueError, TypeError):
            pass
