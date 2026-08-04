from __future__ import annotations

import sys
from pathlib import Path


def bootstrap_code_root() -> Path:
    """Put the code folder on sys.path (needed when pipeline.py is run via exec())."""
    candidates: list[Path] = []

    if "__file__" in globals():
        try:
            candidates.append(Path(__file__).resolve().parent.parent)
        except (NameError, TypeError, ValueError):
            pass

    candidates.extend(
        [
            Path("/content/tariff-errors-search"),
            Path.cwd(),
        ]
    )

    for root in candidates:
        if root.is_dir() and (root / "tariff_compare").is_dir():
            root_str = str(root.resolve())
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            return root.resolve()

    fallback = Path("/content/tariff-errors-search").resolve()
    fallback_str = str(fallback)
    if fallback_str not in sys.path:
        sys.path.insert(0, fallback_str)
    return fallback
