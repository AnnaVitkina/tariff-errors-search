from __future__ import annotations

from typing import Any

from tariff_compare.diff_engine import DiffResult


def build_cost_change_rows(diff: DiffResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ch in diff.field_changes:
        if "amount_old" not in ch and "amount_new" not in ch:
            continue
        old_a = ch.get("amount_old")
        new_a = ch.get("amount_new")
        if old_a == new_a:
            continue
        row = dict(ch)
        if old_a is not None and new_a is not None:
            row["amount_delta"] = new_a - old_a
        key = ch.get("lane_key", "")
        if key.startswith("ambiant|") and "|wb=" in key:
            parts = key.split("|")
            row["destination_zone"] = parts[1] if len(parts) > 1 else ""
            row["weight_break"] = parts[2].replace("wb=", "") if len(parts) > 2 else ""
        elif key.startswith("germanetti|"):
            parts = key.split("|")
            row["destination_zone"] = ""
            row["weight_break"] = ""
            for part in parts[1:]:
                if part.startswith("wb="):
                    row["weight_break"] = part.replace("wb=", "")
        rows.append(row)
    rows.sort(
        key=lambda r: (
            -(abs(r["pct_change"]) if r.get("pct_change") is not None else 0),
            r.get("lane_key", ""),
        )
    )
    return rows
