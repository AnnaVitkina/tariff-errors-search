from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class SourceRef:
    sheet: str
    row: int
    col: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RateRecord:
    """One comparable rate line."""

    lane_key: str
    record_type: str
    block: str
    sheet: str
    amount: Optional[float] = None
    billing_basis: Optional[str] = None
    currency: Optional[str] = None
    text_value: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)
    source: Optional[SourceRef] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "lane_key": self.lane_key,
            "record_type": self.record_type,
            "block": self.block,
            "sheet": self.sheet,
            "amount": self.amount,
            "billing_basis": self.billing_basis,
            "currency": self.currency,
            "text_value": self.text_value,
            "meta": self.meta,
        }
        if self.source:
            d["source"] = self.source.to_dict()
        return d


@dataclass
class Flag:
    rule_id: str
    severity: str
    lane_key: str
    message: str
    old_value: Any = None
    new_value: Any = None
    block: str = ""
    sheet: str = ""
    where_to_look_old: str = ""
    where_to_look_new: str = ""
    action_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
