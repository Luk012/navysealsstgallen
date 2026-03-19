from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class PRSField(BaseModel):
    value: Any = None
    confidence: float = 0.0
    evidence: str = ""
    source: Literal["extracted", "derived", "policy", "user_feedback", "default"] = "default"


class PRS(BaseModel):
    """Procurement Requirement Spec — fixed template for every request."""

    request_id: str
    created_at: str = ""
    processed_at: str = ""
    original_request_text: str = ""

    # Extracted fields (Stage 1)
    category_l1: PRSField = Field(default_factory=PRSField)
    category_l2: PRSField = Field(default_factory=PRSField)
    quantity: PRSField = Field(default_factory=PRSField)
    unit_of_measure: PRSField = Field(default_factory=PRSField)
    budget_amount: PRSField = Field(default_factory=PRSField)
    currency: PRSField = Field(default_factory=PRSField)
    delivery_countries: PRSField = Field(default_factory=PRSField)
    required_by_date: PRSField = Field(default_factory=PRSField)
    days_until_required: PRSField = Field(default_factory=PRSField)
    data_residency_required: PRSField = Field(default_factory=PRSField)
    esg_requirement: PRSField = Field(default_factory=PRSField)
    preferred_supplier_stated: PRSField = Field(default_factory=PRSField)
    incumbent_supplier: PRSField = Field(default_factory=PRSField)
    requester_instruction: PRSField = Field(default_factory=PRSField)
    contract_type: PRSField = Field(default_factory=PRSField)
    request_language: PRSField = Field(default_factory=PRSField)
    request_channel: PRSField = Field(default_factory=PRSField)
    business_unit: PRSField = Field(default_factory=PRSField)
    translated_text: PRSField = Field(default_factory=PRSField)

    # Derived fields (Stage 2)
    estimated_total_value: PRSField = Field(default_factory=PRSField)
    approval_threshold: PRSField = Field(default_factory=PRSField)
    quotes_required: PRSField = Field(default_factory=PRSField)
    approvers: PRSField = Field(default_factory=PRSField)
    applicable_category_rules: PRSField = Field(default_factory=PRSField)
    applicable_geography_rules: PRSField = Field(default_factory=PRSField)
    applicable_escalation_rules: PRSField = Field(default_factory=PRSField)
    preferred_supplier_eligible: PRSField = Field(default_factory=PRSField)
    detected_anomalies: PRSField = Field(default_factory=PRSField)

    # Validation
    completeness_status: PRSField = Field(default_factory=PRSField)
    issues: list[dict] = Field(default_factory=list)

    def get_field_value(self, field_path: str) -> Any:
        parts = field_path.split(".")
        obj = self
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                obj = getattr(obj, part, None)
        return obj

    def set_field(self, field_path: str, value: Any, confidence: float,
                  evidence: str, source: str):
        field_name = field_path.split(".")[0]
        if hasattr(self, field_name):
            field = getattr(self, field_name)
            if isinstance(field, PRSField):
                field.value = value
                field.confidence = confidence
                field.evidence = evidence
                field.source = source
