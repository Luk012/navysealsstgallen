from __future__ import annotations
from enum import IntFlag
from typing import Any
from pydantic import BaseModel, Field
from backend.config import WEIGHT_HARD, WEIGHT_EXPENSIVE, WEIGHT_MODERATE, WEIGHT_CHEAP


class ConstraintFlag(IntFlag):
    NONE = 0
    # Hard constraints (never relaxed)
    RESTRICTED = 1 << 0
    DATA_RESIDENCY = 1 << 1
    WRONG_CATEGORY = 1 << 2
    NO_REGION_COVER = 1 << 3
    # Expensive constraints
    BUDGET_BREACH = 1 << 4
    ESG_FAIL = 1 << 5
    CURRENCY_MISMATCH = 1 << 6
    # Moderate constraints
    LEAD_TIME_MISS = 1 << 7
    NOT_PREFERRED = 1 << 8
    GEO_GAP = 1 << 9
    # Cheap constraints
    CAPACITY_CONCERN = 1 << 10
    NO_HISTORICAL = 1 << 11


HARD_MASK = (
    ConstraintFlag.RESTRICTED
    | ConstraintFlag.DATA_RESIDENCY
    | ConstraintFlag.WRONG_CATEGORY
    | ConstraintFlag.NO_REGION_COVER
)

CONSTRAINT_WEIGHT_MAP = {
    ConstraintFlag.RESTRICTED: WEIGHT_HARD,
    ConstraintFlag.DATA_RESIDENCY: WEIGHT_HARD,
    ConstraintFlag.WRONG_CATEGORY: WEIGHT_HARD,
    ConstraintFlag.NO_REGION_COVER: WEIGHT_HARD,
    ConstraintFlag.BUDGET_BREACH: WEIGHT_EXPENSIVE,
    ConstraintFlag.ESG_FAIL: WEIGHT_EXPENSIVE,
    ConstraintFlag.CURRENCY_MISMATCH: WEIGHT_EXPENSIVE,
    ConstraintFlag.LEAD_TIME_MISS: WEIGHT_MODERATE,
    ConstraintFlag.NOT_PREFERRED: WEIGHT_MODERATE,
    ConstraintFlag.GEO_GAP: WEIGHT_MODERATE,
    ConstraintFlag.CAPACITY_CONCERN: WEIGHT_CHEAP,
    ConstraintFlag.NO_HISTORICAL: WEIGHT_CHEAP,
}


def compute_penalty(bitmask: int) -> float:
    total = 0.0
    for flag, weight in CONSTRAINT_WEIGHT_MAP.items():
        if bitmask & flag:
            if weight == float("inf"):
                return float("inf")
            total += weight
    return total


def is_hard_fail(bitmask: int) -> bool:
    return bool(bitmask & HARD_MASK)


class SupplierConstraintResult(BaseModel):
    supplier_id: str
    supplier_name: str
    failure_bitmask: int = 0
    hard_fail: bool = False
    constraint_details: list[dict] = Field(default_factory=list)
    total_penalty: float = 0.0
    pricing: dict = Field(default_factory=dict)
    scores: dict = Field(default_factory=dict)
    preferred: bool = False
    incumbent: bool = False
    covers_delivery_country: bool = True
