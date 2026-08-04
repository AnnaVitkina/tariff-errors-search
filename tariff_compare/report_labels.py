from __future__ import annotations

# Plain-language labels for report consumers (non-technical users).

RULE_TITLES: dict[str, str] = {
    "LOGIC_REMOVED_IN_NEW_FILE": "Calculation rule removed",
    "LOGIC_TEXT_CHANGED": "Calculation rule wording changed",
    "LOGIC_ADDED_IN_NEW_FILE": "New calculation rule",
    "MASS_LANE_REMOVAL": "Many lanes removed",
    "MASS_LANE_ADDITION": "Many new lanes",
    "PRICE_CHANGE_EXTREME": "Very large price change",
    "BILLING_BASIS_CHANGED": "How the charge is billed changed",
    "CALCULATION_METHOD_CHANGED": "How to apply the rate changed",
    "FUEL_TABLE_REDESIGN": "Fuel surcharge table redesigned",
    "MATRIX_LAYOUT_CHANGED": "Rate matrix layout changed",
    "NEW_BLOCK": "New type of charge section",
    "NEW_ZONE_MAPPING": "New remote / island zones",
    "NEW_COST": "New accessorial charge",
    "REMOVED_COST": "Accessorial charge removed",
    "WEIGHT_BRACKET_GRANULARITY_CHANGED": "Weight bracket steps changed",
    "NEW_COUNTRY_IN_TARIFF": "New country in tariff",
    "COUNTRY_REMOVED_FROM_TARIFF": "Country removed from tariff",
    "POSTAL_ZONE_FORMAT_CHANGED": "Postal / zone code format changed",
    "NEW_POSTAL_ZONES": "New postal / zone codes",
    "COST_APPLICABILITY_CHANGED": "Fuel surcharge applicability changed",
    "EXTRACTION_EMPTY_OLD": "Previous file could not be read",
    "EXTRACTION_EMPTY_NEW": "New file could not be read",
    "EXTRACTION_LOADED": "Comparison completed",
}

BLOCK_TITLES: dict[str, str] = {
    "base_rate": "Base transport rate",
    "accessorial": "Accessorial / surcharge",
    "fuel": "Fuel surcharge",
    "linehaul": "Linehaul",
    "contract_logic": "Calculation rule",
    "zone": "Zone / country",
    "other": "Other charge",
    "summary": "Overall",
    "extraction": "File read",
}

PRIORITY_CRITICAL = "Critical - action required"
PRIORITY_CHECK = "Please review"
PRIORITY_INFO = "Information only"

# Internal / noisy rules — not shown on the main findings sheet.
HIDDEN_FROM_FINDINGS = frozenset({"EXTRACTION_LOADED"})


def rule_title(rule_id: str) -> str:
    return RULE_TITLES.get(rule_id, rule_id.replace("_", " ").title())


def block_title(block: str) -> str:
    return BLOCK_TITLES.get(block, block.replace("_", " ").title())


def priority_label(severity: str) -> str:
    if severity == "red_flag":
        return PRIORITY_CRITICAL
    if severity == "review":
        return PRIORITY_CHECK
    return PRIORITY_INFO
