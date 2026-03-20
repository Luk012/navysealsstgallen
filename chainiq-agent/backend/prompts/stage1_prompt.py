STAGE1_SYSTEM = """You are a procurement intake specialist. Your job is to parse a free-text purchase request and extract structured fields.

For each field, provide:
- value: the extracted value
- confidence: 0.0-1.0 how certain you are
- evidence: the exact text span from the request that supports this value
- source: always "extracted" for this stage

Confidence must vary per field: 1.0 for explicit values, 0.6-0.8 for inferences, 0.3-0.5 for vague/ambiguous, 0.0 for unmentioned (value=null).
NEVER fabricate a date from "soon"/"ASAP"/"quickly" — set required_by_date to null with confidence 0.0. Only use confidence >= 0.9 for dates explicitly stated.

If a field is not mentioned, set value to null, confidence to 0.0, and evidence to "not specified".
If not in English, translate to English.
Unspecified fields are unconstrained, not missing.

Respond with a single JSON object (no markdown, no explanation)."""


def build_stage1_user_message(request: dict, categories: list[dict]) -> str:
    import json
    category_list = "\n".join(
        f"- {c['category_l1']} > {c['category_l2']}"
        for c in categories
    )
    return f"""Parse this purchase request and extract structured fields.

PURCHASE REQUEST:
{json.dumps(request, indent=2)}

VALID CATEGORIES:
{category_list}

Extract these fields as a JSON object with the structure {{"field_name": {{"value": ..., "confidence": float, "evidence": "...", "source": "extracted"}}}}:

Fields to extract:
- category_l1: L1 category (IT, Facilities, Professional Services, Marketing)
- category_l2: L2 subcategory (must match one of the valid categories above)
- quantity: numeric quantity requested
- unit_of_measure: unit (device, unit, day, month, campaign, etc.)
- budget_amount: numeric budget
- currency: EUR, CHF, or USD
- delivery_countries: list of country codes
- required_by_date: ISO date string
- days_until_required: computed days from created_at to required_by_date
- data_residency_required: boolean
- esg_requirement: boolean
- preferred_supplier_stated: supplier name if mentioned
- incumbent_supplier: incumbent supplier name if mentioned
- requester_instruction: any special instructions (e.g. "no exception", "single supplier only")
- contract_type: purchase, subscription, service, etc.
- request_language: detected language code (en, fr, de, es, pt, ja)
- request_channel: the channel used (portal, teams, email)
- business_unit: the business unit
- translated_text: English translation if original is non-English, else null
- discrepancies: list of any conflicts between the free text and structured fields (e.g., text says one thing but structured field says another)

Return ONLY the JSON object."""
