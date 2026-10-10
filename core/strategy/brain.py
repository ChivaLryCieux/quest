"""
策略大脑 - 核心策略控制器

负责:
1. 接收和处理K线数据 (5m + 15m + 1h 刻时模型)
2. 计算技术指标
3. 基于ADX/VWAP/MACD/ST/KDJ的趋势状态判断
4. 协调信号生成
"""

from collections import deque
import pandas as pd
import logging
from colorama import Fore

from core.strategy.base import BaseStrategy
from core.strategy.analyzers import SignalEngine
from core.analysis.feature_engineering import FeatureEngineer
from core.analysis.indicators import SuperTrend
from core.analysis.regime import RegimeDetector

logger = logging.getLogger(__name__)


# ==========================================
# 策略大脑
# ==========================================
class StrategyBrain(BaseStrategy):
    HISTORY_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy']

    def __init__(self, name: str = "ConsensusCTAStrategy"):
        super().__init__(name=name)
        self.feature_engineer = FeatureEngineer()
        self.signal_engine = SignalEngine()
        self.state = "⏳ 等待"
        self.color = Fore.WHITE
        
        # 定长双端队列缓冲，消除 pd.concat 的内存拷贝与重分配
        self._buffer_5m = deque(maxlen=500)
        self._buffer_15m = deque(maxlen=200)
        self._buffer_1h = deque(maxlen=120)
        self._buffer_1d = deque(maxlen=100)

        # 5m K线历史数据 (用于信号生成与外部读取)
        self.history_5m = pd.DataFrame(columns=self.HISTORY_COLUMNS)
        self.history_15m = pd.DataFrame(columns=self.HISTORY_COLUMNS)
        self.history_1h = pd.DataFrame(columns=self.HISTORY_COLUMNS)
        self.history_1d = pd.DataFrame(columns=self.HISTORY_COLUMNS)
        
        # 缓存的分析数据
        self.cached_analysis_data = None
        
        # 15m / 1h SuperTrend计算器
        self.supertrend_15m = SuperTrend(atr_period=10, multiplier=3.0)
        self.supertrend_1h = SuperTrend(atr_period=10, multiplier=3.0)

        # HMM 市场状态检测器
        self.regime_detector = RegimeDetector(n_states=4, lookback=100, retrain_interval=50)
        self.current_regime = -1
        self.regime_params = {}

    def ingest_candle(self, item, timeframe='5m', btc_change_pct=0.0, obi_value=0.0):
        """
        接收K线数据并计算特征
        
        Args:
            item: K线数据 [timestamp, open, high, low, close, volume, taker_buy?]
            timeframe: '5m' 或 '15m' 或 '1h' 或 '1m'
            btc_change_pct: BTC变化百分比 (保留兼容)
            obi_value: 订单簿失衡值 (保留兼容)
        """
        normalized = self._normalize_candle(item)
        
        if timeframe in ['5m', '1m']:
            self._buffer_5m.append(normalized)
            self.history_5m = pd.DataFrame(list(self._buffer_5m), columns=self.HISTORY_COLUMNS)
            
            # 计算5m特征
            if len(self.history_5m) >= 100:
                _, context = self.feature_engineer.calculate_features(
                    self.history_5m, normalized[4], btc_change_pct, obi_value
                )
                self.cached_analysis_data = context
        
        elif timeframe == '15m':
            self._buffer_15m.append(normalized)
            self.history_15m = pd.DataFrame(list(self._buffer_15m), columns=self.HISTORY_COLUMNS)
            
            # 计算15m SuperTrend
            if len(self.history_15m) >= 30:
                st_result = self.supertrend_15m.calculate(self.history_15m)
                self.signal_engine.update_15m_supertrend(st_result['direction'])

        elif timeframe == '1h':
            self._buffer_1h.append(normalized)
            self.history_1h = pd.DataFrame(list(self._buffer_1h), columns=self.HISTORY_COLUMNS)

            if len(self.history_1h) >= 30:
                st_result = self.supertrend_1h.calculate(self.history_1h)
                self.signal_engine.update_1h_supertrend(st_result['direction'])

        elif timeframe == '1d':
            self._buffer_1d.append(normalized)
            self.history_1d = pd.DataFrame(list(self._buffer_1d), columns=self.HISTORY_COLUMNS)

    def _normalize_candle(self, item):
        """将K线数据标准化为7字段。"""
        if len(item) == 6:
            return list(item) + [item[5] * 0.5]
        return list(item)

    @staticmethod
    def _append_history(history_df, new_row, max_length):
        if history_df.empty:
            return new_row
        return pd.concat([history_df, new_row]).iloc[-max_length:]

    def analyze(self, orderbook=None):
        """
        分析市场状态 (基于技术指标)
        
        Returns:
            feature_data: 包含技术指标的字典
        """
        feature_data = self.cached_analysis_data
        if not feature_data:
            return None

        feature_data['orderbook'] = orderbook
        obi, spread_pct = self.signal_engine.ob_analyzer.analyze(orderbook)
        feature_data['obi'] = obi
        feature_data['spread_pct'] = spread_pct

        # 根据ADX和VWAP判断市场状态
        adx = feature_data.get('adx', 0)
        vwap_dist = feature_data.get('vwap_distance', 0)
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

        # HMM 市场状态检测 (异步更新，不影响主逻辑)
        try:
            self.current_regime = self.regime_detector.update(self.history_5m)
            self.regime_params = self.regime_detector.get_strategy_params()
            regime_info = self.regime_detector.get_state_info()
            feature_data['regime'] = self.current_regime
            feature_data['regime_label'] = regime_info.get('label', '')
            feature_data['regime_confidence'] = regime_info.get('confidence', 0.0)
            feature_data['regime_params'] = self.regime_params
        except Exception as e:
            logger.debug(f"Regime detection error: {e}")

        return feature_data

    def get_entry_signal(self, analysis_data, current_price):
        """获取入场信号"""
        return self.signal_engine.get_entry_signal(analysis_data, current_price)
