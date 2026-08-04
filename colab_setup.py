"""Colab bootstrap: sys.path + missing pip deps (safe when pipeline.py is run via exec())."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

CODE_ROOT = "/content/tariff-errors-search"

_RUNTIME_PACKAGES = (
    ("xlsxwriter", "xlsxwriter"),
    ("openpyxl", "openpyxl"),
    ("pyyaml", "yaml"),
    ("pandas", "pandas"),
)


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


def ensure_runtime_deps() -> None:
    """On Colab, pip-install packages from requirements.txt if they are missing."""
    if not os.environ.get("COLAB_RELEASE_TAG"):
        return
    missing = [pkg for pkg, mod in _RUNTIME_PACKAGES if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    print(f"Installing missing packages for Colab: {', '.join(missing)}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", *missing],
    )


install()
ensure_runtime_deps()
