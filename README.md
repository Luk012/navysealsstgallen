# Audit-Ready Autonomous Sourcing Agent
Hackathon Dataset

This repository contains the dataset for the **Audit-Ready Autonomous Sourcing Agent** challenge.

The objective is to design a system that converts **unstructured purchase requests** into a **structured, compliant supplier comparison** with transparent reasoning and escalation logic.

Participants should focus on **reasoning architecture, rule enforcement, and explainability** - not just generating answers.

---

## Dataset Overview

The dataset simulates a global enterprise procurement environment spanning 19 countries, 3 currencies, and 4 procurement categories.

Participants must combine **six datasets** to evaluate sourcing decisions.

| File | Records | Description |
|------|---------|-------------|
| `requests.json` | 304 | Unstructured purchase requests submitted by internal stakeholders |
| `suppliers.csv` | 151 rows / 40 suppliers | Supplier master data including capabilities, risk indicators, and restrictions |
| `pricing.csv` | 599 | Supplier pricing tiers and delivery performance |
| `categories.csv` | 30 | Category taxonomy with typical units and pricing models |
| `policies.json` | 6 sections | Procurement rules, approval thresholds, and escalation logic |
| `historical_awards.csv` | 590 | Historical sourcing decisions for use as contextual precedent |

The datasets are intentionally simplified but designed to replicate common procurement decision patterns found in real enterprise environments.

---

## Scenario Context

Large organisations receive thousands of purchase requests each year. These requests are typically:

- written in free text, sometimes in languages other than English
- incomplete, ambiguous, or internally contradictory
- influenced by requester supplier preferences that may conflict with policy
- subject to approval thresholds, category rules, and compliance constraints

Procurement professionals must interpret these requests, apply internal governance rules, compare suppliers, and justify every decision during audits.

The goal of this challenge is to design a system capable of performing this reasoning automatically, in a way that produces transparent, auditable outputs.

---

## Dataset Structure

### requests.json

Represents stakeholder purchase requests. These are **intentionally messy and human-written**. They contain the kinds of ambiguities, contradictions, and omissions that real procurement teams deal with daily.

Key fields:

| Field | Description |
|-------|-------------|
| `request_id` | Unique identifier (REQ-000001 format) |
| `created_at` | Request creation timestamp (ISO 8601) |
| `request_channel` | Submission channel: `portal`, `teams`, or `email` |
| `request_language` | Language of request text: `en`, `fr`, `de`, `es`, `pt`, `ja` |
| `business_unit` | Internal department requesting the purchase |
| `country` | Country where the requester is based |
| `category_l1` | High-level category: IT / Facilities / Professional Services / Marketing |
| `category_l2` | Detailed subcategory (e.g. Laptops, Cloud Compute, Data Engineering Services) |
| `request_text` | Original free-text request description |
| `quantity` | Requested quantity (may be null or inconsistent with request_text) |
| `unit_of_measure` | Unit for the quantity field |
| `currency` | Budget currency: `EUR`, `CHF`, or `USD` |
| `budget_amount` | Budget amount in the stated currency (may be null) |
| `required_by_date` | Requested delivery or start date |
| `preferred_supplier_mentioned` | Supplier named by the requester (may be wrong category, wrong region, or restricted) |
| `incumbent_supplier` | Currently contracted supplier for this category, if any |
| `delivery_countries` | List of countries where goods/services must be delivered |
| `data_residency_constraint` | True if data must remain in-country |
| `esg_requirement` | True if the requester has specified an ESG/sustainability requirement |
| `scenario_tags` | List of scenario labels - see Scenario Types below |

---

### suppliers.csv

Supplier master data. Each supplier may appear on multiple rows, one per category served.

Key fields:

| Field | Description |
|-------|-------------|
| `supplier_id` | Unique identifier (SUP-0001 format) |
| `supplier_name` | Supplier name |
| `category_l1` / `category_l2` | Category this row covers |
| `country_hq` | Country of supplier headquarters |
| `service_regions` | Semicolon-delimited list of countries the supplier serves |
| `currency` | Currency in which this supplier prices and contracts |
| `pricing_model` | Pricing model: `tiered`, `fixed`, `usage`, `subscription`, `day_rate`, `blended_rate`, `performance` |
| `quality_score` | Supplier quality rating (0–100) |
| `risk_score` | Operational risk indicator - lower is better |
| `esg_score` | Sustainability rating (0–100) |
| `preferred_supplier` | `True` if this supplier is on the preferred list for this category |
| `is_restricted` | `True` if a policy restriction applies to this supplier for this category. **Always cross-reference with `policies.json` `restricted_suppliers`** - a False flag does not guarantee the supplier is unrestricted in all countries or above all value thresholds |
| `restriction_reason` | Human-readable note where a restriction applies or is conditional |
| `capacity_per_month` | Maximum units the supplier can fulfil per month across all categories |

> **Note on `is_restricted`:** The flag indicates a general restriction. Country-scoped and value-conditional restrictions (e.g. a supplier restricted only in specific countries, or only above a given contract value) are defined in `policies.json` and take precedence. Always check both.

---

### pricing.csv

Supplier pricing by volume tier and delivery speed.

Key fields:

| Field | Description |
|-------|-------------|
| `pricing_id` | Unique identifier (PR-00001 format) |
| `supplier_id` | Reference to suppliers.csv |
| `category_l1` / `category_l2` | Category this pricing row covers |
| `region` | Region this pricing applies to: `EU`, `Americas`, `APAC`, `MEA` |
| `currency` | Pricing currency |
| `pricing_model` | Must match suppliers.csv |
| `min_quantity` / `max_quantity` | Quantity range for this tier |
| `unit_price` | Price per unit in this tier |
| `moq` | Minimum order quantity |
| `standard_lead_time_days` | Standard delivery lead time |
| `expedited_lead_time_days` | Expedited delivery option |
| `expedited_unit_price` | Price per unit for expedited delivery (~8% premium) |
| `valid_from` / `valid_to` | Pricing validity window (all rows valid 2026-01-01 to 2026-12-31) |

Determine the correct pricing tier by matching `quantity` against `min_quantity`/`max_quantity`. For hardware suppliers, four tiers exist: 1–99, 100–499, 500–1999, 2000+.

---

### categories.csv

Category reference data. 30 rows covering all L1/L2 category combinations.

| Field | Description |
|-------|-------------|
| `category_l1` / `category_l2` | Category identifiers |
| `category_description` | Plain-language description of what this category covers |
| `typical_unit` | Standard unit of measure |
| `pricing_model` | Expected pricing model for this category |

---

### policies.json

Defines procurement governance rules. Six top-level sections:

#### `approval_thresholds`
Determines the approval level and number of quotes required based on contract value. Thresholds exist for EUR, CHF, and USD.

| Tier | EUR | CHF | USD | Quotes | Approver |
|------|-----|-----|-----|--------|----------|
| 1 | < 25K | < 27.5K | < 27K | 1 | Business |
| 2 | 25K–100K | 27.5K–110K | 27K–108K | 2 | Business + Procurement |
| 3 | 100K–500K | 110K–550K | 108K–540K | 3 | Head of Category |
| 4 | 500K–5M | 550K–5.5M | 540K–5.4M | 3 | Head of Strategic Sourcing |
| 5 | > 5M | > 5.5M | > 5.4M | 3 | CPO |

#### `preferred_suppliers`
Lists preferred supplier / category / region combinations. Preferred status means the supplier should be used where they are commercially competitive and policy-compliant. It is not a mandate.

#### `restricted_suppliers`
Lists suppliers with restrictions on use. Restrictions may be:
- **Global** - supplier cannot be used in this category without exception approval
- **Country-scoped** - supplier is restricted in specific countries only
- **Value-conditional** - supplier can be used below a value threshold without exception, but requires approval above it

Always apply the most specific restriction that matches the request context.

#### `category_rules`
Category-specific sourcing constraints such as mandatory competitive comparison, security review requirements, engineering sign-off, CV review, and brand safety checks.

#### `geography_rules`
Region-specific requirements including data sovereignty rules for CH, US, APAC, MEA, and LATAM. Verify applicable rules based on `delivery_countries`.

#### `escalation_rules`
Defines when an automated decision is insufficient and human escalation is required:

| Rule | Trigger | Target |
|------|---------|--------|
| ER-001 | Missing required information (budget, quantity, spec) | Requester |
| ER-002 | Preferred supplier is restricted | Procurement Manager |
| ER-003 | Contract value exceeds tier threshold | Head of Strategic Sourcing |
| ER-004 | No compliant supplier can be identified | Head of Category |
| ER-005 | Data residency constraint cannot be satisfied | Security/Compliance |
| ER-006 | Requested quantity exceeds supplier monthly capacity | Sourcing Excellence Lead |
| ER-007 | Brand safety concern in Marketing category | Marketing Governance Lead |
| ER-008 | Supplier not registered or sanction-screened in delivery country | Regional Compliance Lead |

---

### historical_awards.csv

Contains past sourcing decisions across 180 of the 304 requests. Not every request has a historical award - this is intentional and realistic.

Key fields:

| Field | Description |
|-------|-------------|
| `award_id` | Unique identifier (AWD-000001 format) |
| `request_id` | Reference to requests.json |
| `award_date` | Date the sourcing decision was made (note: this is decision date, not delivery date) |
| `supplier_id` / `supplier_name` | Supplier that was evaluated |
| `total_value` | Total contract value for this supplier's bid |
| `awarded` | `True` for the selected supplier, `False` for evaluated alternatives |
| `award_rank` | Rank in the shortlist (1 = recommended) |
| `decision_rationale` | Brief rationale for placement |
| `policy_compliant` | Whether this bid was assessed as policy-compliant |
| `preferred_supplier_used` | Whether the awarded supplier was the preferred supplier |
| `escalation_required` | Whether this award required escalation |
| `escalated_to` | Escalation target if applicable |
| `savings_pct` | Savings percentage achieved by the winning bid vs. budget |
| `lead_time_days` | Lead time quoted by this supplier |

Historical data should be used as **contextual precedent** only. It illustrates typical decision patterns but does not represent ground truth for evaluation.

---

## Scenario Types

Requests are tagged with one or more `scenario_tags` indicating the type of challenge they present:

| Tag | Description | Count |
|-----|-------------|-------|
| `standard` | Well-formed request with sufficient information and no conflicts | 141 |
| `threshold` | Budget sits at or near a policy approval boundary - tier determination requires care | 29 |
| `lead_time` | Delivery deadline is critically short - standard lead time is insufficient | 29 |
| `missing_info` | Budget amount or quantity is null - agent must escalate to requester | 28 |
| `contradictory` | Request contains an internal conflict: quantity in text differs from field, budget is insufficient for stated spec, or requester explicitly refuses policy-required steps | 21 |
| `restricted` | Preferred supplier is restricted, wrong category, or geographically out of scope | 18 |
| `multilingual` | Request text is in a language other than English, or delivery spans multiple countries with different regulatory requirements | 18 |
| `capacity` | Requested quantity exceeds the preferred or only viable supplier's monthly capacity | 18 |
| `multi_country` | Delivery is required in multiple countries with different compliance, data residency, or language requirements | 3 |

> **On `threshold`:** This tag means the request value crosses into or sits close to an elevated approval tier - not that it is unambiguously borderline. Approximately half the threshold-tagged requests sit within a few percent of a boundary and require careful tier determination. The remainder are clearly in a higher tier and require the corresponding approval and quote count.

> **On `multilingual`:** Some requests in this group have `request_language` set to a non-English language (`fr`, `de`, `es`, `pt`, `ja`) - the request_text will be in that language. Others have `request_language='en'` but involve multi-country delivery with different regulatory or language requirements per country.

> **On `restricted`:** The `preferred_supplier_mentioned` field may name a supplier that is restricted under policy, is registered for a different category entirely, does not cover the delivery country, or requires exception approval above a certain value. Agents must detect and handle all of these cases.

---

## Geographic Coverage

| Region | Countries | Currency |
|--------|-----------|----------|
| Western Europe | DE, FR, NL, BE, AT, IT, ES, PL, UK | EUR |
| Switzerland | CH | CHF |
| Americas | US, CA, BR, MX | USD |
| APAC | SG, AU, IN, JP | USD |
| MEA | UAE, ZA | USD |

USD approval thresholds apply to all Americas, APAC, and MEA requests. Verify applicable geography rules in `policies.json` before finalising recommendations for regulated categories.

---

## Challenge Objective

Your system should demonstrate the ability to:

1. **Interpret** unstructured purchase requests, including non-English text
2. **Extract** structured requirements: category, quantity, budget, delivery constraints
3. **Validate** the request for completeness and internal consistency
4. **Apply** procurement policy rules: approval thresholds, preferred/restricted suppliers, category rules, geography rules
5. **Identify** compliant suppliers covering the delivery country, category, and currency
6. **Rank** suppliers using pricing, quality, risk, and ESG data
7. **Explain** the reasoning behind each recommendation in auditable terms
8. **Escalate** when policy conditions require human involvement, naming the correct escalation target

---

## Expected Output

Participants should demonstrate a system capable of producing, for each request:

- A structured interpretation of the request (category, quantity, budget, constraints)
- Detection of any missing information, contradictions, or policy conflicts
- A compliant supplier shortlist with pricing calculated at the correct tier
- A ranked supplier comparison with scoring criteria made explicit
- Clear, auditable reasoning explaining why each supplier was included or excluded
- Escalation notice where required, specifying the trigger rule and target

---

## Evaluation Focus

Solutions will be evaluated primarily on:

- **Reasoning clarity** - can an auditor follow the decision logic without prior knowledge of the system?
- **Rule enforcement** - are all applicable policy rules detected and applied correctly?
- **Edge case robustness** - how does the system handle contradictory, incomplete, or restricted scenarios?
- **Escalation accuracy** - are escalations triggered at the right threshold and routed to the correct target?
- **Architecture feasibility** - is the system design practical and extensible?

Interface polish or the use of large models alone will not score highly. A system that produces confident wrong answers will score lower than one that correctly identifies uncertainty and escalates.

---

## Known Data Characteristics

The following characteristics are present by design and should be handled by your system:

- **Preferred supplier category mismatch:** Some requests name a preferred supplier registered in a different procurement category. The system must detect this and discard the preference.
- **Preferred supplier geographic mismatch:** Some preferred suppliers do not cover the delivery country.
- **Conditional restrictions:** Some suppliers carry restrictions that only apply above a value threshold or in specific countries. The `is_restricted` flag in `suppliers.csv` is a hint - always check `policies.json` for the full restriction definition.
- **Quantity/text discrepancies:** Some requests have a numeric `quantity` field that conflicts with the quantity stated in `request_text`. Both should be surfaced.
- **Award dates vs. delivery dates:** `award_date` in `historical_awards.csv` represents the date the sourcing decision was made, not the delivery date. Late awards relative to `required_by_date` reflect normal procurement process delays and are not data errors.
- **Requests without historical awards:** 124 of 304 requests have no award records. This reflects a realistic pipeline where many requests are still in progress. Do not treat the absence of an award record as an error signal.

---

*This dataset is a simplified representation of real enterprise procurement environments. The challenge focuses on governed AI decision-making, not building a full procurement platform.*
# navysealsstgallen
