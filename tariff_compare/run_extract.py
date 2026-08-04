from __future__ import annotations

from pathlib import Path

from tariff_compare.profile_extract import extract_workbook, load_profile, write_tariff_lines
from tariff_compare.run_naming import default_extract_path


def discover_profiles(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(root.glob("*.yaml"), key=lambda p: p.name.lower())


def run_extract(
    profile_path: Path,
    workbook_path: Path,
    *,
    out_path: Path | None = None,
) -> tuple[Path, int]:
    profile_path = Path(profile_path).resolve()
    workbook_path = Path(workbook_path).resolve()
    profile = load_profile(profile_path)
    profile["source_file"] = workbook_path.name

    print(f"Extract — profile: {profile_path.name}")
    print(f"         workbook: {workbook_path.name}")
    lines = extract_workbook(workbook_path, profile)
    print(f"  -> {len(lines)} TariffLine(s)")

    dest = Path(out_path) if out_path else default_extract_path(workbook_path)
    write_tariff_lines(dest, lines)
    print(f"  -> wrote {dest.name}")
    return dest, len(lines)
