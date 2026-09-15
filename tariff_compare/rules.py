from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tariff_compare.diff_engine import DiffResult
from tariff_compare.models import Flag, RateRecord
from tariff_compare.structural_rules import apply_structural_rules


def load_thresholds(path: Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _where_from_record(rec: RateRecord | None) -> str:
    if rec is None:
        return "(not present in file)"
    cell = rec.meta.get("excel_cell", "")
    row = rec.meta.get("excel_row", "")
    col = rec.meta.get("excel_col", "")
    parts = [f"Sheet «{rec.sheet}»"]
    if cell:
        parts.append(f"cell {cell}")
    elif row:
        parts.append(f"row {row}, col {col}")
    if rec.meta.get("source_file"):
        parts.append(f"file: {rec.meta['source_file']}")
    return " | ".join(parts)


def _logic_records(records: list[RateRecord]) -> dict[str, RateRecord]:
    return {
        r.lane_key: r
        for r in records
        if r.record_type == "contract_logic"
    }


# Review-level field tracking: set changes + remaps on same lane identity.
# Each entry: meta field(s), rule id, human label, column hint for "where to look".
_CODE_FIELD_CHECKS: tuple[dict[str, Any], ...] = (
    {
        "fields": ("charge_id",),
        "rule_id": "CHARGE_CODE_CHANGED",
        "label": "Charge codes",
        "column_hint": "charge code / Charge ID column",
        "lane_prefix": "charge_code",
    },
    {
        "fields": ("service_level",),
        "rule_id": "SERVICE_CODE_CHANGED",
        "label": "Service codes",
        "column_hint": "service / service level / service code column",
        "lane_prefix": "service_code",
    },
    {
        "fields": ("origin_location", "dest_location"),
        "rule_id": "POSTAL_CODE_CHANGED",
        "label": "Postal / zone codes",
        "column_hint": "postal / zip / zone / location column",
        "lane_prefix": "postal_code",
    },
)

# Fields that form lane identity when detecting remaps (exclude the field under test).
_IDENTITY_META_FIELDS: tuple[str, ...] = (
    "equipment",
    "origin_country",
    "origin_location",
    "dest_country",
    "dest_location",
    "service_level",
    "rate_component",
    "weight_break_label",
    "charge_id",
)


def _norm_code(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _values_by_sheet(
    records: list[RateRecord], fields: tuple[str, ...]
) -> dict[str, set[str]]:
    by_sheet: dict[str, set[str]] = {}
    for r in records:
        if r.record_type == "contract_logic":
            continue
        sheet = (r.sheet or "(no sheet)").strip() or "(no sheet)"
        for field in fields:
            code = _norm_code(r.meta.get(field))
            if code:
                by_sheet.setdefault(sheet, set()).add(code)
    return by_sheet


def _lane_identity_excluding(
    rec: RateRecord, exclude_fields: frozenset[str]
) -> tuple[str, ...]:
    parts: list[str] = [(rec.sheet or "").strip(), str(rec.block or "").strip()]
    for field in _IDENTITY_META_FIELDS:
        if field in exclude_fields:
            continue
        parts.append(_norm_code(rec.meta.get(field)))
    return tuple(parts)


def _field_value(rec: RateRecord, fields: tuple[str, ...]) -> str:
    """Join non-empty values for multi-field checks (e.g. origin+dest postal)."""
    vals = [_norm_code(rec.meta.get(f)) for f in fields]
    vals = [v for v in vals if v]
    return " | ".join(vals)


def _remaps_by_sheet(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
    fields: tuple[str, ...],
) -> dict[str, list[tuple[str, str, str]]]:
    exclude = frozenset(fields)
    old_map: dict[tuple[str, ...], str] = {}
    new_map: dict[tuple[str, ...], str] = {}
    for r in old_records:
        if r.record_type == "contract_logic":
            continue
        val = _field_value(r, fields)
        if not val:
            continue
        old_map[_lane_identity_excluding(r, exclude)] = val
    for r in new_records:
        if r.record_type == "contract_logic":
            continue
        val = _field_value(r, fields)
        if not val:
            continue
        new_map[_lane_identity_excluding(r, exclude)] = val

    by_sheet: dict[str, list[tuple[str, str, str]]] = {}
    for key in set(old_map) & set(new_map):
        old_c, new_c = old_map[key], new_map[key]
        if old_c == new_c:
            continue
        sheet = key[0] or "(no sheet)"
        label_parts = [p for p in key[2:6] if p]
        label = " | ".join(label_parts[:3]) if label_parts else "(lane)"
        by_sheet.setdefault(sheet, []).append((label, old_c, new_c))
    return by_sheet


def detect_code_field_changes(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> list[Flag]:
    """
    Review flags for charge codes, service codes, and postal/zone codes.

    Per sheet, detects:
    - values only in OLD / only in NEW (set change)
    - same lane identity with a different value (remap)
    """
    flags: list[Flag] = []

    for cfg in _CODE_FIELD_CHECKS:
        fields: tuple[str, ...] = cfg["fields"]
        old_by = _values_by_sheet(old_records, fields)
        new_by = _values_by_sheet(new_records, fields)
        remaps_by = _remaps_by_sheet(old_records, new_records, fields)
        sheets = sorted(set(old_by) | set(new_by) | set(remaps_by))

        for sheet in sheets:
            old_codes = old_by.get(sheet, set())
            new_codes = new_by.get(sheet, set())
            removed = sorted(old_codes - new_codes)
            added = sorted(new_codes - old_codes)
            remaps = remaps_by.get(sheet, [])

            if not removed and not added and not remaps:
                continue

            parts: list[str] = []
            sample_removed = ", ".join(removed[:8]) + ("…" if len(removed) > 8 else "")
            sample_added = ", ".join(added[:8]) + ("…" if len(added) > 8 else "")
            if removed:
                parts.append(
                    f"{len(removed)} only in previous ({sample_removed})"
                )
            if added:
                parts.append(f"{len(added)} only in new ({sample_added})")
            if remaps:
                sample_remap = "; ".join(f"{oc}→{nc}" for _, oc, nc in remaps[:6])
                if len(remaps) > 6:
                    sample_remap += "…"
                parts.append(
                    f"{len(remaps)} remapped on same lane ({sample_remap})"
                )

            old_value = sample_removed or (
                ", ".join(f"{oc}→{nc}" for _, oc, nc in remaps[:8]) if remaps else None
            )
            new_value = sample_added or (
                ", ".join(f"{nc}" for _, _, nc in remaps[:8]) if remaps else None
            )

            flags.append(
                Flag(
                    rule_id=cfg["rule_id"],
                    severity="review",
                    lane_key=f"{cfg['lane_prefix']}|{sheet}",
                    message=(
                        f"{cfg['label']} changed on sheet «{sheet}»: "
                        + "; ".join(parts)
                        + "."
                    ),
                    old_value=old_value,
                    new_value=new_value,
                    block="other",
                    sheet=sheet,
                    where_to_look_old=(
                        f"Sheet «{sheet}» — {cfg['column_hint']} in previous file"
                    ),
                    where_to_look_new=(
                        f"Sheet «{sheet}» — {cfg['column_hint']} in new file"
                    ),
                    action_hint=(
                        f"Confirm whether {cfg['label'].lower()} were renamed, "
                        "remapped, or replaced. Update billing / rating mappings if needed. "
                        "See New / Removed tabs for related lines."
                    ),
                )
            )
    return flags


def detect_charge_code_changes(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> list[Flag]:
    """Backward-compatible alias — prefer detect_code_field_changes."""
    return detect_code_field_changes(old_records, new_records)


def _remark_text(rec: RateRecord) -> str:
    """Lane Remark/Comments text (not contract_logic wording)."""
    if rec.record_type == "contract_logic":
        return ""
    for key in ("remarks", "extra_remarks"):
        val = rec.meta.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    # Auto-extract stores Remarks in text_value when the profile left it free.
    if rec.record_type in {
        "lane_matrix",
        "weight_break_table",
        "overflow_rate",
        "other",
    }:
        return (rec.text_value or "").strip()
    return ""


def _remark_identity(rec: RateRecord) -> tuple[str, ...]:
    """
    Lane identity for Remarks — ignore rate_component so OLD/NEW profiles
    that map different price columns still compare the same lane's Remark.
    """
    sheet = (rec.sheet or "").strip() or "(no sheet)"
    cid = _norm_code(rec.meta.get("charge_id"))
    if cid:
        return (sheet, "id", cid)
    return (
        sheet,
        "loc",
        _norm_code(rec.meta.get("origin_country")),
        _norm_code(rec.meta.get("origin_location")),
        _norm_code(rec.meta.get("dest_country")),
        _norm_code(rec.meta.get("dest_location")),
        _norm_code(rec.meta.get("equipment")),
        _norm_code(rec.meta.get("service_level")),
    )


def detect_remark_changes(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> list[Flag]:
    """
    Review flags when Remark/Comments column text changes on the same lane.

    Uses charge_id (or origin/dest/equipment) so it works even when match_keys
    diverge because profiles map different rate columns.
    """
    old_map: dict[tuple[str, ...], str] = {}
    new_map: dict[tuple[str, ...], str] = {}
    for r in old_records:
        if r.record_type == "contract_logic":
            continue
        txt = _remark_text(r)
        if not txt:
            continue
        old_map[_remark_identity(r)] = txt
    for r in new_records:
        if r.record_type == "contract_logic":
            continue
        txt = _remark_text(r)
        if not txt:
            continue
        new_map[_remark_identity(r)] = txt

    by_sheet: dict[str, list[tuple[str, str, str]]] = {}
    for key in sorted(set(old_map) & set(new_map)):
        o, n = old_map[key], new_map[key]
        if o == n:
            continue
        sheet = key[0]
        label = key[2] if len(key) > 2 and key[1] == "id" else " | ".join(
            p for p in key[2:] if p
        ) or "(lane)"
        by_sheet.setdefault(sheet, []).append((label, o, n))

    # Remark cleared or newly filled on a lane present on both sides with text
    # only on one side — still worth review when the other side had/has a remark.
    for key in sorted(set(old_map) - set(new_map)):
        # Only if the lane still exists in new under same identity (any record).
        if not any(_remark_identity(r) == key for r in new_records if r.record_type != "contract_logic"):
            continue
        sheet = key[0]
        label = key[2] if len(key) > 2 and key[1] == "id" else " | ".join(
            p for p in key[2:] if p
        ) or "(lane)"
        by_sheet.setdefault(sheet, []).append((label, old_map[key], "(empty)"))
    for key in sorted(set(new_map) - set(old_map)):
        if not any(_remark_identity(r) == key for r in old_records if r.record_type != "contract_logic"):
            continue
        sheet = key[0]
        label = key[2] if len(key) > 2 and key[1] == "id" else " | ".join(
            p for p in key[2:] if p
        ) or "(lane)"
        by_sheet.setdefault(sheet, []).append((label, "(empty)", new_map[key]))

    flags: list[Flag] = []
    for sheet, changes in sorted(by_sheet.items()):
        if not changes:
            continue
        samples = []
        for label, o, n in changes[:5]:
            o_one = " ".join(o.split())
            n_one = " ".join(n.split())
            o_snip = (o_one[:90] + "…") if len(o_one) > 90 else o_one
            n_snip = (n_one[:90] + "…") if len(n_one) > 90 else n_one
            samples.append(f"{label}: «{o_snip}» → «{n_snip}»")
        sample_txt = "; ".join(samples) + ("…" if len(changes) > 5 else "")
        flags.append(
            Flag(
                rule_id="REMARK_CHANGED",
                severity="review",
                lane_key=f"remarks|{sheet}",
                message=(
                    f"{len(changes)} lane Remark/Comments change(s) on sheet «{sheet}» "
                    f"({sample_txt})."
                ),
                old_value=changes[0][1][:500],
                new_value=changes[0][2][:500],
                block="other",
                sheet=sheet,
                where_to_look_old=f"Sheet «{sheet}» — column Remark / Remarks in previous file",
                where_to_look_new=f"Sheet «{sheet}» — column Remark / Remarks in new file",
                action_hint=(
                    "Confirm whether Remark text changes are intentional "
                    "(carrier notes, free time, routing, packing group notes, etc.)."
                ),
            )
        )
    return flags


def apply_rules(
    diff: DiffResult,
    old_records: list[RateRecord],
    new_records: list[RateRecord],
    thresholds: dict[str, Any],
) -> list[Flag]:
    flags: list[Flag] = []
    pct_limit = float(thresholds.get("price_change_red_flag_pct", 100))
    mass_pct = float(thresholds.get("mass_lane_removal_pct", 15))
    mass_add_pct = float(thresholds.get("mass_lane_addition_pct", 15))

    old_logic = _logic_records(old_records)
    new_logic = _logic_records(new_records)

    for logic_key in sorted(set(old_logic) - set(new_logic)):
        old_rec = old_logic[logic_key]
        label = old_rec.meta.get("logic_label", logic_key)
        flags.append(
            Flag(
                rule_id="LOGIC_REMOVED_IN_NEW_FILE",
                severity="red_flag",
                lane_key=logic_key,
                message=f"Calculation logic removed in new file: {label}",
                old_value=old_rec.text_value,
                new_value=None,
                block="contract_logic",
                sheet=old_rec.sheet,
                where_to_look_old=_where_from_record(old_rec),
                where_to_look_new="(not present in new file — check Ambiant / rate card header area)",
                action_hint=(
                    "Open the OLD workbook at the location shown. Confirm whether the new "
                    "tariff intentionally dropped this rule; if not, request correction from carrier. "
                    "Charges for >100 kg may calculate differently without this text."
                ),
            )
        )

    for logic_key in sorted(set(new_logic) - set(old_logic)):
        new_rec = new_logic[logic_key]
        label = new_rec.meta.get("logic_label", logic_key)
        flags.append(
            Flag(
                rule_id="LOGIC_ADDED_IN_NEW_FILE",
                severity="review",
                lane_key=logic_key,
                message=f"New calculation logic in new file: {label}",
                old_value=None,
                new_value=new_rec.text_value,
                block="contract_logic",
                sheet=new_rec.sheet,
                where_to_look_old="(not in old file)",
                where_to_look_new=_where_from_record(new_rec),
                action_hint="Verify new wording with carrier and update billing system rules if needed.",
            )
        )

    for logic_key in sorted(set(old_logic) & set(new_logic)):
        old_rec, new_rec = old_logic[logic_key], new_logic[logic_key]
        if (old_rec.text_value or "").strip() != (new_rec.text_value or "").strip():
            flags.append(
                Flag(
                    rule_id="LOGIC_TEXT_CHANGED",
                    severity="red_flag",
                    lane_key=logic_key,
                    message=f"Calculation logic text changed: {old_rec.meta.get('logic_label', logic_key)}",
                    old_value=old_rec.text_value,
                    new_value=new_rec.text_value,
                    block="contract_logic",
                    sheet=old_rec.sheet,
                    where_to_look_old=_where_from_record(old_rec),
                    where_to_look_new=_where_from_record(new_rec),
                    action_hint="Compare both cells side by side; update rating engine if formula changed.",
                )
            )

    lane_types = {"lane_matrix", "weight_break_table", "overflow_rate"}
    old_lanes = [r for r in old_records if r.record_type in lane_types]
    new_lanes = [r for r in new_records if r.record_type in lane_types]
    if old_lanes:
        rem_pct = len(diff.only_old) / len(old_lanes) * 100
        if rem_pct >= mass_pct:
            flags.append(
                Flag(
                    rule_id="MASS_LANE_REMOVAL",
                    severity="red_flag",
                    lane_key="*",
                    message=f"Removed {len(diff.only_old)} lane lines ({rem_pct:.1f}% of old lane records).",
                    block="summary",
                    sheet="",
                    action_hint="See Removed sheet for lane keys.",
                )
            )
    if new_lanes:
        add_pct = len(diff.only_new) / max(len(new_lanes), 1) * 100
        if add_pct >= mass_add_pct and len(diff.only_new) > 10:
            flags.append(
                Flag(
                    rule_id="MASS_LANE_ADDITION",
                    severity="red_flag",
                    lane_key="*",
                    message=f"Added {len(diff.only_new)} lane lines ({add_pct:.1f}% vs new lane records).",
                    block="summary",
                    sheet="",
                    action_hint="See Added sheet for lane keys.",
                )
            )

    old_blocks = {r.block for r in old_records}
    new_blocks = {r.block for r in new_records}
    for b in sorted(new_blocks - old_blocks):
        flags.append(
            Flag(
                rule_id="NEW_BLOCK",
                severity="review",
                lane_key="*",
                message=f"New block type present only in new file: {b}",
                block=b,
                action_hint="Review Added sheet and new workbook tabs.",
            )
        )

    old_fuel_var = {r.meta.get("variant") for r in old_records if r.block.startswith("fuel")}
    new_fuel_var = {r.meta.get("variant") for r in new_records if r.block.startswith("fuel")}
    if old_fuel_var != new_fuel_var:
        flags.append(
            Flag(
                rule_id="FUEL_TABLE_REDESIGN",
                severity="red_flag",
                lane_key="*",
                message=f"Fuel table variant changed: {old_fuel_var} → {new_fuel_var}",
                block="fuel",
                sheet="Fuel",
                where_to_look_old="Sheet «Fuel» in old file",
                where_to_look_new="Sheet «Fuel» in new file",
                action_hint="Fuel surcharge may not be comparable row-for-row; revalidate fuel % tables.",
            )
        )

    old_layout = next(
        (r for r in old_records if r.lane_key == "ambiant|block|matrix_layout"), None
    )
    new_layout = next(
        (r for r in new_records if r.lane_key == "ambiant|block|matrix_layout"), None
    )
    if old_layout and new_layout:
        for field in ("first_p_kg_weight_break", "last_flat_weight_break", "rate_by"):
            if old_layout.meta.get(field) != new_layout.meta.get(field):
                flags.append(
                    Flag(
                        rule_id="MATRIX_LAYOUT_CHANGED",
                        severity="red_flag",
                        lane_key="ambiant|block|matrix_layout",
                        message=f"Ambiant matrix layout changed: {field}",
                        old_value=old_layout.meta.get(field),
                        new_value=new_layout.meta.get(field),
                        block="ambient_rate_card",
                        sheet="Ambiant",
                        where_to_look_old=_where_from_record(old_layout),
                        where_to_look_new=_where_from_record(new_layout),
                        action_hint="Check weight-break header rows (rows 7–8) on sheet Ambiant.",
                    )
                )

    for ch in diff.field_changes:
        key = ch["lane_key"]
        if ch.get("billing_basis_old") != ch.get("billing_basis_new"):
            flags.append(
                Flag(
                    rule_id="BILLING_BASIS_CHANGED",
                    severity="red_flag",
                    lane_key=key,
                    message="Billing basis changed.",
                    old_value=ch.get("billing_basis_old"),
                    new_value=ch.get("billing_basis_new"),
                    block=ch.get("block", ""),
                    sheet=ch.get("sheet", ""),
                    where_to_look_new=f"Sheet «{ch.get('sheet', '')}» — search lane_key in Changed sheet",
                    action_hint="Flat vs p/kg column change affects how charge is calculated.",
                )
            )
        if ch.get("calculation_method_old") != ch.get("calculation_method_new"):
            flags.append(
                Flag(
                    rule_id="CALCULATION_METHOD_CHANGED",
                    severity="red_flag",
                    lane_key=key,
                    message=(
                        "How to apply the cell rate changed "
                        f"({ch.get('calculation_method_old')} → {ch.get('calculation_method_new')})."
                    ),
                    old_value=ch.get("charge_formula_old") or ch.get("calculation_method_old"),
                    new_value=ch.get("charge_formula_new") or ch.get("calculation_method_new"),
                    block=ch.get("block", ""),
                    sheet=ch.get("sheet", ""),
                    where_to_look_new=f"Sheet «{ch.get('sheet', '')}» — see Changed sheet (zone/weight_break columns)",
                    action_hint="Often caused by missing >100kg logic text in new file while p/kg columns remain.",
                )
            )

    # Extreme price changes: if many, one critical flag per sheet (not thousands of rows).
    extreme_detail_max = int(thresholds.get("price_change_extreme_detail_max", 20))
    extreme_by_sheet: dict[str, list[dict[str, Any]]] = {}
    for ch in diff.field_changes:
        pct = ch.get("pct_change")
        if pct is None:
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            continue
        if abs(pct_f) < pct_limit:
            continue
        sheet = str(ch.get("sheet") or "(no sheet)")
        extreme_by_sheet.setdefault(sheet, []).append(ch)

    total_extreme = sum(len(v) for v in extreme_by_sheet.values())
    if total_extreme > extreme_detail_max:
        for sheet, items in sorted(extreme_by_sheet.items()):
            pcts = []
            for ch in items:
                try:
                    pcts.append(float(ch["pct_change"]))
                except (TypeError, ValueError, KeyError):
                    pass
            max_pct = max(pcts, key=abs) if pcts else None
            avg_pct = sum(pcts) / len(pcts) if pcts else None
            msg = (
                f"{len(items)} large price change(s) on sheet «{sheet}» "
                f"(threshold ±{pct_limit:g}%)."
            )
            if avg_pct is not None and max_pct is not None:
                msg += f" Typical {avg_pct:+.1f}%, largest {max_pct:+.1f}%."
            flags.append(
                Flag(
                    rule_id="PRICE_CHANGE_EXTREME",
                    severity="red_flag",
                    lane_key=f"price|*|{sheet}",
                    message=msg,
                    old_value=None,
                    new_value=f"{len(items)} lanes",
                    block="summary",
                    sheet=sheet,
                    where_to_look_old=f"Sheet «{sheet}» in previous file",
                    where_to_look_new=f"Sheet «{sheet}» in new file — see Price changes tab",
                    action_hint=(
                        "Many rates moved a lot on this sheet. Review the Price changes "
                        "summary (by sheet / weight break), then sample cells with the carrier."
                    ),
                )
            )
    else:
        for sheet, items in extreme_by_sheet.items():
            for ch in items:
                pct = float(ch["pct_change"])
                flags.append(
                    Flag(
                        rule_id="PRICE_CHANGE_EXTREME",
                        severity="red_flag",
                        lane_key=ch["lane_key"],
                        message=f"Price change {pct:.1f}% (threshold {pct_limit}%).",
                        old_value=ch.get("amount_old"),
                        new_value=ch.get("amount_new"),
                        block=ch.get("block", ""),
                        sheet=sheet,
                        where_to_look_new=f"Sheet «{sheet}» — Price changes tab",
                        action_hint="Verify rate cell; extreme % may be data error or wrong column match.",
                    )
                )

    new_zones = [r for r in diff.only_new if r.record_type == "zone_mapping"]
    if new_zones:
        flags.append(
            Flag(
                rule_id="NEW_ZONE_MAPPING",
                severity="review",
                lane_key="*",
                message=f"New remote/island zone mapping: {len(new_zones)} department rows (see Added sheet).",
                new_value=new_zones[0].sheet,
                block="remote_area_zones",
                sheet=new_zones[0].sheet,
                where_to_look_new=f"Sheet «{new_zones[0].sheet}»",
            )
        )

    # New accessorial / Extra charges lines (not only legacy surcharge_table).
    new_accessorials = [
        r
        for r in diff.only_new
        if r.record_type == "surcharge_table"
        or r.block == "accessorial"
        or "extra" in (r.sheet or "").lower()
    ]
    if new_accessorials:
        by_sheet: dict[str, list[RateRecord]] = {}
        for r in new_accessorials:
            by_sheet.setdefault(r.sheet or "(no sheet)", []).append(r)
        for sheet, recs in sorted(by_sheet.items()):
            samples = []
            for r in recs[:5]:
                name = (
                    r.meta.get("equipment")
                    or r.meta.get("rate_component")
                    or r.meta.get("charge_id")
                )
                code = r.meta.get("charge_id")
                if name and code and str(name) != str(code):
                    samples.append(f"{code} ({name})")
                else:
                    samples.append(str(name or code or r.lane_key[:40]))
            sample_txt = ", ".join(samples) + ("…" if len(recs) > 5 else "")
            flags.append(
                Flag(
                    rule_id="NEW_COST",
                    severity="red_flag",
                    lane_key=f"new_cost|{sheet}",
                    message=(
                        f"{len(recs)} new accessorial / extra charge line(s) on sheet «{sheet}» "
                        f"({sample_txt})."
                    ),
                    new_value=sample_txt,
                    block="accessorial",
                    sheet=sheet,
                    where_to_look_new=f"Sheet «{sheet}» in new file — see New in new tariff tab",
                    action_hint=(
                        "Confirm new costs with the carrier and update billing mappings. "
                        "Details are listed under New in new tariff."
                    ),
                )
            )

    for rec in diff.only_old:
        if rec.record_type == "surcharge_table" or rec.block == "accessorial":
            flags.append(
                Flag(
                    rule_id="REMOVED_COST",
                    severity="review",
                    lane_key=rec.lane_key,
                    message="Accessorial / cost line removed.",
                    old_value=rec.text_value or rec.amount,
                    block=rec.block,
                    sheet=rec.sheet,
                    where_to_look_old=_where_from_record(rec),
                )
            )

    flags.extend(detect_code_field_changes(old_records, new_records))
    flags.extend(detect_remark_changes(old_records, new_records))
    flags.extend(apply_structural_rules(old_records, new_records))

    flags.sort(key=lambda f: (0 if f.severity == "red_flag" else 1, f.rule_id, f.lane_key))
    return flags
