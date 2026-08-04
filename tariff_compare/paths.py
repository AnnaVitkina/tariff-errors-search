from __future__ import annotations

import os
from pathlib import Path

# Package location → code root (tariff-errors-search/)
_CODE_FROM_PACKAGE = Path(__file__).resolve().parent.parent

# =============================================================================
# Google Colab layout — edit DEFAULT_DATA_ROOT to your Drive folder.
#
#   CODE  → /content/tariff-errors-search/     (Python package + scripts)
#   DATA  → Google Drive                       (config/, input/, output/)
#
# Override without editing file:
#   os.environ["TARIFF_CODE_ROOT"] = "..."
#   os.environ["TARIFF_DATA_ROOT"] = "..."
# =============================================================================

DEFAULT_CODE_ROOT = Path(
    os.environ.get("TARIFF_CODE_ROOT") or "/content/tariff-errors-search"
)
DEFAULT_DATA_ROOT = Path(
    "/content/drive/Shareddrives/FA Ops Europe: Rate Maintenance Team "
    "/Documents/AI Adoption RMT/RMT_Red_Flags"
)

# Local dev: if config/ sits in the repo, use the repo as data root unless overridden.
if not os.environ.get("TARIFF_DATA_ROOT") and (_CODE_FROM_PACKAGE / "config").is_dir():
    DATA_ROOT = _CODE_FROM_PACKAGE
else:
    DATA_ROOT = DEFAULT_DATA_ROOT

CODE_ROOT = (
    _CODE_FROM_PACKAGE
    if (_CODE_FROM_PACKAGE / "tariff_compare").is_dir()
    else DEFAULT_CODE_ROOT
)

CONFIG_DIR = DATA_ROOT / "config"
PROFILES_DIR = CONFIG_DIR / "profiles"
THRESHOLDS_PATH = CONFIG_DIR / "thresholds.yaml"
EXTRACTION_PROFILE_SCHEMA_PATH = CONFIG_DIR / "extraction_profile_schema.yaml"
TARIFF_LINE_SCHEMA_PATH = CONFIG_DIR / "tariff_line_schema.yaml"

INPUT_DIR = DATA_ROOT / "input"
OLD_RATE_DIR = INPUT_DIR / "old rate"
NEW_RATE_DIR = INPUT_DIR / "new rate"
OUTPUT_DIR = DATA_ROOT / "output"


def resolve_data_path(path: Path | str | None) -> Path:
    if path is None:
        raise ValueError("resolve_data_path() received None — check CLI paths or interactive selection.")
    p = Path(path)
    return p.resolve() if p.is_absolute() else (DATA_ROOT / p).resolve()


def display_path(path: Path | str) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(DATA_ROOT.resolve()).as_posix()
    except ValueError:
        return str(p)


def ensure_data_dirs() -> None:
    for directory in (CONFIG_DIR, PROFILES_DIR, OLD_RATE_DIR, NEW_RATE_DIR, OUTPUT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
