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
        pct = ch.get("pct_change")
        if pct is not None and abs(pct) >= pct_limit:
            flags.append(
                Flag(
                    rule_id="PRICE_CHANGE_EXTREME",
                    severity="red_flag",
                    lane_key=key,
                    message=f"Price change {pct:.1f}% (threshold {pct_limit}%).",
                    old_value=ch.get("amount_old"),
                    new_value=ch.get("amount_new"),
                    block=ch.get("block", ""),
                    sheet=ch.get("sheet", ""),
                    where_to_look_new=f"Sheet «{ch.get('sheet', '')}» — Changed sheet",
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

    for rec in diff.only_new:
        if rec.record_type == "surcharge_table":
            flags.append(
                Flag(
                    rule_id="NEW_COST",
                    severity="review",
                    lane_key=rec.lane_key,
                    message="New accessorial / cost line.",
                    new_value=rec.text_value or rec.amount,
                    block=rec.block,
                    sheet=rec.sheet,
                    where_to_look_new=_where_from_record(rec),
                )
            )

    for rec in diff.only_old:
        if rec.record_type == "surcharge_table":
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

    flags.extend(apply_structural_rules(old_records, new_records))

    flags.sort(key=lambda f: (0 if f.severity == "red_flag" else 1, f.rule_id, f.lane_key))
    return flags
