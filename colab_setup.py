from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime, timezone
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
    discover_jsonl_files,
    resolve_path,
)
from tariff_compare.paths import (  # noqa: E402
    DATA_ROOT,
    OLD_RATE_DIR,
    NEW_RATE_DIR,
    OUTPUT_DIR,
    THRESHOLDS_PATH,
    ensure_data_dirs,
    resolve_data_path,
)
from tariff_compare.run_compare import run_compare  # noqa: E402
from tariff_compare.run_naming import allocate_run_dir, default_run_dir_name  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare OLD vs NEW tariff extractions (JSONL). "
            "Optional .xlsx for workbook inventory / labels only."
        )
    )
    parser.add_argument(
        "--old",
        type=Path,
        default=None,
        help="OLD .xlsx under input/old rate/ (optional).",
    )
    parser.add_argument(
        "--new",
        type=Path,
        default=None,
        help="NEW .xlsx under input/new rate/ (optional).",
    )
    parser.add_argument(
        "--old-extraction",
        type=Path,
        default=None,
        help="JSONL/JSON for OLD (under input/old rate/).",
    )
    parser.add_argument(
        "--new-extraction",
        type=Path,
        default=None,
        help="JSONL/JSON for NEW (under input/new rate/).",
    )
    parser.add_argument(
        "--no-workbooks",
        action="store_true",
        help="Do not use or prompt for .xlsx files (compare JSONL only).",
    )
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Output folder under output/ (default: compare_<old>__vs__<new>).",
    )
    parser.add_argument(
        "--timestamp-run-id",
        action="store_true",
        help="Use output/YYYYMMDD_HHMMSS/ instead of a descriptive folder name.",
    )
    args = parser.parse_args()

    interactive = _is_interactive()
    ensure_data_dirs()

    old_jsonl_candidates = discover_jsonl_files(OLD_RATE_DIR)
    new_jsonl_candidates = discover_jsonl_files(NEW_RATE_DIR)
    old_xlsx_candidates = discover_excel_files(OLD_RATE_DIR)
    new_xlsx_candidates = discover_excel_files(NEW_RATE_DIR)

    if interactive and not any(
        [args.old, args.new, args.old_extraction, args.new_extraction]
    ):
        print("Tariff compare — pick JSONL (and optional workbooks).")
        print("  For extract + compare in one step, use: python pipeline.py")
        print(f"  OLD: {OLD_RATE_DIR}")
        print(f"  NEW: {NEW_RATE_DIR}")
        if not old_jsonl_candidates and not new_jsonl_candidates:
            print(
                "\nTip: run python pipeline.py or save extractions as .jsonl in those folders."
            )

    if (
        not old_jsonl_candidates
        and not new_jsonl_candidates
        and args.old_extraction is None
        and args.new_extraction is None
        and not interactive
    ):
        raise SystemExit(
            f"No extractions under {OLD_RATE_DIR} or {NEW_RATE_DIR}. "
            "Use pipeline.py or pass --old-extraction / --new-extraction."
        )

    old_ext = resolve_path(
        args.old_extraction,
        "old-extraction",
        "OLD extraction (JSONL/JSON)",
        old_jsonl_candidates,
        DATA_ROOT,
        title=f"Files in {OLD_RATE_DIR}:",
        interactive=interactive,
        required=True,
    )
    assert old_ext is not None

    new_ext = resolve_path(
        args.new_extraction,
        "new-extraction",
        "NEW extraction (JSONL/JSON)",
        new_jsonl_candidates,
        DATA_ROOT,
        title=f"Files in {NEW_RATE_DIR}:",
        interactive=interactive,
        required=True,
    )
    assert new_ext is not None

    if old_ext.resolve() == new_ext.resolve():
        raise SystemExit("OLD and NEW extraction files must be different.")

    use_workbooks = not args.no_workbooks
    old_path: Path | None = None
    new_path: Path | None = None
    if use_workbooks:
        old_path = resolve_path(
            args.old,
            "old",
            "OLD workbook (.xlsx)",
            old_xlsx_candidates,
            DATA_ROOT,
            title=f"Workbooks in {OLD_RATE_DIR}:",
            interactive=interactive,
            required=False,
            allow_skip=interactive,
        )
        new_path = resolve_path(
            args.new,
            "new",
            "NEW workbook (.xlsx)",
            new_xlsx_candidates,
            DATA_ROOT,
            title=f"Workbooks in {NEW_RATE_DIR}:",
            disallow=old_path,
            interactive=interactive,
            required=False,
            allow_skip=interactive,
        )

    out_base = resolve_data_path(args.out)
    if args.timestamp_run_id:
        run_name = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    elif args.run_name:
        run_name = args.run_name
    else:
        old_lbl = old_path.name if old_path else old_ext.name
        new_lbl = new_path.name if new_path else new_ext.name
        run_name = default_run_dir_name(old_lbl, new_lbl)
    run_dir = allocate_run_dir(out_base, run_name)

    run_compare(
        old_ext=resolve_data_path(old_ext),
        new_ext=resolve_data_path(new_ext),
        run_dir=run_dir,
        thresholds_path=resolve_data_path(args.thresholds),
        old_workbook=resolve_data_path(old_path) if old_path else None,
        new_workbook=resolve_data_path(new_path) if new_path else None,
        compare_method="gem_tariff_line_diff",
    )


if __name__ == "__main__":
    main()
