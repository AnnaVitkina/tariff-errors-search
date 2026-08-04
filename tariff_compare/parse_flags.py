from __future__ import annotations

from tariff_compare.models import Flag


def build_extraction_flags(
    old_count: int,
    new_count: int,
    old_path: str,
    new_path: str,
) -> list[Flag]:
    flags: list[Flag] = []
    if old_count == 0:
        flags.append(
            Flag(
                rule_id="EXTRACTION_EMPTY_OLD",
                severity="red_flag",
                lane_key="*",
                message="OLD extraction JSONL has no lines.",
                block="extraction",
                action_hint=f"Re-run Gem on {old_path}",
            )
        )
    if new_count == 0:
        flags.append(
            Flag(
                rule_id="EXTRACTION_EMPTY_NEW",
                severity="red_flag",
                lane_key="*",
                message="NEW extraction JSONL has no lines.",
                block="extraction",
                action_hint=f"Re-run Gem on {new_path}",
            )
        )
    if old_count and new_count:
        flags.append(
            Flag(
                rule_id="EXTRACTION_LOADED",
                severity="review",
                lane_key="*",
                message=f"Compared Gem extractions: {old_count} OLD lines, {new_count} NEW lines.",
                block="extraction",
                action_hint="See docs/PIPELINE.md",
            )
        )
    return flags
