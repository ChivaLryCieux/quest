"""K 线环形列缓冲 (CandleRing)

定长环形缓冲区，按列存储 OHLCV(+taker_buy) 数据：
- append / update_last / push 均为 O(1) 或 O(cap) 拷贝；
- push() 在蜡烛时间戳前进时自动将上一根标记为已收盘（committed），
  返回被收盘的行供指标引擎消费；
- to_ohlcv_list / column / array 提供零拷贝或小拷贝视图，替代
  原先"deque -> pd.DataFrame 全量重建"的 O(N) 开销。

行格式: [timestamp_ms, open, high, low, close, volume, taker_buy]
"""

from __future__ import annotations

import numpy as np

CANDLE_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "taker_buy")
_COL_IDX = {name: i for i, name in enumerate(CANDLE_COLUMNS)}


class CandleRing:
    __slots__ = ("capacity", "buf", "head", "size")

    def __init__(self, capacity: int = 500):
        self.capacity = capacity
        self.buf = np.full((capacity, len(CANDLE_COLUMNS)), np.nan)
        self.head = 0  # 下一个写入位置
        self.size = 0

    # ------------------------------------------------------------------ 写入

    def append(self, row) -> None:
        """追加一行（调用方保证时间戳单调递增）。"""
        self.buf[self.head] = row[: len(CANDLE_COLUMNS)]
        self.head = (self.head + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def update_last(self, row) -> None:
        """覆盖最后一根（成形中）蜡烛。"""
        if self.size == 0:
            self.append(row)
            return
        self.buf[(self.head - 1) % self.capacity] = row[: len(CANDLE_COLUMNS)]

    def push(self, row):
        """推入最新蜡烛快照。

        Returns:
            ('stale', None)      - 时间戳早于最后一根，忽略
            ('updated', None)    - 同一时间戳，覆盖成形中蜡烛
            ('appended', None)   - 新蜡烛，无上一根可收盘
            ('committed', closed_row) - 时间戳前进，上一根已收盘
        """
        ts = row[0]
        if self.size > 0:
            last_ts = self.buf[(self.head - 1) % self.capacity, 0]
            if ts < last_ts:
                return "stale", None
            if ts == last_ts:
                self.update_last(row)
                return "updated", None
            closed = self.buf[(self.head - 1) % self.capacity].copy()
            self.append(row)
            return "committed", closed
        self.append(row)
        return "appended", None

    # ------------------------------------------------------------------ 读取

    def array(self, n: int | None = None) -> np.ndarray:
        """按时间顺序返回 (m, 7) 数组。n 限制为最近 n 行。"""
        if self.size == 0:
            return np.empty((0, len(CANDLE_COLUMNS)))
        n = self.size if n is None else min(n, self.size)
        end = self.head if self.head > 0 else self.capacity
        start = end - n
        if start >= 0:
            return self.buf[start:end]
        wrapped = np.concatenate((self.buf[start:], self.buf[:end]))
        return wrapped[-n:]

    def column(self, name: str, n: int | None = None) -> np.ndarray:
        idx = _COL_IDX[name]
        return self.array(n)[:, idx]

    @property
    def last_ts(self) -> float | None:
        if self.size == 0:
            return None
        return float(self.buf[(self.head - 1) % self.capacity, 0])

    @property
    def last_row(self) -> np.ndarray | None:
        if self.size == 0:
            return None
        return self.buf[(self.head - 1) % self.capacity].copy()

    def to_ohlcv_list(self, n: int | None = None) -> list:
        """Web 推送格式 [[ts, o, h, l, c, v], ...]。"""
        arr = self.array(n)
        if len(arr) == 0:
            return []
        return arr[:, :6].tolist()

    def __len__(self) -> int:
        return self.size
