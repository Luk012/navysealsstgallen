import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT.parent / "data"

# Anthropic API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Model selection
MODEL_EXTRACTION = "claude-sonnet-4-6"      # Stage 1: fast extraction
MODEL_REASONING = "claude-sonnet-4-6"    # Stage 2: policy reasoning
MODEL_MASTERMIND = "claude-sonnet-4-6"   # Stage 3: approval authority
MODEL_RANKING = "claude-sonnet-4-6"      # Stage 4/Branch A: ranking explanation

# Pipeline constants
MAX_ITERATIONS = 3          # Max Stage 2-3 loops
MIN_SUPPLIER_QUOTES_DEFAULT = 3  # Default K for Branch A/B threshold
CONFIDENCE_THRESHOLD = 0.5  # Below this, flag for escalation

# Constraint weights
WEIGHT_HARD = float("inf")
WEIGHT_EXPENSIVE = 1000
WEIGHT_MODERATE = 100
WEIGHT_CHEAP = 10

# Country to pricing region mapping
COUNTRY_TO_REGION = {
    "DE": "EU", "FR": "EU", "NL": "EU", "BE": "EU", "AT": "EU",
    "IT": "EU", "ES": "EU", "PL": "EU", "UK": "EU", "CH": "EU",
    "US": "Americas", "CA": "Americas", "BR": "Americas", "MX": "Americas",
    "SG": "APAC", "AU": "APAC", "IN": "APAC", "JP": "APAC",
    "UAE": "MEA", "ZA": "MEA",
}

# Country to currency mapping
COUNTRY_TO_CURRENCY = {
    "DE": "EUR", "FR": "EUR", "NL": "EUR", "BE": "EUR", "AT": "EUR",
    "IT": "EUR", "ES": "EUR", "PL": "EUR", "UK": "EUR",
    "CH": "CHF",
    "US": "USD", "CA": "USD", "BR": "USD", "MX": "USD",
    "SG": "USD", "AU": "USD", "IN": "USD", "JP": "USD",
    "UAE": "USD", "ZA": "USD",
}
