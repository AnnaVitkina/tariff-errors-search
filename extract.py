from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_CODE_ROOT = Path("/content/tariff-errors-search")
_setup_file = _CODE_ROOT / "colab_setup.py"
if _setup_file.is_file():
    _spec = importlib.util.spec_from_file_location("colab_setup", _setup_file)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec.loader is not None
    _spec.loader.exec_module(_mod)
    _mod.install()
else:
    for _root in (_CODE_ROOT, Path.cwd()):
        if _root.is_dir() and (_root / "tariff_compare").is_dir():
            _s = str(_root.resolve())
            if _s not in sys.path:
                sys.path.insert(0, _s)
            break

from tariff_compare.file_prompt import (  # noqa: E402
    _is_interactive,
    discover_excel_files,
    resolve_path,
)
from tariff_compare.paths import (  # noqa: E402
    DATA_ROOT,
    OLD_RATE_DIR,
    NEW_RATE_DIR,
    PROFILES_DIR,
    ensure_data_dirs,
    resolve_data_path,
)
from tariff_compare.run_extract import discover_profiles, run_extract  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract TariffLine JSONL from .xlsx using a YAML profile (code, not Gem data dump)."
    )
    parser.add_argument("--profile", type=Path, default=None, help="Extraction profile YAML")
    parser.add_argument("--workbook", type=Path, default=None, help="Source .xlsx")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output .jsonl (default: next to workbook as <stem>-extract.jsonl)",
    )
    parser.add_argument(
        "--side",
        choices=("old", "new"),
        default=None,
        help="When interactive: pick workbook from input/old rate or input/new rate",
    )
    args = parser.parse_args()
    interactive = _is_interactive()

    ensure_data_dirs()
    profile_candidates = discover_profiles(PROFILES_DIR)

    profile_path = resolve_path(
        args.profile,
        "profile",
        "extraction profile YAML",
        profile_candidates,
        DATA_ROOT,
        title=f"Profiles in {PROFILES_DIR}:",
        interactive=interactive and args.profile is None,
        required=True,
    )
    assert profile_path is not None

    if args.side == "old":
        wb_root, label = OLD_RATE_DIR, "OLD"
    elif args.side == "new":
        wb_root, label = NEW_RATE_DIR, "NEW"
    else:
        wb_root, label = OLD_RATE_DIR, "workbook"
    wb_candidates = discover_excel_files(wb_root)
    if args.side is None and interactive and args.workbook is None:
        print(f"Which input folder?  [1] {OLD_RATE_DIR}  [2] {NEW_RATE_DIR}")
        try:
            ch = input("Choice (1/2, default 1): ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("Cancelled.") from None
        if ch == "2":
            wb_root, label = NEW_RATE_DIR, "NEW"
            wb_candidates = discover_excel_files(NEW_RATE_DIR)

    workbook_path = resolve_path(
        args.workbook,
        "workbook",
        f"{label} workbook (.xlsx)",
        wb_candidates,
        DATA_ROOT,
        title=f"Workbooks in {wb_root}:",
        interactive=interactive and args.workbook is None,
        required=True,
    )
    assert workbook_path is not None

    out_path = resolve_data_path(args.out) if args.out else None
    dest, line_count = run_extract(
        resolve_data_path(profile_path),
        resolve_data_path(workbook_path),
        out_path=out_path,
    )
    print(
        json.dumps(
            {
                "profile": str(profile_path),
                "workbook": str(workbook_path),
                "lines": line_count,
                "output": str(dest),
            },
            indent=2,
        )
    )
    print("\nNext: python compare.py  or  python pipeline.py")


if __name__ == "__main__":
    main()
