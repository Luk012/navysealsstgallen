import json
import pandas as pd
from pathlib import Path
from backend.config import DATA_DIR


def _normalize_threshold(t: dict) -> dict:
    """Normalize USD threshold fields to match EUR/CHF schema."""
    return {
        "threshold_id": t["threshold_id"],
        "currency": t["currency"],
        "min_amount": t.get("min_amount", t.get("min_value", 0)),
        "max_amount": t.get("max_amount", t.get("max_value", 999999999.99)),
        "min_supplier_quotes": t.get("min_supplier_quotes", t.get("quotes_required", 1)),
        "managed_by": t.get("managed_by", t.get("approvers", ["business"])),
        "deviation_approval_required_from": t.get(
            "deviation_approval_required_from", []
        ),
        "policy_note": t.get("policy_note", ""),
    }


class DataStore:
    """Singleton data store loaded at startup."""

    def __init__(self):
        self._loaded = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if not self._loaded:
            self.load()
        return self.__dict__[name]

    def load(self):
        if self._loaded:
            return
        self._load_all()
        self._loaded = True

    def _load_all(self):
        # Raw data
        with open(DATA_DIR / "requests.json") as f:
            requests_list = json.load(f)
        with open(DATA_DIR / "policies.json") as f:
            self.policies = json.load(f)

        self.suppliers_df = pd.read_csv(DATA_DIR / "suppliers.csv")
        self.pricing_df = pd.read_csv(DATA_DIR / "pricing.csv")
        self.historical_df = pd.read_csv(DATA_DIR / "historical_awards.csv")
        self.categories_df = pd.read_csv(DATA_DIR / "categories.csv")

        # Index requests by ID
        self.requests_by_id = {r["request_id"]: r for r in requests_list}
        self.requests_list = requests_list

        # Parse service_regions from semicolon-delimited to list
        self.suppliers_df["service_regions_list"] = (
            self.suppliers_df["service_regions"]
            .fillna("")
            .apply(lambda x: [r.strip() for r in x.split(";") if r.strip()])
        )

        # Normalize approval thresholds
        self.approval_thresholds = [
            _normalize_threshold(t) for t in self.policies["approval_thresholds"]
        ]

        # Build indexes
        self._build_indexes()

    def _build_indexes(self):
        # Suppliers by (category_l1, category_l2) -> list of row dicts
        self.suppliers_by_category = {}
        for _, row in self.suppliers_df.iterrows():
            key = (row["category_l1"], row["category_l2"])
            self.suppliers_by_category.setdefault(key, []).append(row.to_dict())

        # Pricing by (supplier_id, category_l1, category_l2) -> list of tier dicts
        self.pricing_by_supplier_category = {}
        for _, row in self.pricing_df.iterrows():
            key = (row["supplier_id"], row["category_l1"], row["category_l2"])
            self.pricing_by_supplier_category.setdefault(key, []).append(row.to_dict())

        # Preferred supplier lookup: (supplier_id, category_l1, category_l2) -> entry
        self.preferred_lookup = {}
        for entry in self.policies.get("preferred_suppliers", []):
            key = (entry["supplier_id"], entry["category_l1"], entry["category_l2"])
            self.preferred_lookup[key] = entry

        # Restricted suppliers list
        self.restricted_suppliers = self.policies.get("restricted_suppliers", [])

        # Category rules indexed by (category_l1, category_l2)
        self.category_rules = {}
        for rule in self.policies.get("category_rules", []):
            key = (rule["category_l1"], rule["category_l2"])
            self.category_rules.setdefault(key, []).append(rule)

        # Geography rules indexed by country
        self.geography_rules_by_country = {}
        for rule in self.policies.get("geography_rules", []):
            if "country" in rule:
                self.geography_rules_by_country.setdefault(rule["country"], []).append(rule)
            elif "countries" in rule:
                for c in rule["countries"]:
                    self.geography_rules_by_country.setdefault(c, []).append(rule)

        # Escalation rules
        self.escalation_rules = self.policies.get("escalation_rules", [])

        # Historical awards by request_id
        self.historical_by_request = {}
        for _, row in self.historical_df.iterrows():
            rid = row["request_id"]
            self.historical_by_request.setdefault(rid, []).append(row.to_dict())

        # Historical awards by supplier_id
        self.historical_by_supplier = {}
        for _, row in self.historical_df.iterrows():
            sid = row["supplier_id"]
            self.historical_by_supplier.setdefault(sid, []).append(row.to_dict())


# Global singleton
data_store = DataStore()
