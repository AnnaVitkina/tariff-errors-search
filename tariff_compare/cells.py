from __future__ import annotations

import math
import re
from typing import Any


def cell_str(val: Any) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()


def parse_number(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = cell_str(val).replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in (".", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
