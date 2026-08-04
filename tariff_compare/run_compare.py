from __future__ import annotations

import json
from pathlib import Path

from tariff_compare.calculation import logic_ids_present
from tariff_compare.cost_changes import build_cost_change_rows
from tariff_compare.diff_engine import diff_records
from tariff_compare.excel_inventory import inventory_workbook
from tariff_compare.io_jsonl import write_jsonl
from tariff_compare.parse_flags import build_extraction_flags
from tariff_compare.report import write_report
from tariff_compare.rules import apply_rules, load_thresholds
from tariff_compare.tariff_line import load_extraction_jsonl


def label_from_extraction(path: Path, records: list) -> str:
    for r in records:
        src = (r.meta or {}).get("source_file")
        if src:
            return str(src)
    return path.name


def run_compare(
    *,
    old_ext: Path,
    new_ext: Path,
    run_dir: Path,
    thresholds_path: Path,
    old_workbook: Path | None = None,
    new_workbook: Path | None = None,
    compare_method: str = "tariff_line_diff",
) -> dict:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    thresholds = load_thresholds(thresholds_path)

    old_ext = Path(old_ext).resolve()
    new_ext = Path(new_ext).resolve()

    print(f"Loading OLD extraction: {old_ext.name}")
    old_records = load_extraction_jsonl(old_ext)
    print(f"  -> {len(old_records)} line(s)")
    print(f"Loading NEW extraction: {new_ext.name}")
    new_records = load_extraction_jsonl(new_ext)
    print(f"  -> {len(new_records)} line(s)")

    old_label = (
        old_workbook.name if old_workbook else label_from_extraction(old_ext, old_records)
    )
    new_label = (
        new_workbook.name if new_workbook else label_from_extraction(new_ext, new_records)
    )
    print(f"Compare labels: {old_label}  ->  {new_label}")

    old_sheets = inventory_workbook(old_workbook) if old_workbook else []
    new_sheets = inventory_workbook(new_workbook) if new_workbook else []

    write_jsonl(old_records, run_dir / "canonical_old.jsonl")
    write_jsonl(new_records, run_dir / "canonical_new.jsonl")

    diff = diff_records(old_records, new_records)
    cost_max = int(thresholds.get("cost_changes_detail_max", 100))
    cost_change_rows = build_cost_change_rows(diff)
    flags = build_extraction_flags(
        len(old_records), len(new_records), old_label, new_label
    )
    flags.extend(apply_rules(diff, old_records, new_records, thresholds))

    old_logic_n = sum(1 for r in old_records if r.record_type == "contract_logic")
    new_logic_n = sum(1 for r in new_records if r.record_type == "contract_logic")

    summary = {
        "old_file": old_label,
        "new_file": new_label,
        "old_workbook": str(old_workbook) if old_workbook else None,
        "new_workbook": str(new_workbook) if new_workbook else None,
        "compare_method": compare_method,
        "old_extraction": str(old_ext),
        "new_extraction": str(new_ext),
        "old_record_count": len(old_records),
        "new_record_count": len(new_records),
        "matched_keys": len(diff.matched),
        "changed": len(diff.field_changes),
        "added": len(diff.only_new),
        "removed": len(diff.only_old),
        "flag_count": len(flags),
        "red_flags": sum(1 for f in flags if f.severity == "red_flag"),
        "logic_clauses_old_new": f"{old_logic_n} / {new_logic_n}",
        "logic_ids_old": sorted(logic_ids_present(old_records)),
        "logic_ids_new": sorted(logic_ids_present(new_records)),
        "cost_changes_count": len(cost_change_rows),
        "cost_changes_detail_max": cost_max,
        "cost_changes_tab": (
            "included"
            if cost_change_rows and len(cost_change_rows) <= cost_max
            else (
                f"omitted ({len(cost_change_rows)} price changes; detail tab max is {cost_max})"
                if cost_change_rows
                else "not applicable (no matched price changes)"
            )
        ),
        "price_change_red_flag_pct": thresholds.get("price_change_red_flag_pct", 100),
        "project": "tariff-errors-search",
        "output_dir": str(run_dir),
    }

    with (run_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with (run_dir / "workbook_inventory.json").open("w", encoding="utf-8") as f:
        json.dump(
            {
                "old": {
                    "file": old_label,
                    "workbook": str(old_workbook) if old_workbook else None,
                    "sheets": [s.__dict__ for s in old_sheets],
                },
                "new": {
                    "file": new_label,
                    "workbook": str(new_workbook) if new_workbook else None,
                    "sheets": [s.__dict__ for s in new_sheets],
                },
                "source": compare_method,
            },
            f,
            indent=2,
        )

    with (run_dir / "flags.json").open("w", encoding="utf-8") as f:
        json.dump([fl.to_dict() for fl in flags], f, indent=2, ensure_ascii=False)

    report_path = run_dir / "report.xlsx"
    write_report(
        report_path,
        diff,
        flags,
        summary,
        old_records=old_records,
        new_records=new_records,
        old_sheets=old_sheets or None,
        new_sheets=new_sheets or None,
        generic=None,
    )

    print(json.dumps(summary, indent=2))
    print(f"\nWrote:\n  {run_dir}\n  {report_path}")
    return summary
