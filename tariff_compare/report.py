from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from tariff_compare.cost_changes import build_cost_change_rows
from tariff_compare.diff_engine import DiffResult
from tariff_compare.excel_inventory import SheetInfo
from tariff_compare.generic_diff import GenericDiffResult, numeric_cost_changes
from tariff_compare.models import Flag, RateRecord
from tariff_compare.report_labels import (
    HIDDEN_FROM_FINDINGS,
    PRIORITY_INFO,
    block_title,
    priority_label,
    rule_title,
)


def _excel_value(val: Any) -> Any:
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, list):
        return ", ".join(str(x) for x in val)
    return val


def _fmt_value(val: Any) -> str:
    if val is None or val == "":
        return "-"
    if isinstance(val, float):
        if val != val:  # NaN
            return "-"
        if abs(val) >= 1000 or (abs(val) < 0.01 and val != 0):
            return f"{val:,.4f}"
        return f"{val:,.2f}"
    return str(val).strip()


def _describe_record(r: RateRecord) -> str:
    if r.text_value and str(r.text_value).strip():
        return str(r.text_value).strip()[:300]

    parts: list[str] = []
    mode = r.meta.get("mode")
    if mode:
        parts.append(str(mode).title())

    origin = " ".join(
        str(p)
        for p in (r.meta.get("origin_country"), r.meta.get("origin_location"))
        if p is not None and p != ""
    ).strip()
    dest = " ".join(
        str(p)
        for p in (r.meta.get("dest_country"), r.meta.get("dest_location"))
        if p is not None and p != ""
    ).strip()
    if origin and dest:
        parts.append(f"{origin} → {dest}")
    elif dest:
        parts.append(f"Destination: {dest}")
    elif origin:
        parts.append(f"Origin: {origin}")

    for label, key in (
        ("Service", "service_level"),
        ("Weight break", "weight_break_label"),
        ("Charge", "charge_id"),
        ("Component", "rate_component"),
    ):
        val = r.meta.get(key)
        if val is not None and val != "":
            parts.append(f"{label}: {val}")

    if parts:
        return " | ".join(parts)
    # Fallback: humanize lane_key pipe segments
    return " | ".join(r.lane_key.split("|")[:6])


def _clean_user_text(text: str) -> str:
    """Strip technical artefacts from messages shown to business users."""
    cleaned = text
    replacements = {
        "set() → {None}": "the fuel table layout changed",
        "set() →": "changed to",
        "{None}": "(not specified)",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return cleaned


def _flags_for_users(flags: list[Flag]) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for idx, flag in enumerate(
        sorted(
            flags,
            key=lambda f: (
                0 if f.severity == "red_flag" else 1,
                rule_title(f.rule_id),
                f.lane_key,
            ),
        ),
        start=1,
    ):
        if flag.rule_id in HIDDEN_FROM_FINDINGS:
            continue
        rows.append(
            {
                "#": idx,
                "Priority": priority_label(flag.severity),
                "Issue type": rule_title(flag.rule_id),
                "What we found": _clean_user_text(flag.message),
                "Previous tariff": _fmt_value(flag.old_value),
                "New tariff": _fmt_value(flag.new_value),
                "Where to look (previous file)": flag.where_to_look_old or "-",
                "Where to look (new file)": flag.where_to_look_new or "-",
                "Recommended action": flag.action_hint or "-",
                "Sheet": flag.sheet or "-",
            }
        )
    if not rows:
        rows.append(
            {
                "#": 1,
                "Priority": PRIORITY_INFO,
                "Issue type": "No issues detected",
                "What we found": "No red flags or review items were raised by the comparison rules.",
                "Previous tariff": "-",
                "New tariff": "-",
                "Where to look (previous file)": "-",
                "Where to look (new file)": "-",
                "Recommended action": "-",
                "Sheet": "-",
            }
        )
    return pd.DataFrame(rows)


def _critical_flags(flags: list[Flag]) -> pd.DataFrame:
    df = _flags_for_users([f for f in flags if f.severity == "red_flag"])
    return df


def _review_flags(flags: list[Flag]) -> pd.DataFrame:
    df = _flags_for_users(
        [f for f in flags if f.severity == "review" and f.rule_id not in HIDDEN_FROM_FINDINGS]
    )
    return df


def _record_rows(records: list[RateRecord], *, change_label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for r in records:
        rows.append(
            {
                "Change": change_label,
                "Charge type": block_title(r.block),
                "Charge code": r.meta.get("charge_id") or "-",
                "Description": _describe_record(r),
                "Sheet": r.sheet or "-",
                "Amount": _fmt_value(r.amount) if r.amount is not None else "-",
                "How billed": r.billing_basis or "-",
            }
        )
    if not rows:
        rows.append(
            {
                "Change": change_label,
                "Charge type": "-",
                "Charge code": "-",
                "Description": "None",
                "Sheet": "-",
                "Amount": "-",
                "How billed": "-",
            }
        )
    return pd.DataFrame(rows)


def _price_change_rows(diff: DiffResult, summary: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ch in build_cost_change_rows(diff):
        pct = ch.get("pct_change")
        pct_str = "-"
        if pct is not None:
            try:
                pct_str = f"{float(pct):+.1f}%"
            except (TypeError, ValueError):
                pass
        rows.append(
            {
                "Sheet": ch.get("sheet") or "-",
                "Charge type": block_title(str(ch.get("block") or "other")),
                "Charge code": ch.get("charge_id") or "-",
                "Destination / zone": ch.get("destination_zone") or "-",
                "Weight break": ch.get("weight_break") or "-",
                "Previous price": _fmt_value(ch.get("amount_old")),
                "New price": _fmt_value(ch.get("amount_new")),
                "Change": _fmt_value(ch.get("amount_delta")),
                "% change": pct_str,
                "How billed (before)": ch.get("billing_basis_old") or "-",
                "How billed (after)": ch.get("billing_basis_new") or "-",
            }
        )
    if not rows:
        note = summary.get("cost_changes_tab", "No matched price changes")
        rows.append(
            {
                "Sheet": "-",
                "Charge type": "-",
                "Charge code": "-",
                "Destination / zone": "-",
                "Weight break": "-",
                "Previous price": "-",
                "New price": "-",
                "Change": "-",
                "% change": "-",
                "How billed (before)": "-",
                "How billed (after)": note,
            }
        )
    return pd.DataFrame(rows)


def _logic_rows(records: list[RateRecord], file_label: str) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for r in records:
        if r.record_type != "contract_logic":
            continue
        cell = r.meta.get("excel_cell")
        row_n = r.meta.get("excel_row")
        where = f"Sheet «{r.sheet}»"
        if cell:
            where += f", cell {cell}"
        elif row_n:
            where += f", row {row_n}"
        rows.append(
            {
                "File": file_label,
                "Rule name": str(r.meta.get("logic_label") or r.meta.get("logic_id") or "-"),
                "Location": where,
                "Wording in the contract": (r.text_value or "-")[:500],
            }
        )
    if not rows:
        rows.append(
            {
                "File": file_label,
                "Rule name": "-",
                "Location": "-",
                "Wording in the contract": "No calculation rules detected in this file.",
            }
        )
    return pd.DataFrame(rows)


def _logic_key_map(records: list[RateRecord]) -> dict[str, RateRecord]:
    return {r.lane_key: r for r in records if r.record_type == "contract_logic"}


def _logic_summary_df(
    old_records: list[RateRecord],
    new_records: list[RateRecord],
) -> pd.DataFrame:
    """Short was → changed → new overview before detailed wording."""
    old_map = _logic_key_map(old_records)
    new_map = _logic_key_map(new_records)
    rows: list[dict[str, str]] = []

    removed_keys = sorted(set(old_map) - set(new_map))
    added_keys = sorted(set(new_map) - set(old_map))
    changed_keys: list[str] = []
    for key in sorted(set(old_map) & set(new_map)):
        o_txt = (old_map[key].text_value or "").strip()
        n_txt = (new_map[key].text_value or "").strip()
        if o_txt != n_txt:
            changed_keys.append(key)

    def _label(rec: RateRecord) -> str:
        return str(rec.meta.get("logic_label") or rec.meta.get("logic_id") or rec.lane_key)

    def _snip(text: str | None, n: int = 120) -> str:
        s = (text or "").strip().replace("\n", " ")
        return (s[:n] + "…") if len(s) > n else (s or "-")

    rows.append(
        {
            "Category": "Overview",
            "Count": str(len(old_map)),
            "What": (
                f"Previous: {len(old_map)} rule(s). New: {len(new_map)} rule(s). "
                f"Removed: {len(removed_keys)}. Changed: {len(changed_keys)}. Added: {len(added_keys)}."
            ),
            "Previous": "-",
            "New": "-",
        }
    )

    for key in removed_keys:
        rec = old_map[key]
        rows.append(
            {
                "Category": "Was (previous only)",
                "Count": "1",
                "What": _label(rec),
                "Previous": _snip(rec.text_value),
                "New": "(removed)",
            }
        )

    for key in changed_keys:
        o, n = old_map[key], new_map[key]
        rows.append(
            {
                "Category": "Changed",
                "Count": "1",
                "What": _label(o),
                "Previous": _snip(o.text_value),
                "New": _snip(n.text_value),
            }
        )

    for key in added_keys:
        rec = new_map[key]
        rows.append(
            {
                "Category": "New",
                "Count": "1",
                "What": _label(rec),
                "Previous": "(not in previous)",
                "New": _snip(rec.text_value),
            }
        )

    if len(rows) == 1 and not removed_keys and not changed_keys and not added_keys:
        rows.append(
            {
                "Category": "No differences",
                "Count": "0",
                "What": "Calculation rules match between previous and new (or none found).",
                "Previous": "-",
                "New": "-",
            }
        )
    return pd.DataFrame(rows)


def _price_summary_df(diff: DiffResult) -> pd.DataFrame:
    """Aggregated price-change patterns (not per cell)."""
    cost_rows = build_cost_change_rows(diff)
    if not cost_rows:
        return pd.DataFrame(
            [
                {
                    "Category": "Overview",
                    "What": "No matched price changes (same lane in both files with a different amount).",
                    "Count": "0",
                    "Detail": "-",
                }
            ]
        )

    by_sheet: Counter[str] = Counter()
    by_block: Counter[str] = Counter()
    by_wb: Counter[str] = Counter()
    pcts: list[float] = []
    for ch in cost_rows:
        sheet = str(ch.get("sheet") or "(no sheet)")
        by_sheet[sheet] += 1
        block = str(ch.get("block") or "other")
        by_block[block_title(block)] += 1
        wb = str(ch.get("weight_break") or ch.get("weight_break_label") or "")
        if wb:
            by_wb[wb] += 1
        pct = ch.get("pct_change")
        if pct is not None:
            try:
                pcts.append(float(pct))
            except (TypeError, ValueError):
                pass

    rows: list[dict[str, str]] = []
    avg_pct = sum(pcts) / len(pcts) if pcts else None
    max_pct = max(pcts, key=abs) if pcts else None
    overview_bits = [f"{len(cost_rows)} matched price change(s)"]
    if avg_pct is not None:
        overview_bits.append(f"typical change {avg_pct:+.1f}%")
    if max_pct is not None:
        overview_bits.append(f"largest {max_pct:+.1f}%")
    rows.append(
        {
            "Category": "Overview",
            "What": "; ".join(overview_bits),
            "Count": str(len(cost_rows)),
            "Detail": (
                "Detail rows below list individual matched lanes. "
                "Use this summary to see where changes concentrate."
            ),
        }
    )

    for sheet, cnt in by_sheet.most_common(12):
        rows.append(
            {
                "Category": "By sheet",
                "What": sheet,
                "Count": str(cnt),
                "Detail": f"{cnt} price change(s) on this sheet",
            }
        )
    for block, cnt in by_block.most_common(8):
        rows.append(
            {
                "Category": "By charge type",
                "What": block,
                "Count": str(cnt),
                "Detail": f"{cnt} change(s)",
            }
        )
    for wb, cnt in by_wb.most_common(8):
        rows.append(
            {
                "Category": "By weight break",
                "What": wb,
                "Count": str(cnt),
                "Detail": f"{cnt} change(s) for this break",
            }
        )
    return pd.DataFrame(rows)


def _record_summary_df(records: list[RateRecord], *, kind: str) -> pd.DataFrame:
    """Summary of added or removed lines by sheet and charge type."""
    if not records:
        return pd.DataFrame(
            [
                {
                    "Category": "Overview",
                    "What": f"No {kind} lines.",
                    "Count": "0",
                    "Detail": "-",
                }
            ]
        )

    by_sheet: Counter[str] = Counter()
    by_block: Counter[str] = Counter()
    by_sheet_block: Counter[tuple[str, str]] = Counter()
    for r in records:
        sheet = r.sheet or "(no sheet)"
        block = block_title(r.block)
        by_sheet[sheet] += 1
        by_block[block] += 1
        by_sheet_block[(sheet, block)] += 1

    rows: list[dict[str, str]] = [
        {
            "Category": "Overview",
            "What": f"{len(records)} {kind} line(s) across {len(by_sheet)} sheet(s)",
            "Count": str(len(records)),
            "Detail": "Detail rows below list each line.",
        }
    ]
    for sheet, cnt in by_sheet.most_common(20):
        rows.append(
            {
                "Category": "By sheet",
                "What": sheet,
                "Count": str(cnt),
                "Detail": f"{cnt} {kind} line(s)",
            }
        )
    for block, cnt in by_block.most_common(12):
        rows.append(
            {
                "Category": "By charge type",
                "What": block,
                "Count": str(cnt),
                "Detail": f"{cnt} {kind} line(s)",
            }
        )
    for (sheet, block), cnt in by_sheet_block.most_common(15):
        rows.append(
            {
                "Category": "By sheet + type",
                "What": f"{sheet} — {block}",
                "Count": str(cnt),
                "Detail": f"{cnt} {kind} line(s)",
            }
        )
    return pd.DataFrame(rows)


def _severity_style(workbook: Any) -> dict[str, Any]:
    return {
        "critical": workbook.add_format(
            {
                "bg_color": "#FFC7CE",
                "font_color": "#9C0006",
                "bold": True,
                "border": 1,
                "text_wrap": True,
                "valign": "top",
            }
        ),
        "review": workbook.add_format(
            {
                "bg_color": "#FFEB9C",
                "font_color": "#9C6500",
                "border": 1,
                "text_wrap": True,
                "valign": "top",
            }
        ),
        "header": workbook.add_format(
            {
                "bold": True,
                "bg_color": "#2F5496",
                "font_color": "#FFFFFF",
                "border": 1,
                "text_wrap": True,
                "valign": "vcenter",
            }
        ),
        "title": workbook.add_format({"bold": True, "font_size": 16, "font_color": "#2F5496"}),
        "subtitle": workbook.add_format({"bold": True, "font_size": 12, "font_color": "#404040"}),
        "body": workbook.add_format({"font_size": 11, "text_wrap": True, "valign": "top"}),
        "kpi_label": workbook.add_format({"bold": True, "font_size": 11}),
        "kpi_value": workbook.add_format({"font_size": 11}),
        "kpi_red": workbook.add_format(
            {"bold": True, "font_size": 13, "font_color": "#9C0006", "bg_color": "#FFC7CE"}
        ),
        "note": workbook.add_format(
            {"font_size": 10, "italic": True, "font_color": "#666666", "text_wrap": True}
        ),
    }


def _write_dataframe(
    writer: pd.ExcelWriter,
    sheet_name: str,
    df: pd.DataFrame,
    styles: dict[str, Any],
    *,
    priority_col: str | None = None,
    highlight_large_pct_col: str | None = None,
    pct_threshold: float = 100,
    col_widths: dict[int, int] | None = None,
) -> None:
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    ws = writer.sheets[sheet_name]
    ncols = len(df.columns)
    nrows = len(df)

    for c in range(ncols):
        ws.write(0, c, df.columns[c], styles["header"])

    priority_idx = list(df.columns).index(priority_col) if priority_col and priority_col in df.columns else None
    pct_idx = (
        list(df.columns).index(highlight_large_pct_col)
        if highlight_large_pct_col and highlight_large_pct_col in df.columns
        else None
    )

    for r in range(nrows):
        row_fmt = None
        if priority_idx is not None:
            pri = str(df.iloc[r, priority_idx])
            if "Critical" in pri:
                row_fmt = styles["critical"]
            elif "Please review" in pri:
                row_fmt = styles["review"]
        if row_fmt is None and pct_idx is not None:
            raw = df.iloc[r, pct_idx]
            try:
                val = float(str(raw).replace("%", "").replace("+", ""))
                if abs(val) >= pct_threshold:
                    row_fmt = styles["critical"]
            except (TypeError, ValueError):
                pass
        if row_fmt:
            for c in range(ncols):
                ws.write(r + 1, c, df.iloc[r, c], row_fmt)

    if col_widths:
        for col_idx, width in col_widths.items():
            ws.set_column(col_idx, col_idx, width)
    else:
        ws.set_column(0, max(ncols - 1, 0), 18)

    ws.freeze_panes(1, 0)


def _write_sheet_with_summary(
    writer: pd.ExcelWriter,
    sheet_name: str,
    summary_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    styles: dict[str, Any],
    *,
    summary_title: str = "Summary",
    detail_title: str = "Details",
    highlight_large_pct_col: str | None = None,
    pct_threshold: float = 100,
    summary_widths: dict[int, int] | None = None,
    detail_widths: dict[int, int] | None = None,
) -> None:
    """Write summary block first, then detailed table on the same sheet."""
    workbook = writer.book
    ws = workbook.add_worksheet(sheet_name)
    writer.sheets[sheet_name] = ws
    row = 0

    ws.write(row, 0, summary_title, styles["subtitle"])
    row += 1
    for c, col_name in enumerate(summary_df.columns):
        ws.write(row, c, col_name, styles["header"])
    row += 1
    for r_idx in range(len(summary_df)):
        for c, col_name in enumerate(summary_df.columns):
            ws.write(row, c, summary_df.iloc[r_idx, c], styles["body"])
        row += 1

    row += 1
    ws.write(row, 0, detail_title, styles["subtitle"])
    row += 1
    detail_header_row = row
    for c, col_name in enumerate(detail_df.columns):
        ws.write(row, c, col_name, styles["header"])
    row += 1

    pct_idx = (
        list(detail_df.columns).index(highlight_large_pct_col)
        if highlight_large_pct_col and highlight_large_pct_col in detail_df.columns
        else None
    )
    for r_idx in range(len(detail_df)):
        row_fmt = styles["body"]
        if pct_idx is not None:
            raw = detail_df.iloc[r_idx, pct_idx]
            try:
                val = float(str(raw).replace("%", "").replace("+", ""))
                if abs(val) >= pct_threshold:
                    row_fmt = styles["critical"]
            except (TypeError, ValueError):
                pass
        for c in range(len(detail_df.columns)):
            ws.write(row, c, detail_df.iloc[r_idx, c], row_fmt)
        row += 1

    widths = summary_widths or detail_widths or {}
    max_cols = max(len(summary_df.columns), len(detail_df.columns), 1)
    for c in range(max_cols):
        width = widths.get(c, 18)
        ws.set_column(c, c, width)
    ws.freeze_panes(detail_header_row + 1, 0)


def write_report(
    out_path: Path,
    diff: DiffResult,
    flags: list[Flag],
    summary: dict[str, Any],
    *,
    old_records: list[RateRecord] | None = None,
    new_records: list[RateRecord] | None = None,
    old_sheets: list[SheetInfo] | None = None,
    new_sheets: list[SheetInfo] | None = None,
    generic: GenericDiffResult | None = None,
) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import xlsxwriter  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Missing package 'xlsxwriter' (needed to write report.xlsx).\n"
            "In Colab run:\n"
            "  !pip install -q xlsxwriter\n"
            "or:\n"
            "  !pip install -q -r /content/tariff-errors-search/requirements.txt"
        ) from exc

    critical_df = _critical_flags(flags)
    review_df = _review_flags(flags)
    added_df = _record_rows(diff.only_new, change_label="New in new tariff")
    removed_df = _record_rows(diff.only_old, change_label="Removed from previous tariff")
    price_df = _price_change_rows(diff, summary)

    severity_counts = Counter(
        priority_label(f.severity)
        for f in flags
        if f.rule_id not in HIDDEN_FROM_FINDINGS
    )
    issue_type_counts = Counter(
        rule_title(f.rule_id) for f in flags if f.rule_id not in HIDDEN_FROM_FINDINGS
    )

    with pd.ExcelWriter(
        out_path,
        engine="xlsxwriter",
        engine_kwargs={"options": {"nan_inf_to_errors": True}},
    ) as writer:
        workbook = writer.book
        styles = _severity_style(workbook)

        # --- 1. Start here ---
        dash = workbook.add_worksheet("Start here")
        writer.sheets["Start here"] = dash
        row = 0
        dash.write(row, 0, "Tariff comparison report", styles["title"])
        row += 2
        dash.write(
            row,
            0,
            "This workbook compares your PREVIOUS tariff Excel file with the NEW one. "
            "Start with the «Critical issues» tab if any items are listed. "
            "Use «Recommended action» and «Where to look» columns to verify each point with the carrier.",
            styles["body"],
        )
        dash.set_row(row, 36)
        row += 3

        dash.write(row, 0, "Files compared", styles["subtitle"])
        row += 1
        overview = [
            ("Previous tariff file", summary.get("old_file", "")),
            ("New tariff file", summary.get("new_file", "")),
            ("Lines read from previous file", summary.get("old_record_count", "")),
            ("Lines read from new file", summary.get("new_record_count", "")),
            ("Rates that exist in both files", summary.get("matched_keys", "")),
            ("Rates with a price or text change", summary.get("changed", "")),
            ("Rates only in new file", summary.get("added", "")),
            ("Rates only in previous file", summary.get("removed", "")),
            ("Critical issues (must check)", summary.get("red_flags", 0)),
            ("Items to review (when you have time)", len(review_df)),
            ("Calculation rules (previous / new)", summary.get("logic_clauses_old_new", "-")),
        ]
        for label, val in overview:
            fmt = styles["kpi_red"] if label.startswith("Critical") and val else styles["kpi_value"]
            dash.write(row, 0, label, styles["kpi_label"])
            dash.write(row, 1, val, fmt)
            row += 1

        row += 1
        dash.write(row, 0, "How to read the other tabs", styles["subtitle"])
        row += 1
        tab_help = [
            "Critical issues — problems that may affect billing; check these first.",
            "Also review — changes worth confirming but not automatically critical "
            "(charge codes, service codes, postal/zone codes, etc.).",
            "Calculation rules — short summary (was / changed / new), then full wording.",
            "Price changes — pattern summary by sheet/type, then matched lane details.",
            "New in new tariff — summary by sheet/type, then each new line.",
            "Removed from previous — summary by sheet/type, then each removed line.",
        ]
        for line in tab_help:
            dash.write(row, 0, f"• {line}", styles["body"])
            dash.set_row(row, 28)
            row += 1

        if severity_counts:
            row += 1
            dash.write(row, 0, "Issues by priority", styles["header"])
            dash.write(row, 1, "Count", styles["header"])
            row += 1
            sev_start = row
            for sev, cnt in sorted(severity_counts.items()):
                dash.write(row, 0, sev, styles["body"])
                dash.write(row, 1, cnt, styles["body"])
                row += 1

            chart1 = workbook.add_chart({"type": "pie"})
            chart1.add_series(
                {
                    "categories": ["Start here", sev_start, 0, row - 1, 0],
                    "values": ["Start here", sev_start, 1, row - 1, 1],
                }
            )
            chart1.set_title({"name": "Issues by priority"})
            chart1.set_style(10)
            dash.insert_chart(2, 3, chart1, {"x_scale": 1.1, "y_scale": 1.1})

        if issue_type_counts:
            row += 1
            dash.write(row, 0, "Issues by type", styles["header"])
            dash.write(row, 1, "Count", styles["header"])
            row += 1
            type_start = row
            for issue_type, cnt in issue_type_counts.most_common(8):
                dash.write(row, 0, issue_type, styles["body"])
                dash.write(row, 1, cnt, styles["body"])
                row += 1
            if row > type_start:
                chart2 = workbook.add_chart({"type": "column"})
                chart2.add_series(
                    {
                        "categories": ["Start here", type_start, 0, row - 1, 0],
                        "values": ["Start here", type_start, 1, row - 1, 1],
                        "fill": {"color": "#2F5496"},
                    }
                )
                chart2.set_title({"name": "Most common issue types"})
                chart2.set_x_axis({"label_rotation": -30})
                dash.insert_chart(12, 3, chart2, {"x_scale": 1.2, "y_scale": 1.1})

        dash.set_column(0, 0, 42)
        dash.set_column(1, 1, 28)
        dash.set_column(3, 3, 24)

        # --- 2. Critical issues ---
        _write_dataframe(
            writer,
            "Critical issues",
            critical_df,
            styles,
            priority_col="Priority",
            col_widths={0: 5, 1: 22, 2: 24, 3: 48, 4: 22, 5: 22, 6: 36, 7: 36, 8: 44, 9: 16},
        )

        # --- 3. Also review ---
        _write_dataframe(
            writer,
            "Also review",
            review_df,
            styles,
            priority_col="Priority",
            col_widths={0: 5, 1: 22, 2: 24, 3: 48, 4: 22, 5: 22, 6: 36, 7: 36, 8: 44, 9: 16},
        )

        # --- 4. Calculation rules (summary first, then detail) ---
        if old_records is not None and new_records is not None:
            logic_summary = _logic_summary_df(old_records, new_records)
            logic_detail = pd.concat(
                [
                    _logic_rows(old_records, str(summary.get("old_file", "Previous"))),
                    _logic_rows(new_records, str(summary.get("new_file", "New"))),
                ],
                ignore_index=True,
            )
            _write_sheet_with_summary(
                writer,
                "Calculation rules",
                logic_summary,
                logic_detail,
                styles,
                summary_title="Summary — was → changed → new",
                detail_title="Details — full wording by file",
                summary_widths={0: 22, 1: 8, 2: 36, 3: 48, 4: 48},
                detail_widths={0: 36, 1: 32, 2: 28, 3: 70},
            )

        # --- 5. Price changes (summary first, then detail) ---
        cost_max = int(summary.get("cost_changes_detail_max", 100))
        cost_rows = build_cost_change_rows(diff)
        price_summary = _price_summary_df(diff)
        if len(cost_rows) <= cost_max and cost_rows:
            _write_sheet_with_summary(
                writer,
                "Price changes",
                price_summary,
                price_df,
                styles,
                summary_title="Summary — where prices changed (patterns)",
                detail_title="Details — matched lanes with amount change",
                highlight_large_pct_col="% change",
                pct_threshold=float(summary.get("price_change_red_flag_pct", 100)),
                summary_widths={0: 18, 1: 40, 2: 10, 3: 48},
                detail_widths={0: 16, 1: 18, 2: 14, 3: 18, 4: 14, 5: 14, 6: 14, 7: 12, 8: 12, 9: 16, 10: 16},
            )
        else:
            note_df = pd.DataFrame(
                [
                    {
                        "Note": (
                            summary.get("cost_changes_tab")
                            or "No matched price changes to list."
                        ),
                        "Explanation": (
                            "Price changes are only listed when the same lane exists in both files. "
                            "If many lanes show as new or removed, profiles may need alignment — "
                            "see Critical issues tab."
                        ),
                    }
                ]
            )
            _write_sheet_with_summary(
                writer,
                "Price changes",
                price_summary,
                note_df,
                styles,
                summary_title="Summary — where prices changed (patterns)",
                detail_title="Details",
                summary_widths={0: 18, 1: 40, 2: 10, 3: 48},
                detail_widths={0: 40, 1: 60},
            )

        # --- 6. New / Removed (summary first, then detail) ---
        added_detail = added_df.drop(columns=["Change"])
        removed_detail = removed_df.drop(columns=["Change"])
        _write_sheet_with_summary(
            writer,
            "New in new tariff",
            _record_summary_df(diff.only_new, kind="new"),
            added_detail,
            styles,
            summary_title="Summary — new lines by sheet / charge type",
            detail_title="Details — each new line",
            summary_widths={0: 18, 1: 40, 2: 10, 3: 36},
            detail_widths={0: 22, 1: 14, 2: 50, 3: 18, 4: 12, 5: 16},
        )
        _write_sheet_with_summary(
            writer,
            "Removed from previous",
            _record_summary_df(diff.only_old, kind="removed"),
            removed_detail,
            styles,
            summary_title="Summary — removed lines by sheet / charge type",
            detail_title="Details — each removed line",
            summary_widths={0: 18, 1: 40, 2: 10, 3: 36},
            detail_widths={0: 22, 1: 14, 2: 50, 3: 18, 4: 12, 5: 16},
        )

        # --- Optional: technical sheets for power users (hidden at end) ---
        if generic and generic.cell_changes:
            from collections import Counter as _Counter

            export_max = int(summary.get("generic_cell_export_max", 3000))
            rows = [ch.to_dict() for ch in generic.cell_changes[:export_max]]
            tech_df = pd.DataFrame(rows)
            _write_dataframe(writer, "Technical (cell diff)", tech_df, styles)

        # Keep machine-readable summary as last hidden-style tab for support
        tech_summary = pd.DataFrame(
            [
                {
                    "Previous file": summary.get("old_file"),
                    "New file": summary.get("new_file"),
                    "Matched": summary.get("matched_keys"),
                    "Changed": summary.get("changed"),
                    "Added": summary.get("added"),
                    "Removed": summary.get("removed"),
                    "Red flags": summary.get("red_flags"),
                }
            ]
        )
        _write_dataframe(writer, "Technical (summary)", tech_summary, styles)

    # Re-order sheets: move Start here first (xlsxwriter writes in order already)
