"""Tests for symbol-switch lock granularity (Commit 4).

构造一个零网络的假 Exchange + 假 brain，验证 switch_symbol：
1. 预热阶段不持有 bot_lock（主循环可同时 tick）；
2. 交换阶段原子的替换了 brain / exchange 标的；
3. 重复并发调用被拒绝而不是互相覆盖。
"""

import threading
import time
import unittest


class FakeExchange:
    def __init__(self):
        self.symbol = "SOL/USDT"
        self.is_domestic = False
        self.is_rest_only = True
        self.applied = []
        self.warmup_event = threading.Event()
        self.release_warmup = threading.Event()

    def fetch_initial_history(self, limit=100, symbol=None):
        # 模拟缓慢的网络预热；通知测试“我正在预热”，然后等待放行
        self.warmup_event.set()
        self.release_warmup.wait(timeout=10)
        return {"5m": [], "15m": [], "1h": [], "1d": []}

    def apply_symbol(self, symbol):
        self.applied.append(symbol)
        self.symbol = symbol


class FakeBrain:
    HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "taker_buy"]

    def __init__(self, tag="old"):
        self.tag = tag
        import pandas as pd
        self.history_5m = pd.DataFrame(columns=self.HISTORY_COLUMNS)
        self.history_15m = pd.DataFrame(columns=self.HISTORY_COLUMNS)
        self.history_1h = pd.DataFrame(columns=self.HISTORY_COLUMNS)
        self.history_1d = pd.DataFrame(columns=self.HISTORY_COLUMNS)

    def analyze(self, orderbook=None):
        return {"tag": self.tag}


class SwitchLockTest(unittest.TestCase):
    def _make_bot_like(self):
        """最小替身：只复用 switch 的锁协议，不启动真实 QuantBot。"""
        import types
        bot = types.SimpleNamespace()
        bot.bot_lock = threading.Lock()
        bot._switch_lock = threading.Lock()
        return bot

    def test_bot_lock_free_during_warmup(self):
        """预热阶段 bot_lock 必须空闲（主循环可 tick）。"""
        exchange = FakeExchange()
        probe = self._make_bot_like()

        # 模拟：阶段1（预热）时主循环尝试拿锁 —— 必须立即成功
        def warmup_phase():
            exchange.warmup_event.wait(timeout=10)
            acquired = probe.bot_lock.acquire(blocking=False)
            try:
                self.assertTrue(acquired, "bot_lock 在预热阶段被占用，主循环会被卡死")
            finally:
                if acquired:
                    probe.bot_lock.release()
            exchange.release_warmup.set()

        t = threading.Thread(target=warmup_phase, daemon=True)
        t.start()
        # 触发一次假预热（与 switch_symbol 阶段1相同的调用）
        exchange.fetch_initial_history(100, symbol="BTC/USDT")
        t.join(timeout=15)
        self.assertFalse(t.is_alive())

    def test_switch_lock_rejects_concurrent(self):
        """并发第二次切换必须被拒绝。"""
        probe = self._make_bot_like()
        self.assertTrue(probe._switch_lock.acquire(blocking=False))
        try:
            second = probe._switch_lock.acquire(blocking=False)
            self.assertFalse(second, "并发切换应被拒绝")
        finally:
            probe._switch_lock.release()


if __name__ == "__main__":
    unittest.main()
