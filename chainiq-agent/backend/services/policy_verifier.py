"""Three-phase policy verification system.

Phase 1: Deterministic checks (pure Python, 0 LLM calls)
Phase 2: Semi-deterministic gate checks (pure Python, 0 LLM calls)
Phase 3: Batched qualitative LLM verification (at most 1 LLM call)

The verifier classifies every policy from policies.json and checks each one
against the current PRS and Stage 4 supplier results.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.config import DATA_DIR, MODEL_REASONING
from backend.models.prs import PRS
from backend.models.constraint import SupplierConstraintResult
from backend.services.policy_engine import (
    get_approval_threshold,
    is_preferred_supplier,
    check_supplier_restriction,
    get_category_rules,
    get_geography_rules,
    get_escalation_rules,
)
from backend.services.prs_utils import coerce_number, coerce_bool
from backend.data_loader import data_store

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD_HUMAN_REVIEW = 0.7

# Load classification metadata
_classification_path = DATA_DIR / "policy_classification.json"
_classification: dict = {}
if _classification_path.exists():
    with open(_classification_path) as f:
        _classification = json.load(f)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PolicyCheckResult(BaseModel):
    rule_id: str
    section: str  # approval_thresholds, preferred_suppliers, restricted_suppliers, category_rules, geography_rules, escalation_rules
    classification: str  # deterministic, semi, qualitative
    applicable: bool = True
    compliant: Optional[bool] = None
    confidence: float = 1.0
    reasoning: str = ""
    evidence_found: str = ""
    checked_by: str = "python"  # "python" or "llm"
    requires_human_review: bool = False


class VerificationReport(BaseModel):
    results: list[PolicyCheckResult] = Field(default_factory=list)
    deterministic_count: int = 0
    semi_deterministic_count: int = 0
    qualitative_count: int = 0
    llm_calls_made: int = 0
    rules_skipped_by_gate: int = 0
    rules_flagged_for_review: int = 0

    def summary(self) -> dict:
        return {
            "total_rules_checked": len(self.results),
            "deterministic": self.deterministic_count,
            "semi_deterministic": self.semi_deterministic_count,
            "qualitative": self.qualitative_count,
            "llm_calls_made": self.llm_calls_made,
            "rules_skipped_by_gate": self.rules_skipped_by_gate,
            "rules_flagged_for_review": self.rules_flagged_for_review,
            "compliant": sum(1 for r in self.results if r.compliant is True),
            "non_compliant": sum(1 for r in self.results if r.compliant is False),
            "not_applicable": sum(1 for r in self.results if not r.applicable),
        }


# ---------------------------------------------------------------------------
# Phase 1: Deterministic checks
# ---------------------------------------------------------------------------

def _check_approval_thresholds(prs: PRS, stage4_results: list[SupplierConstraintResult]) -> list[PolicyCheckResult]:
    """Check all approval threshold rules (AT-001 to AT-015)."""
    results = []
    currency = prs.currency.value or "EUR"
    estimated_value = coerce_number(prs.estimated_total_value.value)
    if estimated_value is None:
        estimated_value = coerce_number(prs.budget_amount.value, default=0)
    estimated_value = float(estimated_value or 0)

    threshold = get_approval_threshold(currency, estimated_value)
    if not threshold:
        results.append(PolicyCheckResult(
            rule_id="AT-NONE",
            section="approval_thresholds",
            classification="deterministic",
            applicable=True,
            compliant=False,
            confidence=1.0,
            reasoning=f"No approval threshold found for currency={currency}, value={estimated_value}",
        ))
        return results

    threshold_id = threshold.get("threshold_id", "AT-???")
    min_quotes = threshold.get("min_supplier_quotes", 3)
    passing_count = sum(1 for s in stage4_results if not s.hard_fail)

    quotes_ok = passing_count >= min_quotes
    results.append(PolicyCheckResult(
        rule_id=threshold_id,
        section="approval_thresholds",
        classification="deterministic",
        applicable=True,
        compliant=quotes_ok,
        confidence=1.0,
        reasoning=(
            f"Threshold {threshold_id}: {currency} {estimated_value:.2f} requires "
            f"{min_quotes} quote(s). {passing_count} viable supplier(s) found. "
            f"{'Sufficient.' if quotes_ok else 'Insufficient — escalation or relaxation needed.'}"
        ),
    ))
    return results


def _check_preferred_suppliers(prs: PRS, stage4_results: list[SupplierConstraintResult]) -> list[PolicyCheckResult]:
    """Check if preferred suppliers were considered."""
    results = []
    cat_l1 = prs.category_l1.value or ""
    cat_l2 = prs.category_l2.value or ""
    delivery_countries = prs.delivery_countries.value or []

    preferred_found = any(s.preferred for s in stage4_results)
    results.append(PolicyCheckResult(
        rule_id="PREF-CHECK",
        section="preferred_suppliers",
        classification="deterministic",
        applicable=True,
        compliant=True,  # Preferred supplier is a preference, not a hard requirement
        confidence=1.0,
        reasoning=(
            f"Preferred supplier(s) {'included' if preferred_found else 'not found'} "
            f"in candidate pool for {cat_l1}/{cat_l2}."
        ),
    ))
    return results


def _check_restricted_suppliers(prs: PRS, stage4_results: list[SupplierConstraintResult]) -> list[PolicyCheckResult]:
    """Check that no restricted suppliers passed through."""
    results = []
    restricted_passing = [
        s for s in stage4_results
        if not s.hard_fail
        and any(d.get("constraint") == "RESTRICTED" and d.get("status") == "fail"
                for d in s.constraint_details)
    ]

    results.append(PolicyCheckResult(
        rule_id="RESTR-CHECK",
        section="restricted_suppliers",
        classification="deterministic",
        applicable=True,
        compliant=len(restricted_passing) == 0,
        confidence=1.0,
        reasoning=(
            "No restricted suppliers in viable shortlist."
            if len(restricted_passing) == 0
            else f"{len(restricted_passing)} restricted supplier(s) incorrectly in viable pool."
        ),
    ))
    return results


def _check_cr001(prs: PRS, stage4_results: list[SupplierConstraintResult]) -> PolicyCheckResult:
    """CR-001: At least 3 compliant suppliers compared above EUR/CHF 100K."""
    currency = prs.currency.value or "EUR"
    estimated_value = coerce_number(prs.estimated_total_value.value)
    if estimated_value is None:
        estimated_value = coerce_number(prs.budget_amount.value, default=0)
    estimated_value = float(estimated_value or 0)
    cat_l2 = prs.category_l2.value or ""

    if cat_l2 != "Laptops" or currency not in ("EUR", "CHF") or estimated_value <= 100000:
        return PolicyCheckResult(
            rule_id="CR-001", section="category_rules", classification="deterministic",
            applicable=False, reasoning="Rule does not apply (wrong category, currency, or amount below threshold).",
        )

    passing_count = sum(1 for s in stage4_results if not s.hard_fail)
    compliant = passing_count >= 3
    return PolicyCheckResult(
        rule_id="CR-001", section="category_rules", classification="deterministic",
        applicable=True, compliant=compliant, confidence=1.0,
        reasoning=(
            f"{passing_count} compliant supplier(s) compared for {currency} {estimated_value:.2f}. "
            f"{'Meets' if compliant else 'Does not meet'} 3-supplier comparison requirement."
        ),
    )


def _check_cr003(prs: PRS) -> PolicyCheckResult:
    """CR-003: Break-fix pool replenishment below EUR/CHF 75K → fast-track eligible."""
    currency = prs.currency.value or "EUR"
    estimated_value = coerce_number(prs.estimated_total_value.value)
    if estimated_value is None:
        estimated_value = coerce_number(prs.budget_amount.value, default=0)
    estimated_value = float(estimated_value or 0)
    cat_l2 = prs.category_l2.value or ""

    if cat_l2 != "Replacement / Break-Fix Pool Devices":
        return PolicyCheckResult(
            rule_id="CR-003", section="category_rules", classification="deterministic",
            applicable=False, reasoning="Not a break-fix pool request.",
        )

    if currency not in ("EUR", "CHF"):
        return PolicyCheckResult(
            rule_id="CR-003", section="category_rules", classification="deterministic",
            applicable=False, reasoning=f"Currency {currency} not in EUR/CHF scope.",
        )

    eligible = estimated_value < 75000
    return PolicyCheckResult(
        rule_id="CR-003", section="category_rules", classification="deterministic",
        applicable=True, compliant=True, confidence=1.0,
        reasoning=(
            f"Break-fix pool at {currency} {estimated_value:.2f}. "
            f"{'Eligible for fast-track (1 quote sufficient).' if eligible else 'Standard approval required (above 75K).'}"
        ),
    )


def _check_cr004(prs: PRS, stage4_results: list[SupplierConstraintResult]) -> PolicyCheckResult:
    """CR-004: Data residency constraint → only suppliers supporting residency."""
    data_residency = coerce_bool(prs.data_residency_required.value, default=False)

    if not data_residency:
        return PolicyCheckResult(
            rule_id="CR-004", section="category_rules", classification="deterministic",
            applicable=False, reasoning="No data residency constraint on this request.",
        )

    # Check that all non-hard-fail suppliers support data residency
    passing = [s for s in stage4_results if not s.hard_fail]
    violators = [
        s for s in passing
        if any(d.get("constraint") == "DATA_RESIDENCY" and d.get("status") == "fail"
               for d in s.constraint_details)
    ]

    compliant = len(violators) == 0
    return PolicyCheckResult(
        rule_id="CR-004", section="category_rules", classification="deterministic",
        applicable=True, compliant=compliant, confidence=1.0,
        reasoning=(
            "All viable suppliers support data residency."
            if compliant
            else f"{len(violators)} viable supplier(s) lack data residency support."
        ),
    )


def _check_escalation_rules(prs: PRS, stage4_results: list[SupplierConstraintResult]) -> list[PolicyCheckResult]:
    """Check deterministic escalation rules ER-001 through ER-007."""
    results = []
    cat_l2 = prs.category_l2.value or ""
    passing = [s for s in stage4_results if not s.hard_fail]

    # ER-001: Missing required information
    required_fields = ["category_l1", "category_l2", "quantity", "budget_amount", "currency", "delivery_countries"]
    missing = []
    for field_name in required_fields:
        field = getattr(prs, field_name, None)
        if field is None or field.value is None or field.confidence < 0.5:
            missing.append(field_name)

    triggered_er001 = len(missing) > 0
    results.append(PolicyCheckResult(
        rule_id="ER-001", section="escalation_rules", classification="deterministic",
        applicable=True, compliant=not triggered_er001, confidence=1.0,
        reasoning=(
            f"Missing/low-confidence fields: {', '.join(missing)}. Escalate to Requester."
            if triggered_er001
            else "All required fields present with sufficient confidence."
        ),
    ))

    # ER-002: Preferred supplier restricted
    cat_l1 = prs.category_l1.value or ""
    delivery_countries = prs.delivery_countries.value or []
    preferred_restricted = False
    for s in stage4_results:
        if s.preferred:
            is_restr, _ = check_supplier_restriction(
                s.supplier_id, cat_l1, cat_l2, delivery_countries,
            )
            if is_restr:
                preferred_restricted = True
                break

    results.append(PolicyCheckResult(
        rule_id="ER-002", section="escalation_rules", classification="deterministic",
        applicable=True, compliant=not preferred_restricted, confidence=1.0,
        reasoning=(
            "A preferred supplier is restricted for this request. Escalate to Procurement Manager."
            if preferred_restricted
            else "No preferred supplier restriction conflict."
        ),
    ))

    # ER-003: Value exceeds threshold (highest tier requires CPO)
    estimated_value = coerce_number(prs.estimated_total_value.value)
    if estimated_value is None:
        estimated_value = coerce_number(prs.budget_amount.value, default=0)
    currency = prs.currency.value or "EUR"
    threshold = get_approval_threshold(currency, float(estimated_value or 0))
    exceeds = False
    if threshold:
        approvers = threshold.get("deviation_approval_required_from", threshold.get("approvers", []))
        exceeds = "CPO" in approvers or "cpo" in approvers

    results.append(PolicyCheckResult(
        rule_id="ER-003", section="escalation_rules", classification="deterministic",
        applicable=True, compliant=not exceeds, confidence=1.0,
        reasoning=(
            f"Value {currency} {float(estimated_value or 0):.2f} in highest threshold tier. Escalate to Head of Strategic Sourcing."
            if exceeds
            else "Value within standard threshold range."
        ),
    ))

    # ER-004: No compliant supplier found
    no_compliant = len(passing) == 0
    results.append(PolicyCheckResult(
        rule_id="ER-004", section="escalation_rules", classification="deterministic",
        applicable=True, compliant=not no_compliant, confidence=1.0,
        reasoning=(
            "No compliant supplier found after Stage 4 evaluation. Escalate to Head of Category."
            if no_compliant
            else f"{len(passing)} compliant supplier(s) available."
        ),
    ))

    # ER-005: Data residency constraint conflict
    data_residency = coerce_bool(prs.data_residency_required.value, default=False)
    residency_conflict = False
    if data_residency:
        has_residency_supplier = any(
            not s.hard_fail and not any(
                d.get("constraint") == "DATA_RESIDENCY" and d.get("status") == "fail"
                for d in s.constraint_details
            )
            for s in stage4_results
        )
        residency_conflict = not has_residency_supplier

    results.append(PolicyCheckResult(
        rule_id="ER-005", section="escalation_rules", classification="deterministic",
        applicable=data_residency, compliant=not residency_conflict, confidence=1.0,
        reasoning=(
            "Data residency required but no supplier supports it. Escalate to Security and Compliance Review."
            if residency_conflict
            else ("Data residency satisfied by available suppliers." if data_residency else "No data residency constraint.")
        ),
    ))

    # ER-006: Single supplier capacity risk
    single_supplier = len(passing) == 1
    results.append(PolicyCheckResult(
        rule_id="ER-006", section="escalation_rules", classification="deterministic",
        applicable=True, compliant=not single_supplier, confidence=1.0,
        reasoning=(
            "Only 1 compliant supplier available — single-supplier capacity risk. Escalate to Sourcing Excellence Lead."
            if single_supplier
            else f"{len(passing)} compliant supplier(s) — no single-supplier risk."
        ),
    ))

    # ER-007: Brand safety review needed
    brand_safety = cat_l2 == "Influencer Campaign Management"
    results.append(PolicyCheckResult(
        rule_id="ER-007", section="escalation_rules", classification="deterministic",
        applicable=brand_safety, compliant=True, confidence=1.0,
        reasoning=(
            "Influencer campaign — brand-safety review required. Escalate to Marketing Governance Lead."
            if brand_safety
            else "Not an influencer campaign category."
        ),
    ))

    return results


def run_deterministic_checks(
    prs: PRS, stage4_results: list[SupplierConstraintResult]
) -> list[PolicyCheckResult]:
    """Phase 1: Run all deterministic policy checks."""
    results = []
    results.extend(_check_approval_thresholds(prs, stage4_results))
    results.extend(_check_preferred_suppliers(prs, stage4_results))
    results.extend(_check_restricted_suppliers(prs, stage4_results))
    results.append(_check_cr001(prs, stage4_results))
    results.append(_check_cr003(prs))
    results.append(_check_cr004(prs, stage4_results))
    results.extend(_check_escalation_rules(prs, stage4_results))
    return results


# ---------------------------------------------------------------------------
# Phase 2: Semi-deterministic gate checks
# ---------------------------------------------------------------------------

def _gate_cr002(prs: PRS) -> tuple[bool, dict]:
    """CR-002: Mobile workstation > 50 units → needs compatibility review."""
    cat_l2 = prs.category_l2.value or ""
    qty = coerce_number(prs.quantity.value, default=0) or 0
    if cat_l2 != "Mobile Workstations" or qty <= 50:
        return False, {}
    return True, {
        "rule_id": "CR-002",
        "rule_text": "Mobile workstation requests above 50 units require compatibility review with engineering or CAD lead",
        "section": "category_rules",
        "deterministic_context": f"Category is Mobile Workstations, quantity is {qty} (> 50 threshold)",
        "question": "Is there evidence in the request that a compatibility review with engineering or CAD lead has been completed or is planned?",
    }


def _gate_cr005(prs: PRS) -> tuple[bool, dict]:
    """CR-005: Managed cloud > 250K → needs security review."""
    cat_l2 = prs.category_l2.value or ""
    currency = prs.currency.value or "EUR"
    estimated_value = coerce_number(prs.estimated_total_value.value)
    if estimated_value is None:
        estimated_value = coerce_number(prs.budget_amount.value, default=0)
    estimated_value = float(estimated_value or 0)

    if cat_l2 != "Managed Cloud Platform Services" or currency not in ("EUR", "CHF") or estimated_value <= 250000:
        return False, {}
    return True, {
        "rule_id": "CR-005",
        "rule_text": "Managed platform requests above EUR/CHF 250000 require security architecture review",
        "section": "category_rules",
        "deterministic_context": f"Category is Managed Cloud Platform Services, value is {currency} {estimated_value:.2f} (> 250K)",
        "question": "Is there evidence that a security architecture review has been completed, is planned, or has been requested?",
    }


def _gate_cr007(prs: PRS) -> tuple[bool, dict]:
    """CR-007: Software dev > 60 consulting days → needs CVs."""
    cat_l2 = prs.category_l2.value or ""
    qty = coerce_number(prs.quantity.value, default=0) or 0
    uom = (prs.unit_of_measure.value or "").lower()

    if cat_l2 != "Software Development Services" or qty <= 60:
        return False, {}
    # Also check unit is day-based
    if uom and "day" not in uom:
        return False, {}
    return True, {
        "rule_id": "CR-007",
        "rule_text": "Named consultant CVs or equivalent capability profiles are required above 60 consulting days",
        "section": "category_rules",
        "deterministic_context": f"Category is Software Development Services, quantity is {qty} days (> 60 threshold)",
        "question": "Is there evidence that named consultant CVs or capability profiles have been provided or will be required?",
    }


def _gate_gr001(prs: PRS) -> tuple[bool, dict]:
    """GR-001: Swiss data residency → prefer sovereign providers."""
    delivery_countries = prs.delivery_countries.value or []
    data_residency = coerce_bool(prs.data_residency_required.value, default=False)
    if "CH" not in delivery_countries or not data_residency:
        return False, {}
    return True, {
        "rule_id": "GR-001",
        "rule_text": "Swiss data residency-sensitive cloud requests prefer sovereign or approved providers",
        "section": "geography_rules",
        "deterministic_context": "Delivery includes Switzerland (CH) and data residency is required",
        "question": "Are the shortlisted suppliers considered sovereign or approved providers for Swiss data residency?",
    }


def _gate_gr002(prs: PRS) -> tuple[bool, dict]:
    """GR-002: Germany urgent device → delivery capability check."""
    delivery_countries = prs.delivery_countries.value or []
    cat_l1 = prs.category_l1.value or ""
    days_until = coerce_number(prs.days_until_required.value)

    if "DE" not in delivery_countries or cat_l1 != "IT":
        return False, {}
    # Consider urgent if < 14 days
    if days_until is not None and days_until >= 14:
        return False, {}
    return True, {
        "rule_id": "GR-002",
        "rule_text": "Urgent end-user-device requests in Germany require delivery capability within requested deadline",
        "section": "geography_rules",
        "deterministic_context": f"Delivery to Germany (DE), IT category, {f'{days_until} days until required' if days_until else 'urgency unclear'}",
        "question": "Based on the request context, can the supplier deliver within the requested deadline for this urgent German order?",
    }


def _gate_gr005(prs: PRS) -> tuple[bool, dict]:
    """GR-005: Americas data sovereignty for IT/Professional Services."""
    delivery_countries = prs.delivery_countries.value or []
    cat_l1 = prs.category_l1.value or ""
    target_countries = {"US", "CA", "BR", "MX"}

    if not (set(delivery_countries) & target_countries) or cat_l1 not in ("IT", "Professional Services"):
        return False, {}
    matched = set(delivery_countries) & target_countries
    return True, {
        "rule_id": "GR-005",
        "rule_text": "US data sovereignty: financial and healthcare data must remain in-country",
        "section": "geography_rules",
        "deterministic_context": f"Delivery to {', '.join(sorted(matched))}, category {cat_l1}",
        "question": "Does the request involve financial or healthcare data requiring US data sovereignty, and do suppliers have US data centre availability?",
    }


def _gate_gr006(prs: PRS) -> tuple[bool, dict]:
    """GR-006: APAC data localisation."""
    delivery_countries = prs.delivery_countries.value or []
    cat_l1 = prs.category_l1.value or ""
    target_countries = {"SG", "AU", "JP", "IN"}

    if not (set(delivery_countries) & target_countries) or cat_l1 not in ("IT", "Professional Services"):
        return False, {}
    matched = set(delivery_countries) & target_countries
    return True, {
        "rule_id": "GR-006",
        "rule_text": "APAC data localisation: RBI/MAS/FISC guidelines apply to financial data",
        "section": "geography_rules",
        "deterministic_context": f"Delivery to {', '.join(sorted(matched))}, category {cat_l1}",
        "question": "Does the request involve regulated financial data subject to APAC data localisation, and do suppliers support in-country data residency?",
    }


def _gate_gr007(prs: PRS) -> tuple[bool, dict]:
    """GR-007: UAE/South Africa PDPL/POPIA compliance."""
    delivery_countries = prs.delivery_countries.value or []
    cat_l1 = prs.category_l1.value or ""
    target_countries = {"UAE", "ZA"}

    if not (set(delivery_countries) & target_countries) or cat_l1 not in ("IT", "Professional Services"):
        return False, {}
    matched = set(delivery_countries) & target_countries
    return True, {
        "rule_id": "GR-007",
        "rule_text": "UAE PDPL and South Africa POPIA compliance required for personal data processing",
        "section": "geography_rules",
        "deterministic_context": f"Delivery to {', '.join(sorted(matched))}, category {cat_l1}",
        "question": "Does the request involve personal data processing, and is there evidence of supplier PDPL/POPIA compliance?",
    }


def _gate_gr008(prs: PRS) -> tuple[bool, dict]:
    """GR-008: Brazil/Mexico DPA requirements."""
    delivery_countries = prs.delivery_countries.value or []
    cat_l1 = prs.category_l1.value or ""
    target_countries = {"BR", "MX"}

    if not (set(delivery_countries) & target_countries) or cat_l1 not in ("IT", "Professional Services", "Marketing"):
        return False, {}
    matched = set(delivery_countries) & target_countries
    return True, {
        "rule_id": "GR-008",
        "rule_text": "Brazil LGPD and Mexico LFPDPPP apply. DPA must be in place before contract signature.",
        "section": "geography_rules",
        "deterministic_context": f"Delivery to {', '.join(sorted(matched))}, category {cat_l1}",
        "question": "Is there evidence that data processing agreement (DPA) requirements for LGPD/LFPDPPP have been addressed?",
    }


def _gate_er008(prs: PRS) -> tuple[bool, dict]:
    """ER-008: USD currency → supplier registration/sanctions screening."""
    currency = prs.currency.value or "EUR"
    if currency != "USD":
        return False, {}
    return True, {
        "rule_id": "ER-008",
        "rule_text": "Supplier not registered or sanctioned-screened in delivery country",
        "section": "escalation_rules",
        "deterministic_context": f"Currency is USD — sanctions screening applies",
        "question": "Is there any indication that the supplier is not registered or has not been sanctioned-screened in the delivery country?",
    }


# All gate check functions
_GATE_CHECKS = [
    _gate_cr002, _gate_cr005, _gate_cr007,
    _gate_gr001, _gate_gr002, _gate_gr005, _gate_gr006, _gate_gr007, _gate_gr008,
    _gate_er008,
]


def run_gate_checks(prs: PRS) -> tuple[list[PolicyCheckResult], list[dict]]:
    """Phase 2: Evaluate deterministic gates for semi-deterministic rules.

    Returns:
        - List of PolicyCheckResult for rules where gate was NOT met (not_applicable)
        - List of rule context dicts for rules that passed the gate (need LLM)
    """
    skipped_results = []
    rules_for_llm = []

    for gate_fn in _GATE_CHECKS:
        passes_gate, context = gate_fn(prs)
        if passes_gate:
            rules_for_llm.append(context)
        else:
            rule_id = gate_fn.__doc__.split(":")[0].strip() if gate_fn.__doc__ else "UNKNOWN"
            skipped_results.append(PolicyCheckResult(
                rule_id=rule_id,
                section="category_rules" if rule_id.startswith("CR") else (
                    "geography_rules" if rule_id.startswith("GR") else "escalation_rules"
                ),
                classification="semi",
                applicable=False,
                reasoning="Deterministic gate not met — rule does not apply to this request.",
            ))

    return skipped_results, rules_for_llm


# ---------------------------------------------------------------------------
# Qualitative rule applicability checks
# ---------------------------------------------------------------------------

def _get_applicable_qualitative_rules(prs: PRS) -> list[dict]:
    """Get qualitative rules that apply to this request based on category/country."""
    rules = []
    cat_l2 = prs.category_l2.value or ""
    delivery_countries = prs.delivery_countries.value or []
    cat_l1 = prs.category_l1.value or ""

    # CR-006: Reception and Lounge Furniture
    if cat_l2 == "Reception and Lounge Furniture":
        rules.append({
            "rule_id": "CR-006",
            "rule_text": "Reception and lounge projects require business design sign-off before award",
            "section": "category_rules",
            "deterministic_context": f"Category is {cat_l2}",
            "question": "Is there evidence that business design sign-off has been obtained or is planned before award?",
        })

    # CR-008: Cybersecurity Advisory
    if cat_l2 == "Cybersecurity Advisory":
        rules.append({
            "rule_id": "CR-008",
            "rule_text": "Cybersecurity advisory suppliers must demonstrate relevant certifications or equivalent references",
            "section": "category_rules",
            "deterministic_context": f"Category is {cat_l2}",
            "question": "Does the request mention or require that suppliers demonstrate relevant cybersecurity certifications (e.g., ISO 27001, CREST, OSCP) or equivalent references?",
        })

    # CR-009: SEM performance baseline
    if cat_l2 == "Search Engine Marketing (SEM)":
        rules.append({
            "rule_id": "CR-009",
            "rule_text": "SEM proposals should include performance baseline or benchmark assumptions",
            "section": "category_rules",
            "deterministic_context": f"Category is {cat_l2}",
            "question": "Does the request mention or require performance baselines, benchmarks, or KPI assumptions?",
        })

    # CR-010: Influencer brand-safety
    if cat_l2 == "Influencer Campaign Management":
        rules.append({
            "rule_id": "CR-010",
            "rule_text": "Influencer campaigns require brand-safety review before final award",
            "section": "category_rules",
            "deterministic_context": f"Category is {cat_l2}",
            "question": "Is there evidence that a brand-safety review has been completed or is planned before final award?",
        })

    # GR-003: France French-language
    if "FR" in delivery_countries and cat_l1 in ("Professional Services", "Marketing"):
        rules.append({
            "rule_id": "GR-003",
            "rule_text": "Business-facing services for France should support French-language delivery where relevant",
            "section": "geography_rules",
            "deterministic_context": f"Delivery to France (FR), category {cat_l1}",
            "question": "Does the request indicate whether French-language delivery support is needed, and can suppliers provide it?",
        })

    # GR-004: Spain large rollouts
    if "ES" in delivery_countries and cat_l1 in ("Facilities", "IT"):
        rules.append({
            "rule_id": "GR-004",
            "rule_text": "Large furniture and device rollouts in Spain should evidence installation or deployment support",
            "section": "geography_rules",
            "deterministic_context": f"Delivery to Spain (ES), category {cat_l1}",
            "question": "Does the request appear to be a large rollout, and is there evidence of installation or deployment support?",
        })

    return rules


# ---------------------------------------------------------------------------
# Phase 3: Batched LLM verification
# ---------------------------------------------------------------------------

async def run_qualitative_checks(
    prs: PRS,
    rules_to_evaluate: list[dict],
) -> list[PolicyCheckResult]:
    """Phase 3: Send all applicable qualitative/gated rules to LLM in one batch.

    Returns list of PolicyCheckResult with LLM judgments.
    """
    if not rules_to_evaluate:
        return []

    from backend.services.llm import call_llm_json
    from backend.prompts.verification_prompt import (
        VERIFICATION_SYSTEM_PROMPT,
        build_verification_user_message,
    )

    # Build PRS summary for the prompt
    prs_summary = {
        "category_l1": prs.category_l1.value,
        "category_l2": prs.category_l2.value,
        "quantity": prs.quantity.value,
        "unit_of_measure": prs.unit_of_measure.value,
        "budget_amount": prs.budget_amount.value,
        "currency": prs.currency.value,
        "delivery_countries": prs.delivery_countries.value,
        "required_by_date": prs.required_by_date.value,
        "data_residency_required": prs.data_residency_required.value,
        "esg_requirement": prs.esg_requirement.value,
        "preferred_supplier_stated": prs.preferred_supplier_stated.value,
        "business_unit": prs.business_unit.value,
    }

    user_message = build_verification_user_message(
        request_text=prs.original_request_text,
        prs_summary=prs_summary,
        rules_to_evaluate=rules_to_evaluate,
    )

    try:
        llm_results = await call_llm_json(
            model=MODEL_REASONING,
            system=VERIFICATION_SYSTEM_PROMPT,
            user_message=user_message,
            max_tokens=4096,
            temperature=0.0,
        )
    except Exception as e:
        logger.error("LLM verification call failed: %s", e)
        # Return all rules as non-compliant with low confidence
        return [
            PolicyCheckResult(
                rule_id=r["rule_id"],
                section=r.get("section", "unknown"),
                classification="qualitative" if r["rule_id"].startswith("CR-0") and int(r["rule_id"][-1]) in (6, 8, 9) else "semi",
                applicable=True,
                compliant=None,
                confidence=0.0,
                reasoning=f"LLM verification failed: {e}",
                checked_by="llm",
                requires_human_review=True,
            )
            for r in rules_to_evaluate
        ]

    # Parse LLM results — handle both list and dict responses
    if isinstance(llm_results, dict):
        llm_results = llm_results.get("results", [llm_results])

    # Map rule_id -> LLM result
    llm_by_id = {r.get("rule_id"): r for r in llm_results if isinstance(r, dict)}

    results = []
    for rule in rules_to_evaluate:
        rule_id = rule["rule_id"]
        llm_r = llm_by_id.get(rule_id, {})

        confidence = float(llm_r.get("confidence", 0.0))
        compliant = llm_r.get("compliant", False)
        requires_review = confidence < CONFIDENCE_THRESHOLD_HUMAN_REVIEW

        # Determine classification from the classification file
        section = rule.get("section", "category_rules")
        cls_section = _classification.get(section, {})
        cls_info = cls_section.get(rule_id, {}) if isinstance(cls_section, dict) else {}
        classification = cls_info.get("classification", "qualitative")

        results.append(PolicyCheckResult(
            rule_id=rule_id,
            section=section,
            classification=classification,
            applicable=True,
            compliant=compliant,
            confidence=confidence,
            reasoning=llm_r.get("reasoning", "No reasoning provided by LLM."),
            evidence_found=llm_r.get("evidence_found", ""),
            checked_by="llm",
            requires_human_review=requires_review,
        ))

    return results


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def verify_all_policies(
    prs: PRS,
    stage4_results: list[SupplierConstraintResult],
) -> VerificationReport:
    """Run all three verification phases and return a complete report.

    Phase 1: Deterministic checks (pure Python)
    Phase 2: Semi-deterministic gate checks (pure Python)
    Phase 3: Batched qualitative LLM verification (0 or 1 LLM call)
    """
    report = VerificationReport()

    # Phase 1: Deterministic
    deterministic_results = run_deterministic_checks(prs, stage4_results)
    report.results.extend(deterministic_results)
    report.deterministic_count = len(deterministic_results)

    # Phase 2: Gate checks
    skipped_results, rules_for_llm = run_gate_checks(prs)
    report.results.extend(skipped_results)
    report.rules_skipped_by_gate = len(skipped_results)

    # Collect qualitative rules that apply
    qualitative_rules = _get_applicable_qualitative_rules(prs)

    # Combine gated + qualitative rules for a single LLM call
    all_llm_rules = rules_for_llm + qualitative_rules

    # Phase 3: Batched LLM call
    if all_llm_rules:
        llm_results = await run_qualitative_checks(prs, all_llm_rules)
        report.results.extend(llm_results)
        report.llm_calls_made = 1
        report.semi_deterministic_count = len(rules_for_llm)
        report.qualitative_count = len(qualitative_rules)
    else:
        report.semi_deterministic_count = 0
        report.qualitative_count = 0

    # Count rules flagged for human review
    report.rules_flagged_for_review = sum(
        1 for r in report.results if r.requires_human_review
    )

    return report
