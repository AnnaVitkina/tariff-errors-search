from __future__ import annotations

import re
from pathlib import Path


def _sanitize_token(name: str, *, max_len: int = 48) -> str:
    stem = Path(name).stem if name else "file"
    s = re.sub(r"[^\w\-.]+", "_", stem, flags=re.ASCII)
    s = re.sub(r"_+", "_", s).strip("_.")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s or "file"


def default_run_dir_name(old_label: str, new_label: str) -> str:
    """Human-readable folder name under output/."""
    return f"compare_{_sanitize_token(old_label)}__vs__{_sanitize_token(new_label)}"


def allocate_run_dir(out_base: Path, preferred_name: str) -> Path:
    """Pick out_base / preferred_name; if taken, append _2, _3, …"""
    out_base = Path(out_base)
    out_base.mkdir(parents=True, exist_ok=True)
    candidate = out_base / preferred_name
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    n = 2
    while True:
        alt = out_base / f"{preferred_name}_{n}"
        if not alt.exists():
            alt.mkdir(parents=True, exist_ok=True)
            return alt
        n += 1


def default_extract_path(workbook: Path) -> Path:
    return workbook.parent / f"{workbook.stem}-extract.jsonl"
