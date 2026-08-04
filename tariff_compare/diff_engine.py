from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from tariff_compare.models import Flag, RateRecord


@dataclass
class MatchedPair:
    lane_key: str
    old: RateRecord
    new: RateRecord


@dataclass
class DiffResult:
    matched: list[MatchedPair]
    only_old: list[RateRecord]
    only_new: list[RateRecord]
    field_changes: list[dict[str, Any]]


def _pct_change(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None:
        return None
    if old == 0:
        return None if new == 0 else float("inf")
    return (new - old) / abs(old) * 100.0


def diff_records(
    old_records: list[RateRecord], new_records: list[RateRecord]
) -> DiffResult:
    old_map = {r.lane_key: r for r in old_records}
    new_map = {r.lane_key: r for r in new_records}
    keys_old, keys_new = set(old_map), set(new_map)

    matched: list[MatchedPair] = []
    field_changes: list[dict[str, Any]] = []

    for key in sorted(keys_old & keys_new):
        o, n = old_map[key], new_map[key]
        matched.append(MatchedPair(lane_key=key, old=o, new=n))
        change: dict[str, Any] = {
            "lane_key": key,
            "record_type": o.record_type,
            "block": o.block,
            "sheet": o.sheet,
        }
        changed = False
        if o.amount is not None or n.amount is not None:
            if o.amount != n.amount:
                change["amount_old"] = o.amount
                change["amount_new"] = n.amount
                change["pct_change"] = _pct_change(o.amount, n.amount)
                changed = True
        if o.billing_basis != n.billing_basis:
            change["billing_basis_old"] = o.billing_basis
            change["billing_basis_new"] = n.billing_basis
            changed = True
        calc_old = o.meta.get("calculation_method")
        calc_new = n.meta.get("calculation_method")
        if calc_old != calc_new:
            change["calculation_method_old"] = calc_old
            change["calculation_method_new"] = calc_new
            change["charge_formula_old"] = o.meta.get("charge_formula")
            change["charge_formula_new"] = n.meta.get("charge_formula")
            changed = True
        if o.text_value != n.text_value:
            change["text_old"] = o.text_value
            change["text_new"] = n.text_value
            changed = True
        if changed:
            field_changes.append(change)

    only_old = [old_map[k] for k in sorted(keys_old - keys_new)]
    only_new = [new_map[k] for k in sorted(keys_new - keys_old)]

    return DiffResult(
        matched=matched,
        only_old=only_old,
        only_new=only_new,
        field_changes=field_changes,
    )
