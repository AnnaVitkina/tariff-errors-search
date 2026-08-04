from __future__ import annotations

import re
from collections import Counter, defaultdict
from statistics import median
from typing import Any

from tariff_compare.models import Flag, RateRecord

_WEIGHT_LABEL_SKIP = frozenset(
    {"", "flat", "p/kg", "pkg", "per kg", "minimum", "min", "id", "n/a", "na"}
)


def _parse_bracket_number(label: Any) -> float | None:
    if label is None:
        return None
    s = str(label).strip().lower().replace(",", ".")
    if s in _WEIGHT_LABEL_SKIP:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", s)
    if not match:
        return None
    value = float(match.group(1))
    if value <= 0 or value > 50_000:
        return None
    return value


def _bracket_profile(labels: set[str]) -> dict[str, Any]:
    nums = sorted(
        n for n in (_parse_bracket_number(lb) for lb in labels) if n is not None
    )
    if len(nums) < 3:
        return {"kind": "insufficient", "count": len(nums), "nums": nums}

    unique = sorted(set(nums))
    diffs = [unique[i + 1] - unique[i] for i in range(len(unique) - 1)]
    med_step = median(diffs) if diffs else 0.0
    mult10_ratio = sum(1 for n in unique if abs(n % 10) < 0.001) / len(unique)
    non_mult10_ratio = 1.0 - mult10_ratio

    if med_step >= 5 and mult10_ratio >= 0.6:
        kind = "coarse_tens"
    elif med_step <= 2 and non_mult10_ratio >= 0.35 and len(unique) >= 8:
        kind = "fine_individual"
    else:
        kind = "other"

    return {
        "kind": kind,
        "step": float(med_step),
        "count": len(unique),
        "mult10_ratio": mult10_ratio,
        "nums": unique[:20],
    }


def _only_non_numeric_labels(labels: set[str]) -> bool:
    for label in labels:
        if _parse_bracket_number(label) is not None:
            return False
    return bool(labels)


def _collect_weight_breaks_by_scope(
    records: list[RateRecord],
) -> dict[tuple[str, str], set[str]]:
    scopes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rec in records:
        label = rec.meta.get("weight_break_label")
        if not label:
            continue
        scopes[(rec.block, rec.sheet)].add(str(label).strip())
    return scopes


def detect_weight_bracket_changes(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> list[Flag]:
    flags: list[Flag] = []
    old_scopes = _collect_weight_breaks_by_scope(old_records)
    new_scopes = _collect_weight_breaks_by_scope(new_records)

    def _maybe_flag(
        *,
        block: str,
        sheet: str,
        old_labels: set[str],
        new_labels: set[str],
    ) -> None:
        old_prof = _bracket_profile(old_labels)
        new_prof = _bracket_profile(new_labels)

        old_numeric = old_prof["count"] >= 3
        new_numeric = new_prof["count"] >= 3

        old_coarse = old_prof["kind"] == "coarse_tens" or (
            old_prof["kind"] == "other"
            and old_prof["step"] >= 8
            and old_prof["count"] >= 3
        )
        new_fine = new_prof["kind"] == "fine_individual" or (
            new_prof["kind"] == "other"
            and new_prof["step"] <= 2
            and new_prof["count"] >= 10
        )
        new_coarse = new_prof["kind"] == "coarse_tens" or (
            new_prof["kind"] == "other"
            and new_prof["step"] >= 5
            and new_prof["count"] >= 3
        )

        granularity_jump = (
            old_coarse
            and new_fine
            and new_prof["count"] >= max(old_prof["count"] * 2, 8)
        )
        tens_to_singles = (
            old_prof["kind"] == "coarse_tens"
            and new_prof["kind"] == "fine_individual"
        )
        non_numeric_to_numeric = (
            _only_non_numeric_labels(old_labels)
            and new_numeric
            and new_prof["count"] >= 5
        )
        coarse_to_fine_cross_layout = (
            not old_numeric
            and new_fine
            and new_prof["count"] >= 8
        )

        if not any(
            [
                granularity_jump,
                tens_to_singles,
                non_numeric_to_numeric and new_coarse,
                coarse_to_fine_cross_layout,
            ]
        ):
            return

        old_samples = ", ".join(sorted(old_labels)[:8]) or "(none)"
        new_nums = new_prof.get("nums", [])
        new_samples = ", ".join(str(n) for n in new_nums[:12]) or ", ".join(
            sorted(new_labels)[:8]
        )
        flags.append(
            Flag(
                rule_id="WEIGHT_BRACKET_GRANULARITY_CHANGED",
                severity="red_flag",
                lane_key=f"{block}|{sheet}|weight_breaks",
                message=(
                    f"Weight bracket logic changed ({block} / «{sheet}»): "
                    f"OLD breaks [{old_samples}] → NEW numeric bands "
                    f"(~{new_prof['step']:.1f} kg step, e.g. {new_samples}…)."
                ),
                old_value=f"{old_prof['count']} numeric brackets" if old_numeric else str(sorted(old_labels)[:10]),
                new_value=f"{new_prof['count']} brackets, step ~{new_prof['step']:.1f}",
                block=block,
                sheet=sheet,
                where_to_look_old=f"Sheet «{sheet}» or equivalent rate matrix in OLD file — header row",
                where_to_look_new=f"Sheet «{sheet}» or equivalent rate matrix in NEW file — header row",
                action_hint=(
                    "Compare weight-break column headers. A move from 10/20/30 kg bands to "
                    "11/12/13… kg (or from Flat/p/kg labels to per-kg numeric columns) changes "
                    "rating granularity — confirm with carrier and update the rating engine."
                ),
            )
        )

    for scope in sorted(set(old_scopes) & set(new_scopes)):
        block, sheet = scope
        _maybe_flag(
            block=block,
            sheet=sheet,
            old_labels=old_scopes[scope],
            new_labels=new_scopes[scope],
        )

    # Cross-layout: same charge_kind block but different sheet names (e.g. migration).
    old_by_block: dict[str, set[str]] = defaultdict(set)
    new_by_block: dict[str, set[str]] = defaultdict(set)
    for (block, _sheet), labels in old_scopes.items():
        old_by_block[block].update(labels)
    for (block, _sheet), labels in new_scopes.items():
        new_by_block[block].update(labels)

    for block in sorted(set(old_by_block) & set(new_by_block)):
        block_sheet_overlap = any(
            (block, sheet) in old_scopes and (block, sheet) in new_scopes
            for sheet in {s for (b, s) in old_scopes if b == block}
            | {s for (b, s) in new_scopes if b == block}
        )
        if block_sheet_overlap:
            continue
        sheet = next(
            (s for (b, s) in new_scopes if b == block),
            next((s for (b, s) in old_scopes if b == block), block),
        )
        _maybe_flag(
            block=block,
            sheet=sheet,
            old_labels=old_by_block[block],
            new_labels=new_by_block[block],
        )

    return flags


def _norm_country(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip().upper()
    if not s:
        return None
    if len(s) == 2 and s.isalpha():
        return s
    match = re.match(r"^([A-Z]{2})\b", s)
    if match:
        return match.group(1)
    return s[:3]


def _infer_country_from_location(loc: Any) -> str | None:
    if loc is None:
        return None
    s = str(loc).strip().upper()
    match = re.match(r"^([A-Z]{2})[-\s_/]", s)
    if match:
        return match.group(1)
    return None


def _collect_countries(records: list[RateRecord]) -> set[str]:
    countries: set[str] = set()
    for rec in records:
        for field in ("origin_country", "dest_country"):
            norm = _norm_country(rec.meta.get(field))
            if norm:
                countries.add(norm)
        for field in ("origin_location", "dest_location"):
            inferred = _infer_country_from_location(rec.meta.get(field))
            if inferred:
                countries.add(inferred)
    return countries


def _is_postal_like(loc: str) -> bool:
    s = str(loc).strip()
    if not s or len(s) > 30:
        return False
    if re.match(r"^[A-Z]{2}[-\s]?\d", s, re.I):
        return True
    if re.match(r"^\d{2,6}$", s):
        return True
    if re.match(r"^[A-Z]{2}\d{2,5}$", s, re.I):
        return True
    return False


def _digits_only(loc: str) -> str:
    return re.sub(r"\D", "", str(loc))


def _postal_format_signature(locations: list[str]) -> dict[str, Any]:
    postal = [str(x).strip() for x in locations if _is_postal_like(x)]
    if len(postal) < 5:
        return {"count": len(postal)}

    digit_lens = [_digits_only(p) for p in postal if _digits_only(p)]
    if not digit_lens:
        return {"count": len(postal)}

    len_counts = Counter(len(d) for d in digit_lens)
    dominant_len, dominant_n = len_counts.most_common(1)[0]
    leading_zero_ratio = sum(1 for d in digit_lens if d.startswith("0")) / len(digit_lens)

    return {
        "count": len(postal),
        "dominant_digit_len": dominant_len,
        "dominant_len_share": dominant_n / len(digit_lens),
        "leading_zero_ratio": leading_zero_ratio,
        "sample": sorted(set(postal))[:8],
    }


def _locations_by_country(records: list[RateRecord]) -> dict[str, list[str]]:
    by_country: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        country = (
            _norm_country(rec.meta.get("dest_country"))
            or _infer_country_from_location(rec.meta.get("dest_location"))
            or "_global"
        )
        for field in ("dest_location", "origin_location"):
            loc = rec.meta.get(field)
            if loc and _is_postal_like(str(loc)):
                by_country[country].append(str(loc).strip())
    return by_country


def detect_zone_and_country_changes(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> list[Flag]:
    flags: list[Flag] = []
    old_countries = _collect_countries(old_records)
    new_countries = _collect_countries(new_records)

    for country in sorted(new_countries - old_countries):
        flags.append(
            Flag(
                rule_id="NEW_COUNTRY_IN_TARIFF",
                severity="red_flag",
                lane_key=f"zone|country|{country}",
                message=f"New country/region code appears in NEW tariff: {country}",
                new_value=country,
                block="zone",
                sheet="",
                where_to_look_new="Rate card / zone sheets — country or region columns",
                action_hint=(
                    "Confirm whether service to this country is intentional. "
                    "Update zone tables and customs/compliance rules if needed."
                ),
            )
        )

    for country in sorted(old_countries - new_countries):
        flags.append(
            Flag(
                rule_id="COUNTRY_REMOVED_FROM_TARIFF",
                severity="review",
                lane_key=f"zone|country|{country}",
                message=f"Country/region code present in OLD but not in NEW: {country}",
                old_value=country,
                block="zone",
                sheet="",
                where_to_look_old="Rate card / zone sheets — country or region columns",
                action_hint="Verify the country was deliberately dropped from coverage.",
            )
        )

    old_locs = _locations_by_country(old_records)
    new_locs = _locations_by_country(new_records)

    for country in sorted(set(old_locs) & set(new_locs)):
        old_sig = _postal_format_signature(old_locs[country])
        new_sig = _postal_format_signature(new_locs[country])
        if old_sig.get("count", 0) < 5 or new_sig.get("count", 0) < 5:
            continue

        old_len = old_sig.get("dominant_digit_len")
        new_len = new_sig.get("dominant_digit_len")
        old_share = old_sig.get("dominant_len_share", 0)
        new_share = new_sig.get("dominant_len_share", 0)
        old_lz = old_sig.get("leading_zero_ratio", 0)
        new_lz = new_sig.get("leading_zero_ratio", 0)

        format_changed = (
            old_len is not None
            and new_len is not None
            and old_len != new_len
            and old_share >= 0.5
            and new_share >= 0.5
        )
        leading_zero_changed = abs(old_lz - new_lz) >= 0.25 and (
            old_lz >= 0.2 or new_lz >= 0.2
        )

        if not (format_changed or leading_zero_changed):
            continue

        country_label = "all zones" if country == "_global" else country
        flags.append(
            Flag(
                rule_id="POSTAL_ZONE_FORMAT_CHANGED",
                severity="red_flag",
                lane_key=f"zone|postal|{country}",
                message=(
                    f"Postal / zone code format changed ({country_label}): "
                    f"dominant digit length {old_len} → {new_len} "
                    f"(e.g. OLD {old_sig.get('sample', [])} vs NEW {new_sig.get('sample', [])})."
                ),
                old_value=f"len={old_len}, leading_zero={old_lz:.0%}",
                new_value=f"len={new_len}, leading_zero={new_lz:.0%}",
                block="zone",
                sheet="",
                where_to_look_old=f"Zone / destination columns ({country_label}) in OLD file",
                where_to_look_new=f"Zone / destination columns ({country_label}) in NEW file",
                action_hint=(
                    "Check whether postcodes were truncated or reformatted "
                    "(e.g. 07865 → 07 or 7865). Remap zones in the rating engine."
                ),
            )
        )

    old_zone_keys = {
        str(rec.meta.get("dest_location") or "").strip().lower()
        for rec in old_records
        if rec.meta.get("dest_location")
    }
    new_zone_keys = {
        str(rec.meta.get("dest_location") or "").strip().lower()
        for rec in new_records
        if rec.meta.get("dest_location")
    }
    new_zones_only = sorted(new_zone_keys - old_zone_keys)
    if len(new_zones_only) >= 3:
        flags.append(
            Flag(
                rule_id="NEW_POSTAL_ZONES",
                severity="review",
                lane_key="zone|postal|*",
                message=(
                    f"{len(new_zones_only)} new destination/postal zone codes in NEW file "
                    f"(e.g. {', '.join(new_zones_only[:5])}…)."
                ),
                new_value=", ".join(new_zones_only[:10]),
                block="zone",
                sheet="",
                where_to_look_new="Destination / postal code columns in NEW workbook",
                action_hint="Review Added sheet and zone mapping tables for new coverage areas.",
            )
        )

    return flags


_APPLICABILITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("stacked_on_accessorial", re.compile(r"(?i)on top of|in addition to|including\s+accessorial|stacked")),
    ("excluding_accessorial", re.compile(r"(?i)exclud(e|ing)\s+accessorial|without\s+accessorial|excluding\s+acc")),
    ("fuel_on_total", re.compile(r"(?i)fsc.*(total|gross)|fuel.*(total|gross)\s+charge|applied?\s+on\s+total")),
    ("fuel_on_base_only", re.compile(r"(?i)fsc.*(base|net)|fuel.*(base|net)\s+rate|applied?\s+on\s+base")),
    ("fuel_index_formula", re.compile(r"(?i)fuel\s*surcharge|fsc|diesel\s*index|national\s+fuel")),
]


def _applicability_signature(records: list[RateRecord]) -> dict[str, Any]:
    fuel_bases = sorted(
        {
            str(r.billing_basis)
            for r in records
            if r.block == "fuel" and r.billing_basis
        }
    )
    patterns_hit: set[str] = set()
    snippets: list[str] = []

    for rec in records:
        is_fuel = rec.block == "fuel"
        is_acc = rec.block == "accessorial"
        is_logic = rec.record_type == "contract_logic"
        if not (is_fuel or is_acc or is_logic):
            continue

        parts = [
            rec.text_value or "",
            str(rec.meta.get("logic_label") or ""),
            str(rec.meta.get("charge_id") or ""),
            str(rec.billing_basis or ""),
        ]
        text = " ".join(p for p in parts if p).strip()
        if not text:
            continue
        lower = text.lower()
        if not (is_fuel or "fuel" in lower or "fsc" in lower or is_acc):
            if not is_logic:
                continue

        for name, rx in _APPLICABILITY_PATTERNS:
            if rx.search(text):
                patterns_hit.add(name)
                if len(snippets) < 4:
                    snippets.append(text[:120])

    return {
        "fuel_billing_basis": fuel_bases,
        "patterns": sorted(patterns_hit),
        "snippets": snippets,
    }


def detect_cost_applicability_changes(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> list[Flag]:
    flags: list[Flag] = []
    old_sig = _applicability_signature(old_records)
    new_sig = _applicability_signature(new_records)

    if not old_sig["patterns"] and not new_sig["patterns"] and not old_sig["fuel_billing_basis"]:
        return flags

    old_patterns = set(old_sig["patterns"])
    new_patterns = set(new_sig["patterns"])

    stacking_changed = (
        ("stacked_on_accessorial" in new_patterns and "stacked_on_accessorial" not in old_patterns)
        or ("stacked_on_accessorial" in old_patterns and "stacked_on_accessorial" not in new_patterns)
    )
    exclusion_changed = (
        ("excluding_accessorial" in new_patterns and "excluding_accessorial" not in old_patterns)
        or ("excluding_accessorial" in old_patterns and "excluding_accessorial" not in new_patterns)
    )
    basis_text_changed = (
        ("fuel_on_total" in new_patterns and "fuel_on_base_only" in old_patterns)
        or ("fuel_on_base_only" in new_patterns and "fuel_on_total" in old_patterns)
    )
    fuel_basis_changed = old_sig["fuel_billing_basis"] != new_sig["fuel_billing_basis"] and (
        old_sig["fuel_billing_basis"] and new_sig["fuel_billing_basis"]
    )

    if not any(
        [stacking_changed, exclusion_changed, basis_text_changed, fuel_basis_changed]
    ):
        return flags

    parts: list[str] = []
    if stacking_changed:
        parts.append("FSC / surcharge stacking on accessorials changed")
    if exclusion_changed:
        parts.append("whether accessorials are included/excluded from FSC base changed")
    if basis_text_changed:
        parts.append("FSC applied on total vs base rate wording changed")
    if fuel_basis_changed:
        parts.append(
            f"fuel billing basis {old_sig['fuel_billing_basis']} → {new_sig['fuel_billing_basis']}"
        )

    flags.append(
        Flag(
            rule_id="COST_APPLICABILITY_CHANGED",
            severity="red_flag",
            lane_key="fuel|applicability",
            message="; ".join(parts) + ".",
            old_value={
                "patterns": old_sig["patterns"],
                "fuel_billing_basis": old_sig["fuel_billing_basis"],
                "sample": old_sig["snippets"][:2],
            },
            new_value={
                "patterns": new_sig["patterns"],
                "fuel_billing_basis": new_sig["fuel_billing_basis"],
                "sample": new_sig["snippets"][:2],
            },
            block="fuel",
            sheet="Fuel",
            where_to_look_old="Sheet «Fuel» / accessorial notes / contract logic in OLD file",
            where_to_look_new="Sheet «Fuel» / accessorial notes / contract logic in NEW file",
            action_hint=(
                "Confirm with carrier whether FSC is applied on base rate only, on total "
                "including new accessorials (ACC), or excluding prior surcharges. "
                "Update billing system stacking rules for DHL/FSC if needed."
            ),
        )
    )
    return flags


def apply_structural_rules(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> list[Flag]:
    flags: list[Flag] = []
    flags.extend(detect_weight_bracket_changes(old_records, new_records))
    flags.extend(detect_zone_and_country_changes(old_records, new_records))
    flags.extend(detect_cost_applicability_changes(old_records, new_records))
    return flags
