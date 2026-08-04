from __future__ import annotations

from tariff_compare.models import RateRecord


def logic_ids_present(records: list[RateRecord]) -> set[str]:
    return {
        r.meta.get("logic_id", "")
        for r in records
        if r.record_type == "contract_logic" and r.meta.get("logic_id")
    }
