from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import yaml

from tariff_compare.cells import cell_str, parse_number
from tariff_compare.tariff_line import build_match_key

# Profile uses 1-based Excel row/column numbers.
TARIFF_LINE_FIELDS = frozenset(
    {
        "charge_kind",
        "mode",
        "charge_id",
        "origin_country",
        "origin_location",
        "dest_country",
        "dest_location",
        "service_level",
        "rate_component",
        "weight_break_label",
        "equipment",
        "currency",
        "billing_basis",
        "min_amount",
        "max_amount",
        "text_value",
        "calculation_method",
        "valid_from",
        "valid_to",
    }
)


def load_profile(path: Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not data.get("sheets"):
        raise ValueError(f"Profile has no sheets: {path}")
    return data


def _r0(excel_row: int) -> int:
    return excel_row - 1


def _c0(excel_col: int) -> int:
    return excel_col - 1


def _resolve_sheet_name(
    sheet_names: list[str],
    match: dict[str, Any],
    path: Path,
    df_by_sheet: dict[str, pd.DataFrame],
) -> str | None:
    if match.get("name"):
        n = str(match["name"])
        return n if n in sheet_names else None
    if match.get("name_contains"):
        sub = str(match["name_contains"]).lower()
        for sn in sheet_names:
            if sub in sn.lower():
                return sn
    title = match.get("title_cell") or {}
    if title.get("contains"):
        needle = str(title["contains"]).lower()
        tr = int(title.get("row", 1))
        tc = int(title.get("col", 1))
        for sn in sheet_names:
            df = df_by_sheet.get(sn)
            if df is None or df.empty:
                continue
            ri, ci = _r0(tr), _c0(tc)
            if ri < len(df) and ci < df.shape[1]:
                if needle in cell_str(df.iat[ri, ci]).lower():
                    return sn
    return None


def _read_field(
    df: pd.DataFrame, row_excel: int, col_spec: int | str | None
) -> Any:
    if col_spec is None:
        return None
    if isinstance(col_spec, int):
        c = _c0(col_spec)
        r = _r0(row_excel)
        if r >= len(df) or c >= df.shape[1]:
            return None
        val = df.iat[r, c]
        return None if cell_str(val) == "" else val
    return str(col_spec)


def _header_label(
    df: pd.DataFrame,
    col_excel: int,
    header_row: int,
    field_row: int | None = None,
) -> str:
    for row in (field_row, header_row):
        if row is None:
            continue
        ri, ci = _r0(row), _c0(col_excel)
        if ri < len(df) and ci < df.shape[1]:
            t = cell_str(df.iat[ri, ci])
            if t:
                return t
    return f"col{col_excel}"


_REMARKS_HEADER_RE = re.compile(r"(?i)^\s*remarks?\s*$")


def _find_remarks_column(df: pd.DataFrame, header_row: int) -> int | None:
    """Return 1-based Excel column whose header is Remark/Remarks (profile-independent)."""
    ri = _r0(header_row)
    if ri < 0 or ri >= len(df):
        return None
    for c in range(df.shape[1]):
        raw = cell_str(df.iat[ri, c])
        if not raw:
            continue
        # Headers may be multi-line; test each line and the collapsed form.
        for piece in (raw, raw.replace("\n", " ")):
            if _REMARKS_HEADER_RE.match(piece.strip()):
                return c + 1
            for line in raw.splitlines():
                if _REMARKS_HEADER_RE.match(line.strip()):
                    return c + 1
    return None


def _attach_remarks(
    row_base: dict[str, Any],
    df: pd.DataFrame,
    row_excel: int,
    remarks_col: int | None,
    *,
    profile_maps_text_value: bool,
) -> None:
    """Fill extras.remarks (and text_value when free) from an auto-detected Remarks column."""
    if remarks_col is None:
        return
    remarks = cell_str(_read_field(df, row_excel, remarks_col))
    if not remarks:
        return
    extras = dict(row_base.get("extras") or {})
    extras["remarks"] = remarks[:2000]
    row_base["extras"] = extras
    if not profile_maps_text_value and not row_base.get("text_value"):
        row_base["text_value"] = remarks[:2000]


def _emit_line(
    base: dict[str, Any],
    *,
    amount: float | None,
    rate_component: str | None,
    billing_basis: str | None,
    weight_break_label: str | None,
    source_sheet: str,
    source_row: int,
    source_col: int,
    source_file: str,
    min_amount: float | None = None,
    max_amount: float | None = None,
    text_value: str | None = None,
) -> dict[str, Any]:
    line = {k: base.get(k) for k in TARIFF_LINE_FIELDS}
    line.update(base)
    if rate_component is not None:
        line["rate_component"] = rate_component
    if billing_basis is not None:
        line["billing_basis"] = billing_basis
    if weight_break_label is not None:
        line["weight_break_label"] = weight_break_label
    line["amount"] = amount
    line["min_amount"] = min_amount
    line["max_amount"] = max_amount
    if text_value is not None:
        line["text_value"] = text_value
    line["source_sheet"] = source_sheet
    line["source_row"] = source_row
    line["source_col"] = source_col
    line["source_file"] = source_file
    line["match_key"] = build_match_key(line)
    line.setdefault("extras", {})
    return line


def _iter_wide_matrix(
    df: pd.DataFrame,
    sheet: str,
    source_file: str,
    table: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    header_row = int(table.get("header_row", 1))
    data_start = int(table.get("data_start_row", header_row + 1))
    data_end = table.get("data_end_row")
    last_row_excel = len(df) if data_end is None else int(data_end)

    charge_kind = table.get("charge_kind", "base_rate")
    mode = table.get("mode")
    col_map: dict[str, Any] = table.get("columns") or {}
    skip_col = table.get("skip_if_empty_column")

    defaults = {
        "charge_kind": charge_kind,
        "mode": mode,
    }
    for field, col in col_map.items():
        if field in TARIFF_LINE_FIELDS:
            defaults[field] = None  # filled per row

    currency_col = table.get("currency_column")
    profile_maps_text_value = "text_value" in col_map
    # Auto-pick Remark/Remarks even when the YAML profile omitted it.
    remarks_col = _find_remarks_column(df, header_row)

    for row_excel in range(data_start, last_row_excel + 1):
        ri = _r0(row_excel)
        if ri >= len(df):
            break
        if skip_col is not None:
            if not cell_str(df.iat[ri, _c0(int(skip_col))]):
                continue

        row_base = dict(defaults)
        for field, col in col_map.items():
            if field not in TARIFF_LINE_FIELDS:
                continue
            val = _read_field(df, row_excel, col)
            if val is not None:
                row_base[field] = cell_str(val) if not isinstance(val, (int, float)) else val

        currency = None
        if currency_col is not None:
            currency = cell_str(_read_field(df, row_excel, currency_col)) or table.get(
                "default_currency", "EUR"
            )
        row_base["currency"] = currency
        _attach_remarks(
            row_base,
            df,
            row_excel,
            remarks_col,
            profile_maps_text_value=profile_maps_text_value,
        )

        for rc in table.get("rate_columns") or []:
            col = int(rc["col"])
            amount = parse_number(df.iat[_r0(row_excel), _c0(col)])
            if amount is None:
                continue
            yield _emit_line(
                row_base,
                amount=amount,
                rate_component=rc.get("rate_component"),
                billing_basis=rc.get("billing_basis"),
                weight_break_label=rc.get("weight_break_label"),
                source_sheet=sheet,
                source_row=row_excel,
                source_col=col,
                source_file=source_file,
            )

        rcr = table.get("rate_column_range")
        if rcr:
            hr = int(rcr.get("header_row", header_row))
            fr = rcr.get("field_row")
            fr = int(fr) if fr is not None else None
            from_c = int(rcr["from_col"])
            to_c = int(rcr["to_col"])
            default_basis = rcr.get("billing_basis", "per_kg")
            for col in range(from_c, to_c + 1):
                ci = _c0(col)
                if ci >= df.shape[1]:
                    continue
                hdr = _header_label(df, col, hr, fr)
                if not hdr or hdr.lower() == "id":
                    continue
                amount = parse_number(df.iat[ri, ci])
                if amount is None:
                    continue
                comp = rcr.get("rate_component_prefix", "")
                rate_comp = f"{comp}{hdr}" if comp else hdr
                yield _emit_line(
                    row_base,
                    amount=amount,
                    rate_component=rate_comp,
                    billing_basis=default_basis,
                    weight_break_label=hdr,
                    source_sheet=sheet,
                    source_row=row_excel,
                    source_col=col,
                    source_file=source_file,
                )

        for sc in table.get("scalar_columns") or []:
            col = int(sc["col"])
            amount = parse_number(df.iat[ri, _c0(col)])
            if amount is None and sc.get("optional", True):
                continue
            yield _emit_line(
                row_base,
                amount=amount,
                rate_component=sc.get("rate_component", "cost"),
                billing_basis=sc.get("billing_basis"),
                weight_break_label=None,
                source_sheet=sheet,
                source_row=row_excel,
                source_col=col,
                source_file=source_file,
                min_amount=parse_number(df.iat[ri, _c0(sc["min_col"])])
                if sc.get("min_col")
                else None,
                max_amount=parse_number(df.iat[ri, _c0(sc["max_col"])])
                if sc.get("max_col")
                else None,
            )


def _iter_logic_scan(
    df: pd.DataFrame,
    sheet: str,
    source_file: str,
    table: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    # Always include common contract patterns so floater / rounding / fuel text
    # is caught even when the Gem profile omitted them.
    _DEFAULT_LOGIC_PATTERNS: list[dict[str, str]] = [
        {
            "id": "rounding_rule",
            "label": "Decimal rounding and weight rule",
            "regex": r"(?i)decimal\s*places|price\s*per\s*100\s*kg|round(?:ing)?\s*up.*(?:weight|kg|hundred)",
        },
        {
            "id": "floater_rule",
            "label": "Fuel / diesel floater",
            "regex": r"(?i)\bfloater\b|dieselfloater|diesel\s*floater|lng\s*floater|hvo\s*floater|no\s*floater\s*applicable",
        },
        {
            "id": "fuel_surcharge_rule",
            "label": "Fuel surcharge wording",
            "regex": r"(?i)fuel\s*surcharge|fsc\b",
        },
    ]
    seen_ids = {str(p.get("id")) for p in (table.get("patterns") or []) if p.get("id")}
    patterns = list(table.get("patterns") or [])
    for p in _DEFAULT_LOGIC_PATTERNS:
        if p["id"] not in seen_ids:
            patterns.append(p)

    compiled = [
        (p["id"], p.get("label", p["id"]), re.compile(p["regex"], re.I)) for p in patterns
    ]
    if not compiled:
        return
    # One hit per logic_id per sheet (prefer first match) so OLD/NEW compare by rule id.
    emitted_ids: set[str] = set()
    for r in range(len(df)):
        for c in range(df.shape[1]):
            text = cell_str(df.iat[r, c])
            if not text or len(text) < 8:
                continue
            for logic_id, label, rx in compiled:
                if logic_id in emitted_ids:
                    continue
                if rx.search(text):
                    # Prefer richer wording from nearby cells on the same row
                    # (e.g. label «Floater:» + value «No Floater applicable.»).
                    neighbor_bits: list[str] = []
                    for cc in range(max(0, c - 1), min(df.shape[1], c + 4)):
                        bit = cell_str(df.iat[r, cc])
                        if bit:
                            neighbor_bits.append(bit)
                    rich = " ".join(neighbor_bits).strip()
                    use_text = rich if len(rich) > len(text) else text
                    line = _emit_line(
                        {
                            "charge_kind": "contract_logic",
                            "mode": None,
                            "calculation_method": logic_id,
                            "rate_component": label,
                            "charge_id": logic_id,
                        },
                        amount=None,
                        rate_component=label,
                        billing_basis=None,
                        weight_break_label=None,
                        text_value=use_text[:2000],
                        source_sheet=sheet,
                        source_row=r + 1,
                        source_col=c + 1,
                        source_file=source_file,
                    )
                    line["extras"] = {"logic_id": logic_id, "logic_label": label}
                    # Stable key across OLD/NEW so wording changes raise LOGIC_TEXT_CHANGED.
                    line["match_key"] = f"contract_logic|{logic_id}|{sheet}"
                    emitted_ids.add(logic_id)
                    yield line
                    break


def extract_workbook(
    workbook_path: Path,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    workbook_path = Path(workbook_path)
    source_file = profile.get("source_file") or workbook_path.name
    xl = pd.ExcelFile(workbook_path, engine="openpyxl")
    df_by_sheet = {
        sn: pd.read_excel(workbook_path, sheet_name=sn, header=None, engine="openpyxl")
        for sn in xl.sheet_names
    }
    lines: list[dict[str, Any]] = []
    for sheet_cfg in profile.get("sheets") or []:
        match = sheet_cfg.get("sheet_match") or {}
        tables = sheet_cfg.get("tables") or []
        if match.get("all_sheets"):
            target_sheets = list(xl.sheet_names)
        else:
            sn = _resolve_sheet_name(xl.sheet_names, match, workbook_path, df_by_sheet)
            target_sheets = [sn] if sn else []
        for sn in target_sheets:
            if sn is None:
                continue
            df = df_by_sheet[sn]
            for table in tables:
                ttype = table.get("type", "wide_matrix")
                if ttype == "wide_matrix":
                    lines.extend(_iter_wide_matrix(df, sn, source_file, table))
                elif ttype == "logic_scan":
                    lines.extend(_iter_logic_scan(df, sn, source_file, table))
    return lines


def write_tariff_lines(path: Path, lines: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
