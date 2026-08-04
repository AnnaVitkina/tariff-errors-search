from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tariff_compare.models import RateRecord


def write_jsonl(records: list[RateRecord], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL (one object per line). Also accepts a single JSON array in a .json file."""
    path = Path(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        raise ValueError(f"Expected JSON array in {path}")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def records_by_key(records: list[RateRecord]) -> dict[str, RateRecord]:
    out: dict[str, RateRecord] = {}
    for rec in records:
        out[rec.lane_key] = rec
    return out
