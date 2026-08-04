"""Add code folder to sys.path — os/sys only (safe when pipeline.py is run via exec())."""

from __future__ import annotations

import os
import sys

CODE_ROOT = "/content/tariff-errors-search"


def install() -> str:
    roots: list[str] = []
    try:
        roots.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    roots.extend([CODE_ROOT, os.getcwd()])
    seen: set[str] = set()
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        if os.path.isdir(os.path.join(root, "tariff_compare")):
            if root not in sys.path:
                sys.path.insert(0, root)
            return root
    if CODE_ROOT not in sys.path:
        sys.path.insert(0, CODE_ROOT)
    return CODE_ROOT


install()
