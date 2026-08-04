from __future__ import annotations

import os
import sys
from pathlib import Path


def is_notebook_kernel() -> bool:
    """True in Colab / Jupyter (cell exec, !python subprocess, or kernel argv)."""
    if os.environ.get("COLAB_RELEASE_TAG"):
        return True
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


def discover_excel_files(root: Path) -> list[Path]:
    """List .xlsx in this folder only (not subfolders of sibling input dirs)."""
    root = Path(root)
    if not root.is_dir():
        return []
    files: list[Path] = []
    for p in root.iterdir():
        if p.is_file() and p.suffix.lower() == ".xlsx" and not p.name.startswith("~$"):
            files.append(p.resolve())
    return sorted(files, key=lambda p: p.name.lower())


def discover_jsonl_files(root: Path) -> list[Path]:
    """Gem extractions: .jsonl and .json in this folder only."""
    root = Path(root)
    if not root.is_dir():
        return []
    files: list[Path] = []
    for p in root.iterdir():
        if not p.is_file() or p.name.startswith("~$"):
            continue
        if p.suffix.lower() in (".jsonl", ".json"):
            files.append(p.resolve())
    return sorted(files, key=lambda p: p.name.lower())


def _is_interactive() -> bool:
    """Notebooks (Colab) are interactive even when stdin is not a TTY."""
    if is_notebook_kernel():
        return True
    return sys.stdin.isatty() and sys.stdout.isatty()


def _rel_display(p: Path, project_root: Path) -> str:
    try:
        return p.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(p)


def _print_candidates(
    candidates: list[Path],
    project_root: Path,
    *,
    title: str,
) -> None:
    print(f"\n{title}")
    if not candidates:
        print("  (none found — enter a full path, or place files under input/)")
        return
    for i, p in enumerate(candidates, start=1):
        print(f"  [{i}] {_rel_display(p, project_root)}")


def _resolve_choice(raw: str, candidates: list[Path], project_root: Path) -> Path | None:
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
        print(f"Invalid number: {idx}. Use 1–{len(candidates)}.")
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = (project_root / path).resolve()
    else:
        path = path.resolve()
    if path.is_file():
        return path
    print(f"File not found: {path}")
    return None


def prompt_file(
    role_label: str,
    candidates: list[Path],
    project_root: Path,
    *,
    title: str,
    disallow: Path | None = None,
    allow_skip: bool = False,
) -> Path | None:
    """Ask user to pick a file by number or path. Returns None if skipped."""
    print(f"\n--- Select {role_label} ---")
    _print_candidates(candidates, project_root, title=title)
    skip_hint = ", 's' to skip" if allow_skip else ""

    while True:
        try:
            raw = input(
                f"Enter number or path for {role_label} "
                f"(or 'q' to quit{skip_hint}): "
            )
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit("Cancelled.") from None

        token = raw.strip().lower()
        if token in ("q", "quit", "exit"):
            raise SystemExit("Cancelled.")
        if allow_skip and token in ("s", "skip"):
            print(f"  (skipped {role_label})")
            return None

        chosen = _resolve_choice(raw, candidates, project_root)
        if chosen is None:
            continue
        if disallow is not None and chosen.resolve() == disallow.resolve():
            print("Must differ from the previously selected file. Choose another.")
            continue
        return chosen


def resolve_path(
    path: Path | None,
    role: str,
    role_label: str,
    candidates: list[Path],
    project_root: Path,
    *,
    title: str,
    disallow: Path | None = None,
    interactive: bool,
    required: bool = True,
    allow_skip: bool = False,
) -> Path | None:
    if path is not None:
        resolved = path if path.is_absolute() else (project_root / path).resolve()
        if resolved.is_file():
            if disallow is not None and resolved.resolve() == disallow.resolve():
                raise SystemExit(f"--{role} must differ from the other file: {resolved}")
            return resolved
        if interactive:
            print(f"\n{role_label} not found: {resolved}")
            return prompt_file(
                role_label,
                candidates,
                project_root,
                title=title,
                disallow=disallow,
                allow_skip=allow_skip,
            )
        raise SystemExit(f"{role_label} not found: {resolved}")

    if interactive:
        chosen = prompt_file(
            role_label,
            candidates,
            project_root,
            title=title,
            disallow=disallow,
            allow_skip=allow_skip,
        )
        if chosen is None and required:
            raise SystemExit(f"{role_label} is required.")
        return chosen

    if required:
        raise SystemExit(f"Missing --{role}. Pass a path or run interactively.")
    return None
