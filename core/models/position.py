"""统一持仓模型。

替代 TradeExecutor / RiskManager / WebState 之间传递的裸 dict，
字段缺失时不再静默 .get() 兜底，而是由构造器保证完整。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Position:
    size: float = 0.0
    entry_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    entry_time: int = 0
    leverage: float = 10.0
    cluster: int = 99
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_flat(self) -> bool:
        return self.size == 0

    @property
    def direction(self) -> int:
        if self.size > 0:
            return 1
        if self.size < 0:
            return -1
        return 0

    @property
    def is_long(self) -> bool:
        return self.size > 0

    def raw_pnl_pct(self, price: float) -> float:
        """相对入场价的原始涨跌幅（带方向），空仓返回 0。"""
        if self.is_flat or self.entry_price <= 0:
            return 0.0
        return (price - self.entry_price) / self.entry_price * self.direction

    def unrealized_pnl(self, price: float) -> float:
        if self.is_flat:
            return 0.0
        return (price - self.entry_price) * self.size

    def margin_used(self, default_leverage: float = 10.0) -> float:
        leverage = self.leverage or default_leverage
        if leverage <= 0:
            return 0.0
        return abs(self.size) * self.entry_price / leverage

    def flatten(self) -> "Position":
        """返回空仓，保留杠杆档位。"""
        return Position(leverage=self.leverage or 10.0)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "size": self.size,
            "entry_price": self.entry_price,
            "sl": self.sl,
            "tp": self.tp,
            "entry_time": self.entry_time,
            "leverage": self.leverage,
            "cluster": self.cluster,
        }
        data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Position":
        data = data or {}
        known = {"size", "entry_price", "sl", "tp", "entry_time", "leverage", "cluster"}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            size=float(data.get("size", 0.0)),
            entry_price=float(data.get("entry_price", 0.0)),
            sl=float(data.get("sl", 0.0)),
            tp=float(data.get("tp", 0.0)),
            entry_time=int(data.get("entry_time", 0) or 0),
            leverage=float(data.get("leverage", 10.0) or 10.0),
            cluster=int(data.get("cluster", 99)),
            extra=extra,
        )

    def to_web_dict(self, price: float = 0.0) -> dict[str, Any]:
        """WebState.update_position 需要的快照。"""
        return {
            "size": self.size,
            "entry_price": self.entry_price,
            "sl": self.sl,
            "tp": self.tp,
            "entry_time": self.entry_time,
            "leverage": self.leverage,
            "unrealized_pnl": self.unrealized_pnl(price),
        }
