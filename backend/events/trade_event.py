"""Immutable orchestration envelope; the pure matcher continues to return Fill."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from backend.matching.order_book import Fill

BIGINT_MAX = 2**63 - 1


@dataclass(frozen=True, slots=True)
class TradeEvent:
    event_id: int
    instrument_id: int
    buy_order_id: int
    sell_order_id: int
    buy_trader_id: UUID
    sell_trader_id: UUID
    price_ticks: int
    quantity: int
    taker_order_id: int
    occurred_at: datetime

    def __post_init__(self) -> None:
        for name in ("event_id", "instrument_id", "buy_order_id", "sell_order_id",
                     "price_ticks", "quantity", "taker_order_id"):
            value = getattr(self, name)
            maximum = 2**31 - 1 if name == "instrument_id" else BIGINT_MAX
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError(f"{name} must be a positive database-range integer")
        if self.buy_order_id == self.sell_order_id:
            raise ValueError("Buy and sell order IDs must differ")
        if self.taker_order_id not in (self.buy_order_id, self.sell_order_id):
            raise ValueError("Taker must be one of the fill orders")
        if not isinstance(self.buy_trader_id, UUID) or not isinstance(self.sell_trader_id, UUID):
            raise ValueError("Trader IDs must be UUID objects")
        if self.buy_trader_id == self.sell_trader_id:
            raise ValueError("Self-trade events are forbidden")
        if (not isinstance(self.occurred_at, datetime)
                or self.occurred_at.tzinfo is None
                or self.occurred_at.utcoffset() is None):
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(timezone.utc))

    @classmethod
    def from_fill(cls, fill: Fill, *, event_id: int, taker_order_id: int,
                  occurred_at: datetime) -> TradeEvent:
        """IDs/time come from orchestration, never from order-book I/O."""
        return cls(
            event_id=event_id, instrument_id=fill.instrument_id,
            buy_order_id=fill.buy_order_id, sell_order_id=fill.sell_order_id,
            buy_trader_id=UUID(fill.buy_trader_id), sell_trader_id=UUID(fill.sell_trader_id),
            price_ticks=fill.price_ticks, quantity=fill.quantity,
            taker_order_id=taker_order_id, occurred_at=occurred_at,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["buy_trader_id"] = str(self.buy_trader_id)
        payload["sell_trader_id"] = str(self.sell_trader_id)
        payload["occurred_at"] = self.occurred_at.isoformat().replace("+00:00", "Z")
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TradeEvent:
        if not isinstance(payload, Mapping) or set(payload) != {f.name for f in fields(cls)}:
            raise ValueError("TradeEvent requires exactly the documented fields")
        values = dict(payload)
        for name in ("buy_trader_id", "sell_trader_id"):
            if not isinstance(values[name], str):
                raise ValueError(f"{name} must be a UUID string")
            values[name] = UUID(values[name])
        if not isinstance(values["occurred_at"], str):
            raise ValueError("occurred_at must be an ISO-8601 string")
        values["occurred_at"] = datetime.fromisoformat(values["occurred_at"])
        return cls(**values)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload: str) -> TradeEvent:
        return cls.from_dict(json.loads(payload))
