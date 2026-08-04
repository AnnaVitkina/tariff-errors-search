from __future__ import annotations

import os
import sys

# Bootstrap sys.path BEFORE tariff_compare imports (Colab exec()-safe: os/sys only).
_SETUP = "/content/tariff-errors-search/colab_setup.py"
if os.path.isfile(_SETUP):
    with open(_SETUP, encoding="utf-8") as _f:
        exec(compile(_f.read(), _SETUP, "exec"), {"__file__": _SETUP, "os": os, "sys": sys})
else:
    for _root in ("/content/tariff-errors-search", os.getcwd()):
        if os.path.isdir(os.path.join(_root, "tariff_compare")):
            if _root not in sys.path:
                sys.path.insert(0, _root)
            break
    else:
        if "/content/tariff-errors-search" not in sys.path:
            sys.path.insert(0, "/content/tariff-errors-search")

import argparse
import json
from pathlib import Path

from tariff_compare.file_prompt import (  # noqa: E402
    _is_interactive,
    _print_candidates,
    discover_excel_files,
    resolve_path,
)
from tariff_compare.paths import (  # noqa: E402
    DATA_ROOT,
    NEW_RATE_DIR,
    OLD_RATE_DIR,
    OUTPUT_DIR,
    PROFILES_DIR,
    TARIFF_LINE_SCHEMA_PATH,
    THRESHOLDS_PATH,
    display_path,
    ensure_data_dirs,
    resolve_data_path,
)
from tariff_compare.run_compare import run_compare  # noqa: E402
from tariff_compare.run_extract import discover_profiles, run_extract  # noqa: E402
from tariff_compare.run_naming import (  # noqa: E402
    allocate_run_dir,
    default_extract_path,
    default_run_dir_name,
)


_PIPELINE_CLI_FLAGS = (
    "--old-profile",
    "--new-profile",
    "--profile",
    "--old",
    "--new",
    "--skip-extract",
    "--run-name",
    "--out",
    "--thresholds",
)


def _is_notebook_kernel() -> bool:
    """Colab/Jupyter: argv is the kernel launcher, not pipeline.py."""
    prog = os.path.basename(sys.argv[0]) if sys.argv else ""
    if "kernel" in prog.lower() or prog.startswith("ipykernel"):
        return True
    if "IPython" in sys.modules:
        return True
    try:
        get_ipython  # type: ignore[name-defined]  # noqa: B018
        return True
    except NameError:
        pass
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


def _kernel_polluted_argv() -> bool:
    """True when Jupyter/Colab left launcher args in sys.argv (unsafe for argparse)."""
    if not sys.argv:
        return False
    prog = os.path.basename(sys.argv[0]).lower()
    return "kernel" in prog or prog == "colab_kernel_launcher.py"


def _argv_for_parser() -> list[str] | None:
    """Notebook kernels pass -f kernel.json (and sometimes pipeline.py) — strip for argparse."""
    if not _is_notebook_kernel() and not _kernel_polluted_argv():
        return None

    cleaned: list[str] = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        token = args[i]
        if token in ("-f",):
            i += 2
            continue
        if token.endswith(".py"):
            i += 1
            continue
        if token in _PIPELINE_CLI_FLAGS or token.split("=", 1)[0] in _PIPELINE_CLI_FLAGS:
            cleaned.append(token)
            if "=" not in token and i + 1 < len(args) and not args[i + 1].startswith("-"):
                cleaned.append(args[i + 1])
                i += 2
                continue
        i += 1
    return cleaned


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end: pick profile + OLD/NEW workbooks from input folders, "
            "extract JSONL, compare, write report under output/ with a clear folder name."
        )
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="One profile for BOTH workbooks (same Excel layout).",
    )
    parser.add_argument(
        "--old-profile",
        default=None,
        help="Profile for OLD .xlsx only (e.g. etp_ratecard_ambient_d2_v1.yaml).",
    )
    parser.add_argument(
        "--new-profile",
        default=None,
        help="Profile for NEW .xlsx only (e.g. tarif_siemens_2026_v1.yaml).",
    )
    parser.add_argument("--old", default=None, help="OLD .xlsx in input/old rate/")
    parser.add_argument("--new", default=None, help="NEW .xlsx in input/new rate/")
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Output folder name under output/ (default: compare_<oldStem>__vs__<newStem>)",
    )
    parser.add_argument("--out", default=None, help="Output base directory (default: DATA_ROOT/output)")
    parser.add_argument("--thresholds", default=None, help="thresholds.yaml path")
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Use existing <workbook>-extract.jsonl next to each .xlsx (do not re-run extract)",
    )
    parse_argv = argv if argv is not None else _argv_for_parser()
    if parse_argv is None and _kernel_polluted_argv():
        parse_argv = []
    args = parser.parse_args(parse_argv)
    interactive = _is_interactive()

    ensure_data_dirs()

    profile_candidates = discover_profiles(PROFILES_DIR)
    old_xlsx = discover_excel_files(OLD_RATE_DIR)
    new_xlsx = discover_excel_files(NEW_RATE_DIR)

    if interactive and not any(
        [args.profile, args.old_profile, args.new_profile, args.old, args.new]
    ):
        print("Tariff pipeline — extract both workbooks to TariffLine JSONL, then compare.")
        print(f"  Data root (Drive): {DATA_ROOT}")
        print(f"  Profiles:          {PROFILES_DIR}")
        print(f"  OLD workbook:      {OLD_RATE_DIR}")
        print(f"  NEW workbook:      {NEW_RATE_DIR}")
        print(f"  Report:            {OUTPUT_DIR}/<run-name>/report.xlsx\n")

    pick_old_profile = interactive and args.old_profile is None and args.profile is None
    old_profile_path = resolve_path(
        Path(args.old_profile) if args.old_profile else (Path(args.profile) if args.profile else None),
        "old-profile",
        "OLD extraction profile (YAML)",
        profile_candidates,
        DATA_ROOT,
        title=f"Profile for OLD workbook ({PROFILES_DIR}):",
        interactive=pick_old_profile,
        required=True,
    )
    assert old_profile_path is not None
    old_profile_path = resolve_data_path(old_profile_path)

    if args.new_profile is not None:
        new_profile_path = resolve_path(
            Path(args.new_profile),
            "new-profile",
            "NEW extraction profile (YAML)",
            profile_candidates,
            DATA_ROOT,
            title=f"Profile for NEW workbook ({PROFILES_DIR}):",
            interactive=False,
            required=True,
        )
        assert new_profile_path is not None
        new_profile_path = resolve_data_path(new_profile_path)
    elif args.profile is not None and args.old_profile is None:
        new_profile_path = old_profile_path
    elif interactive and args.new_profile is None and args.profile is None:
        print("\n--- Profile for NEW workbook ---")
        print(f"  Press Enter to reuse OLD profile: {old_profile_path.name}")
        _print_candidates(
            profile_candidates,
            DATA_ROOT,
            title=f"Or pick a different profile ({PROFILES_DIR}):",
        )
        try:
            raw = input("Enter number, path, or Enter to reuse OLD profile: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("Cancelled.") from None
        if not raw:
            new_profile_path = old_profile_path
        else:
            from tariff_compare.file_prompt import _resolve_choice

            chosen = _resolve_choice(raw, profile_candidates, DATA_ROOT)
            if chosen is None:
                raise SystemExit("Invalid NEW profile selection.")
            new_profile_path = resolve_data_path(chosen)
    else:
        new_profile_path = old_profile_path

    old_wb = resolve_path(
        Path(args.old) if args.old else None,
        "old",
        "OLD workbook (.xlsx)",
        old_xlsx,
        DATA_ROOT,
        title=f"Workbooks in {OLD_RATE_DIR}:",
        interactive=interactive and args.old is None,
        required=True,
    )
    assert old_wb is not None

    new_wb = resolve_path(
        Path(args.new) if args.new else None,
        "new",
        "NEW workbook (.xlsx)",
        new_xlsx,
        DATA_ROOT,
        title=f"Workbooks in {NEW_RATE_DIR}:",
        disallow=old_wb,
        interactive=interactive and args.new is None,
        required=True,
    )
    assert new_wb is not None

    old_wb = resolve_data_path(old_wb)
    new_wb = resolve_data_path(new_wb)

    old_ext = default_extract_path(old_wb)
    new_ext = default_extract_path(new_wb)

    if args.skip_extract:
        for p in (old_ext, new_ext):
            if not p.is_file():
                raise SystemExit(f"--skip-extract but missing: {p}")
        print("Skipping extract; using existing JSONL next to workbooks.")
    else:
        run_extract(old_profile_path, old_wb, out_path=old_ext)
        run_extract(new_profile_path, new_wb, out_path=new_ext)

    run_name = args.run_name or default_run_dir_name(old_wb.name, new_wb.name)
    out_base = resolve_data_path(args.out or OUTPUT_DIR)
    run_dir = allocate_run_dir(out_base, run_name)

    summary = run_compare(
        old_ext=old_ext,
        new_ext=new_ext,
        run_dir=run_dir,
        thresholds_path=resolve_data_path(args.thresholds or THRESHOLDS_PATH),
        old_workbook=old_wb,
        new_workbook=new_wb,
        compare_method="profile_extract_pipeline",
    )

    meta = {
        "data_root": str(DATA_ROOT),
        "old_profile": display_path(old_profile_path),
        "new_profile": display_path(new_profile_path),
        "common_schema": display_path(TARIFF_LINE_SCHEMA_PATH),
        "run_dir": display_path(run_dir),
        "report": display_path(run_dir / "report.xlsx"),
        "old_workbook": display_path(old_wb),
        "new_workbook": display_path(new_wb),
        "old_extraction": display_path(old_ext),
        "new_extraction": display_path(new_ext),
    }
    with (run_dir / "pipeline.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("\nPipeline done.")
    print(json.dumps(meta, indent=2))
    print(f"\nOpen report: {run_dir / 'report.xlsx'}")


if __name__ == "__main__":
    main(_argv_for_parser())
