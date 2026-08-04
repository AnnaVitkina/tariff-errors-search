from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.utils import get_column_letter


@dataclass
class CellChange:
    sheet: str
    cell: str
    row: int
    col: int
    old_value: Any
    new_value: Any
    change_type: str  # modified | added | removed
    pct_change: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "cell": self.cell,
            "row": self.row,
            "col": self.col,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "change_type": self.change_type,
            "pct_change": self.pct_change,
        }


@dataclass
class GenericDiffResult:
    cell_changes: list[CellChange] = field(default_factory=list)
    sheets_only_old: list[str] = field(default_factory=list)
    sheets_only_new: list[str] = field(default_factory=list)
    sheets_compared: int = 0


def _is_empty(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


def _normalize(val: Any) -> Any:
    if _is_empty(val):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        f = float(val)
        if math.isfinite(f) and abs(f - round(f)) < 1e-9:
            return round(f, 6)
        return round(f, 6)
    if hasattr(val, "isoformat"):
        return str(val)[:19]
    s = str(val).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _pct_change(old: float, new: float) -> float | None:
    if old == 0:
        return None if new == 0 else float("inf")
    return (new - old) / abs(old) * 100.0


def _cell_ref(r: int, c: int) -> str:
    return f"{get_column_letter(c + 1)}{r + 1}"


def diff_workbooks_generic(old_path: Path, new_path: Path) -> GenericDiffResult:
    """Pair-wise cell diff on sheets with the same name (layout-agnostic)."""
    old_path, new_path = Path(old_path), Path(new_path)
    xl_old = pd.ExcelFile(old_path, engine="openpyxl")
    xl_new = pd.ExcelFile(new_path, engine="openpyxl")
    names_old = set(xl_old.sheet_names)
    names_new = set(xl_new.sheet_names)
    result = GenericDiffResult(
        sheets_only_old=sorted(names_old - names_new),
        sheets_only_new=sorted(names_new - names_old),
    )

    for sheet in sorted(names_old & names_new):
        df_o = pd.read_excel(old_path, sheet_name=sheet, header=None, engine="openpyxl")
        df_n = pd.read_excel(new_path, sheet_name=sheet, header=None, engine="openpyxl")
        max_r = max(df_o.shape[0], df_n.shape[0])
        max_c = max(df_o.shape[1], df_n.shape[1])
        result.sheets_compared += 1

        for r in range(max_r):
            for c in range(max_c):
                vo = df_o.iat[r, c] if r < df_o.shape[0] and c < df_o.shape[1] else None
                vn = df_n.iat[r, c] if r < df_n.shape[0] and c < df_n.shape[1] else None
                no, nn = _normalize(vo), _normalize(vn)
                if no == nn:
                    continue
                if no is None and nn is None:
                    continue
                if no is None:
                    ctype = "added"
                elif nn is None:
                    ctype = "removed"
                else:
                    ctype = "modified"
                pct = None
                if isinstance(no, (int, float)) and isinstance(nn, (int, float)):
                    pct = _pct_change(float(no), float(nn))
                result.cell_changes.append(
                    CellChange(
                        sheet=sheet,
                        cell=_cell_ref(r, c),
                        row=r + 1,
                        col=c + 1,
                        old_value=vo if not _is_empty(vo) else None,
                        new_value=vn if not _is_empty(vn) else None,
                        change_type=ctype,
                        pct_change=pct,
                    )
                )

    return result


def numeric_cost_changes(changes: list[CellChange]) -> list[CellChange]:
    """Cells where both sides look like numeric rates/costs."""
    out: list[CellChange] = []
    for ch in changes:
        no, nn = _normalize(ch.old_value), _normalize(ch.new_value)
        if isinstance(no, (int, float)) and isinstance(nn, (int, float)):
            if no != nn:
                out.append(ch)
        elif ch.change_type == "added" and isinstance(nn, (int, float)):
            out.append(ch)
        elif ch.change_type == "removed" and isinstance(no, (int, float)):
            out.append(ch)
    return out
