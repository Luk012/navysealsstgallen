from __future__ import annotations
from backend.models.constraint import (
    ConstraintFlag, SupplierConstraintResult,
    CONSTRAINT_WEIGHT_MAP, HARD_MASK, compute_penalty, is_hard_fail,
)


def greedy_relax(
    candidates: list[SupplierConstraintResult],
    k: int = 3,
) -> tuple[list[SupplierConstraintResult], list[dict]]:
    """Greedy constraint relaxation algorithm.

    Iteratively relaxes the lowest-cost soft constraint until K suppliers
    become eligible (failure_bitmask == 0 after all relaxations applied).

    Per the spec:
    1. Remove hard-fail suppliers permanently
    2. Pick supplier with lowest failure_cost, relax its constraints
    3. Other suppliers whose failures are a subset of relaxed constraints come free
    4. Repeat until >= K eligible
    """
    # Remove hard-fail suppliers (never relaxable)
    soft_candidates = [c for c in candidates if not is_hard_fail(c.failure_bitmask)]

    relaxed_bits = ConstraintFlag.NONE  # Accumulated relaxed constraints
    relaxations = []

    def count_eligible():
        return sum(1 for c in soft_candidates if (c.failure_bitmask & ~relaxed_bits) == 0)

    def get_eligible():
        return [c for c in soft_candidates if (c.failure_bitmask & ~relaxed_bits) == 0]

    while count_eligible() < k:
        # Among ineligible suppliers, find the one with lowest marginal cost
        # (fewest additional constraints to relax beyond what's already relaxed)
        best_supplier = None
        best_marginal_bits = None
        best_marginal_cost = float("inf")

        for c in soft_candidates:
            remaining = c.failure_bitmask & ~relaxed_bits
            if remaining == 0:
                continue  # Already eligible

            # Compute marginal cost = sum of weights of constraints not yet relaxed
            marginal_cost = 0
            for bit in ConstraintFlag:
                if bit == ConstraintFlag.NONE:
                    continue
                if not (remaining & bit):
                    continue
                if bit & HARD_MASK:
                    marginal_cost = float("inf")
                    break
                weight = CONSTRAINT_WEIGHT_MAP.get(bit, float("inf"))
                marginal_cost += weight

            if marginal_cost < best_marginal_cost:
                best_marginal_cost = marginal_cost
                best_supplier = c
                best_marginal_bits = remaining

        if best_supplier is None or best_marginal_cost == float("inf"):
            break  # No further relaxation possible

        # Relax all constraints this supplier needs
        for bit in ConstraintFlag:
            if bit == ConstraintFlag.NONE:
                continue
            if not (best_marginal_bits & bit):
                continue

            relaxed_bits |= bit
            # Count how many suppliers this frees (come for free)
            freed = sum(
                1 for c in soft_candidates
                if (c.failure_bitmask & ~relaxed_bits) == 0
                and (c.failure_bitmask & ~(relaxed_bits & ~bit)) != 0
            )

            relaxations.append({
                "constraint": bit.name,
                "weight": CONSTRAINT_WEIGHT_MAP.get(bit, 0),
                "weight_class": _get_weight_class(bit),
                "suppliers_unlocked": freed,
                "description": _describe_relaxation(bit),
            })

    eligible = get_eligible()

    # Update penalty scores for display
    for c in soft_candidates:
        c.failure_bitmask = c.failure_bitmask & ~relaxed_bits
        c.total_penalty = compute_penalty(c.failure_bitmask)
        c.hard_fail = is_hard_fail(c.failure_bitmask)

    return eligible, relaxations


def _get_weight_class(bit: ConstraintFlag) -> str:
    weight = CONSTRAINT_WEIGHT_MAP.get(bit, 0)
    if weight == float("inf"):
        return "hard"
    if weight >= 1000:
        return "expensive"
    if weight >= 100:
        return "moderate"
    return "cheap"


def _describe_relaxation(bit: ConstraintFlag) -> str:
    descriptions = {
        ConstraintFlag.BUDGET_BREACH: "Allow suppliers whose pricing exceeds the stated budget",
        ConstraintFlag.ESG_FAIL: "Waive ESG score requirement",
        ConstraintFlag.CURRENCY_MISMATCH: "Allow suppliers with different pricing currency",
        ConstraintFlag.LEAD_TIME_MISS: "Accept suppliers that cannot meet the delivery deadline",
        ConstraintFlag.NOT_PREFERRED: "Include non-preferred suppliers in the comparison",
        ConstraintFlag.GEO_GAP: "Accept suppliers with limited geographic coverage",
        ConstraintFlag.CAPACITY_CONCERN: "Accept suppliers with potential capacity constraints",
        ConstraintFlag.NO_HISTORICAL: "Include suppliers without historical performance data",
    }
    return descriptions.get(bit, f"Relax {bit.name} constraint")
