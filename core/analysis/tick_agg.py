"""Tick -> Candle 聚合器 (TickAggregator)

REST 轮询 / 国内行情源只有秒级 tick，没有交易所推送的成形中 K 线。
本聚合器把 tick 累积为真实 OHLCV 蜡烛，替代原先
"OHLC 全部填同一个价、volume 填日累计量" 的假蜡烛。

- update(ts, price, vol_delta) -> 当前成形蜡烛 [ts,o,h,l,c,v,tb]
- pop_closed() -> 时间桶切换时收盘的上一根蜡烛（只取一次）
"""

from __future__ import annotations


class TickAggregator:
    __slots__ = ("tf_ms", "candle", "_closed")

    def __init__(self, tf_seconds: int):
        self.tf_ms = tf_seconds * 1000
        self.candle: list | None = None
        self._closed: list | None = None

    def update(self, ts_ms: float, price: float, volume: float = 0.0,
               taker_volume: float | None = None) -> list:
        bucket = int(ts_ms // self.tf_ms) * self.tf_ms
        tb = volume * 0.5 if taker_volume is None else taker_volume

        if self.candle is None or bucket > self.candle[0]:
            if self.candle is not None:
                self._closed = self.candle
            self.candle = [bucket, price, price, price, price, volume, tb]
        elif bucket == self.candle[0]:
            c = self.candle
            if price > c[2]:
                c[2] = price
            if price < c[3]:
                c[3] = price
            c[4] = price
            c[5] += volume
            c[6] += tb
        # bucket < candle[0] -> 迟到 tick，忽略
        return list(self.candle)

    def pop_closed(self) -> list | None:
        c = self._closed
        self._closed = None
        return c
