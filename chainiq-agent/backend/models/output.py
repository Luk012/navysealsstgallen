from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    issue_id: str
    severity: str  # "critical", "high", "medium", "low"
    type: str
    description: str
    action_required: str = ""


class PolicyEvaluation(BaseModel):
    approval_threshold: dict = Field(default_factory=dict)
    preferred_supplier: dict = Field(default_factory=dict)
    restricted_suppliers: dict = Field(default_factory=dict)
    category_rules_applied: list[dict] = Field(default_factory=list)
    geography_rules_applied: list[dict] = Field(default_factory=list)
    verification_report: dict = Field(default_factory=dict)


class SupplierShortlistEntry(BaseModel):
    rank: int
    supplier_id: str
    supplier_name: str
    preferred: bool = False
    incumbent: bool = False
    pricing_tier_applied: str = ""
    unit_price: float = 0.0
    total_price: float = 0.0
    currency: str = "EUR"
    standard_lead_time_days: int = 0
    expedited_lead_time_days: int = 0
    expedited_unit_price: float = 0.0
    expedited_total: float = 0.0
    quality_score: int = 0
    risk_score: int = 0
    esg_score: int = 0
    policy_compliant: bool = True
    covers_delivery_country: bool = True
    recommendation_note: str = ""


class Escalation(BaseModel):
    escalation_id: str
    rule: str
    trigger: str
    escalate_to: str
    blocking: bool = True


class EscalationChatMessage(BaseModel):
    role: str  # "human" or "system"
    content: str
    timestamp: str = ""


class EscalationResolution(BaseModel):
    escalation_id: str
    resolved: bool = False
    chat_history: list[EscalationChatMessage] = Field(default_factory=list)
    resolution_summary: str = ""


class NearMissSupplier(BaseModel):
    supplier_id: str
    supplier_name: str
    relaxed_requirements: list[dict] = Field(default_factory=list)
    overall_near_miss_rationale: str = ""
    recommended_action: str = ""
    human_decision: Optional[str] = None  # None, "approved", "rejected"


class Recommendation(BaseModel):
    status: str  # "proceed", "cannot_proceed", "requires_relaxation"
    reason: str = ""
    preferred_supplier_if_resolved: str = ""
    preferred_supplier_rationale: str = ""
    minimum_budget_required: Optional[float] = None
    minimum_budget_currency: Optional[str] = None


class AuditTrail(BaseModel):
    policies_checked: list[str] = Field(default_factory=list)
    supplier_ids_evaluated: list[str] = Field(default_factory=list)
    pricing_tiers_applied: str = ""
    data_sources_used: list[str] = Field(default_factory=list)
    historical_awards_consulted: bool = False
    historical_award_note: str = ""
    commit_log: list[dict] = Field(default_factory=list)


class ProcessingResult(BaseModel):
    request_id: str
    processed_at: str = ""
    request_interpretation: dict = Field(default_factory=dict)
    validation: dict = Field(default_factory=dict)
    policy_evaluation: dict = Field(default_factory=dict)
    supplier_shortlist: list[dict] = Field(default_factory=list)
    suppliers_excluded: list[dict] = Field(default_factory=list)
    escalations: list[dict] = Field(default_factory=list)
    escalation_resolutions: dict = Field(default_factory=dict)
    recommendation: dict = Field(default_factory=dict)
    audit_trail: dict = Field(default_factory=dict)
    branch: str = "A"  # "A" or "B"
    relaxations: list[dict] = Field(default_factory=list)
    near_miss_suppliers: list[dict] = Field(default_factory=list)
    prs: dict = Field(default_factory=dict)
    reevaluated: bool = False
    reevaluated_at: Optional[str] = None
