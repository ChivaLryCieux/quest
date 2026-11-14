"""
策略大脑 - 核心策略控制器

负责:
1. 接收和处理K线数据 (5m + 15m + 1h 刻时模型)
2. 计算技术指标
3. 基于ADX/VWAP/MACD/ST/KDJ的趋势状态判断
4. 协调信号生成

数据结构（v0.4 重构）:
- CandleRing: numpy 环形列缓冲，O(1) 写入，替代 deque->DataFrame 全量重建
- StreamingFeatureEngine: 收盘蜡烛驱动的 O(1) 增量指标引擎，
  与 FeatureEngineer 批量实现数值等价（tests/test_streaming_equivalence.py）

喂入语义:
- ingest_candle: 权威收盘K线（预热/脚本/回测），每行按收盘处理
- push_forming: 成形中蜡烛 tick 更新；时间戳前进时自动收盘上一根
- commit_final: 收盘K线终值（WS x=true / TickAggregator），
  用真终值覆盖成形值并推进指标（引擎按 ts 去重，不会重复喂入）
"""

import logging

import numpy as np
import pandas as pd
from colorama import Fore

from core.strategy.base import BaseStrategy
from core.strategy.analyzers import SignalEngine
from core.analysis.ring import CandleRing
from core.analysis.streaming import StreamingFeatureEngine, StreamingSuperTrend
from core.analysis.regime import RegimeDetector

logger = logging.getLogger(__name__)


# ==========================================
# 策略大脑
# ==========================================
class StrategyBrain(BaseStrategy):
    HISTORY_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy']
    RING_CAPS = {'5m': 500, '15m': 200, '1h': 120, '1d': 100}

    def __init__(self, name: str = "ConsensusCTAStrategy"):
        super().__init__(name=name)
        self.signal_engine = SignalEngine()
        self.state = "⏳ 等待"
        self.color = Fore.WHITE

        # numpy 环形列缓冲（含成形中最后一根）
        self.rings = {tf: CandleRing(cap) for tf, cap in self.RING_CAPS.items()}

        # 5m 流式特征引擎（只吃收盘蜡烛）
        self.engine = StreamingFeatureEngine()
        self.supertrend_15m = StreamingSuperTrend(atr_period=10, multiplier=3.0)
        self.supertrend_1h = StreamingSuperTrend(atr_period=10, multiplier=3.0)

        # 已喂入指标的最后时间戳（去重）
        self._fed_ts = {'5m': None, '15m': None, '1h': None, '1d': None}

        # 缓存的分析快照
        self.cached_analysis_data = None

        # HMM 市场状态检测器（异步 fit，不阻塞主循环）
        self.regime_detector = RegimeDetector(n_states=4, lookback=100, retrain_interval=50)
        self.current_regime = -1
        self.regime_params = {}

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _tf_key(timeframe: str) -> str:
        return '5m' if timeframe in ('5m', '1m') else timeframe

    def _normalize_candle(self, item):
        """K线 -> float64[7] ndarray；6 字段补 taker_buy=volume*0.5。"""
        if item is None or len(item) < 6:
            return None
        arr = np.asarray(item, dtype=np.float64)
        if len(arr) == 6:
            arr = np.concatenate([arr, [arr[5] * 0.5]])
        return arr[:7]

    def _feed_commit(self, tf: str, row: np.ndarray) -> bool:
        """一根收盘蜡烛进入对应指标状态（按 ts 去重，防止 final/forming 双路径重复）。"""
        ts = float(row[0])
        last = self._fed_ts.get(tf)
        if last is not None and ts <= last:
            return False
        self._fed_ts[tf] = ts

        if tf == '5m':
            self.engine.update(row)
        elif tf == '15m':
            self.supertrend_15m.update(float(row[2]), float(row[3]), float(row[4]))
            self.signal_engine.update_15m_supertrend(self.supertrend_15m.direction)
        elif tf == '1h':
            self.supertrend_1h.update(float(row[2]), float(row[3]), float(row[4]))
            self.signal_engine.update_1h_supertrend(self.supertrend_1h.direction)
        return True

    # ------------------------------------------------------------------ 数据接入

    def ingest_candle(self, item, timeframe='5m', btc_change_pct=0.0, obi_value=0.0):
        """权威收盘K线喂入（预热/脚本/回测路径）。每行按已收盘处理。

        btc_change_pct / obi_value: 保留兼容参数（现由 analyze 阶段注入）。
        """
        row = self._normalize_candle(item)
        if row is None:
            return
        tf = self._tf_key(timeframe)
        res, closed = self.rings[tf].push(row)
        if res == 'committed' and closed is not None:
            self._feed_commit(tf, closed)
        self._feed_commit(tf, row)

    def push_forming(self, item, timeframe='5m') -> bool:
        """成形中蜡烛 tick 更新。

        同一时间戳 -> 覆盖最后一根成形值；时间戳前进 -> 上一根按
        最后的成形值收盘并喂入指标。返回是否发生了收盘。
        """
        row = self._normalize_candle(item)
        if row is None:
            return False
        tf = self._tf_key(timeframe)
        res, closed = self.rings[tf].push(row)
        if res == 'committed' and closed is not None:
            self._feed_commit(tf, closed)
            return True
        return False

    def commit_final(self, item, timeframe='5m') -> bool:
        """收盘K线终值（WS x=true / TickAggregator 弹出）。

        用真终值覆盖最后一根成形值；返回是否有新 bar 真正进入指标。
        """
        row = self._normalize_candle(item)
        if row is None:
            return False
        tf = self._tf_key(timeframe)
        res, closed = self.rings[tf].push(row)
        if res == 'stale':
            return False
        fed = False
        if res == 'committed' and closed is not None:
            fed |= self._feed_commit(tf, closed)
        fed |= self._feed_commit(tf, row)
        return fed

    def kline_list(self, timeframe='5m', n=None) -> list:
        """Web 推送用 K 线列表 [[ts,o,h,l,c,v], ...]。"""
        return self.rings[self._tf_key(timeframe)].to_ohlcv_list(n)

    @property
    def history_5m(self) -> pd.DataFrame:
        """兼容门面：少量遗留调用方仍期望 DataFrame。"""
        return pd.DataFrame(self.rings['5m'].array(), columns=self.HISTORY_COLUMNS)

    @property
    def history_15m(self) -> pd.DataFrame:
        return pd.DataFrame(self.rings['15m'].array(), columns=self.HISTORY_COLUMNS)

    @property
    def history_1h(self) -> pd.DataFrame:
        return pd.DataFrame(self.rings['1h'].array(), columns=self.HISTORY_COLUMNS)

    @property
    def history_1d(self) -> pd.DataFrame:
        return pd.DataFrame(self.rings['1d'].array(), columns=self.HISTORY_COLUMNS)

    # ------------------------------------------------------------------ 分析

    def analyze(self, orderbook=None):
        """
        分析市场状态 (基于技术指标)

        Returns:
            feature_data: 包含技术指标的字典（每次调用生成新快照）
        """
        last = self.rings['5m'].last_row
        curr_price = float(last[4]) if last is not None else 0.0

        _, feature_data = self.engine.context(curr_price=curr_price)
        if feature_data is None:
            return None

        # 盘口注入（无盘口输入时保留上一轮的值，不再覆写为 0）
        feature_data['orderbook'] = orderbook
        if orderbook is not None:
            obi, spread_pct = self.signal_engine.ob_analyzer.analyze(orderbook)
            feature_data['obi'] = obi
            feature_data['spread_pct'] = spread_pct

        # 根据ADX和VWAP判断市场状态
        adx = feature_data.get('adx', 0)
        plus_di = feature_data.get('plus_di', 0)
        minus_di = feature_data.get('minus_di', 0)

        if adx < 20:
            self.state = "🦀 震荡"
            self.color = Fore.YELLOW
        elif plus_di > minus_di:
            if adx > 30:
                self.state = "📈 强涨"
                self.color = Fore.GREEN
            else:
                self.state = "📈 小涨"
                self.color = Fore.LIGHTGREEN_EX
        else:
            if adx > 30:
                self.state = "📉 强跌"
                self.color = Fore.RED
            else:
                self.state = "📉 小跌"
                self.color = Fore.LIGHTRED_EX

        # HMM 市场状态检测 (异步 fit；update 本身只跑 O(30) predict)
        try:
            self.current_regime = self.regime_detector.update(
                self.engine.closes, self.engine.volumes)
            self.regime_params = self.regime_detector.get_strategy_params()
            regime_info = self.regime_detector.get_state_info()
            feature_data['regime'] = self.current_regime
            feature_data['regime_label'] = regime_info.get('label', '')
            feature_data['regime_confidence'] = regime_info.get('confidence', 0.0)
            feature_data['regime_params'] = self.regime_params
        except Exception as e:
            logger.debug(f"Regime detection error: {e}")

        self.cached_analysis_data = feature_data
        return feature_data

    def get_entry_signal(self, analysis_data, current_price):
        """获取入场信号"""
        return self.signal_engine.get_entry_signal(analysis_data, current_price)
