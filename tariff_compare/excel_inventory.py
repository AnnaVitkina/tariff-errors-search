from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class SheetInfo:
    name: str
    rows: int
    cols: int


def inventory_workbook(path: Path) -> list[SheetInfo]:
    path = Path(path)
    xl = pd.ExcelFile(path, engine="openpyxl")
    out: list[SheetInfo] = []
    for name in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=name, header=None, engine="openpyxl")
        out.append(SheetInfo(name=name, rows=df.shape[0], cols=df.shape[1]))
    return out
