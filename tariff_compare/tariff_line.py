from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tariff_compare.io_jsonl import read_jsonl
from tariff_compare.models import RateRecord, SourceRef


def _norm_part(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    return re.sub(r"\s+", " ", s)


def build_match_key(line: dict[str, Any]) -> str:
    order = [
        "charge_kind",
        "charge_id",
        "mode",
        "origin_country",
        "origin_location",
        "dest_country",
        "dest_location",
        "service_level",
        "rate_component",
        "weight_break_label",
        "equipment",
    ]
    parts = [_norm_part(line.get(k)) for k in order]
    parts = [p for p in parts if p]
    if not parts:
        sheet = _norm_part(line.get("source_sheet"))
        row = line.get("source_row", "")
        col = line.get("source_col", "")
        return f"weak|{sheet}|r{row}|c{col}"
    return "|".join(parts)


def _is_legacy_rate_record(row: dict[str, Any]) -> bool:
    return "lane_key" in row and "record_type" in row


def tariff_line_to_rate_record(line: dict[str, Any]) -> RateRecord:
    lk = line.get("match_key") or build_match_key(line)
    charge_kind = str(line.get("charge_kind") or "other")
    sheet = str(line.get("source_sheet") or "")
    meta: dict[str, Any] = {
        k: line.get(k)
        for k in (
            "charge_id",
            "mode",
            "origin_country",
            "origin_location",
            "dest_country",
            "dest_location",
            "service_level",
            "rate_component",
            "weight_break_label",
            "equipment",
            "valid_from",
            "valid_to",
            "source_file",
        )
        if line.get(k) is not None
    }
    if line.get("calculation_method"):
        meta["calculation_method"] = line["calculation_method"]
    extras = line.get("extras")
    if isinstance(extras, dict):
        for k in ("logic_id", "logic_label"):
            if extras.get(k) is not None:
                meta[k] = extras[k]
        meta.update(
            {
                f"extra_{k}": v
                for k, v in extras.items()
                if k not in ("logic_id", "logic_label")
            }
        )

    src = None
    if sheet and line.get("source_row") is not None:
        src = SourceRef(
            sheet=sheet,
            row=int(line["source_row"]),
            col=int(line["source_col"]) if line.get("source_col") is not None else None,
        )

    record_type = (
        "contract_logic"
        if charge_kind == "contract_logic"
        else "lane_matrix"
        if charge_kind in ("base_rate", "accessorial", "fuel", "linehaul")
        else "other"
    )

    return RateRecord(
        lane_key=lk,
        record_type=record_type,
        block=charge_kind,
        sheet=sheet,
        amount=line.get("amount"),
        billing_basis=line.get("billing_basis") or line.get("rate_component"),
        currency=line.get("currency"),
        text_value=line.get("text_value"),
        meta=meta,
        source=src,
    )


def legacy_dict_to_rate_record(row: dict[str, Any]) -> RateRecord:
    src = row.get("source")
    source = SourceRef(**src) if isinstance(src, dict) else None
    return RateRecord(
        lane_key=row["lane_key"],
        record_type=row.get("record_type", "other"),
        block=row.get("block", ""),
        sheet=row.get("sheet", ""),
        amount=row.get("amount"),
        billing_basis=row.get("billing_basis"),
        currency=row.get("currency"),
        text_value=row.get("text_value"),
        meta=row.get("meta") or {},
        source=source,
    )


def load_extraction_jsonl(path: Path) -> list[RateRecord]:
    rows = read_jsonl(path)
    if not rows:
        return []
    if _is_legacy_rate_record(rows[0]):
        return [legacy_dict_to_rate_record(r) for r in rows]
    return [tariff_line_to_rate_record(r) for r in rows]
