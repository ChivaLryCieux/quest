import numpy as np
import pandas as pd
from .utils import MathUtils


class MomentumCalculator:
    def __init__(self, periods=[1, 5, 15, 30, 50, 96]):
        self.periods = periods
        self.history = []
        self.max_len = max(periods) + 5

    def update(self, price):
        """Update with new price and return momentum array."""
        self.history.append(price)
        if len(self.history) > self.max_len:
            self.history.pop(0)
        return np.array(
            [np.log(self.history[-1] / self.history[-(p + 1)]) if len(self.history) > p else 0.0
             for p in self.periods])

    def get_momentum(self, prices, T):
        """Calculate momentum for a specific period T."""
        if len(prices) <= T:
            return None
        momentum = prices[-1] / prices[-(T + 1)]
        return np.log(momentum)

    def calculate_all_momentums(self, prices):
        """Calculate all momentum periods and return as dict."""
        results = {}
        for T in self.periods:
            results[f"T_{T}"] = self.get_momentum(prices, T)
        return results


class MACDCalculator:
    """MACD指标 - 支持Appel黄金规则"""

    def __init__(self, fast=12, slow=26, signal=9):
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def calculate(self, df):
        """
        计算MACD + Appel黄金规则信号

        Returns dict:
            macd/signal/histogram/normalized: 基础值
            golden_cross: 金叉 (MACD上穿信号线)
            death_cross: 死叉 (MACD下穿信号线)
            above_zero: MACD在零线上方
            hist_turning_up: 直方图从谷底回升 (连续2根下降后回升)
            hist_turning_down: 直方图从峰值回落 (连续2根上升后回落)
            bullish_divergence: 看涨背离 (价格新低但直方图未新低)
            bearish_divergence: 看跌背离 (价格新高但直方图未新高)
        """
        close = df['close']

        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()

        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=self.signal, adjust=False).mean()
        histogram = macd - signal_line

        # 归一化: MACD / Close
        normalized = macd / close.replace(0, np.nan)
        normalized = normalized.fillna(0)

        n = len(macd)

        # === 信号线交叉 (金叉/死叉) ===
        golden_cross = False
        death_cross = False
        if n >= 2:
            prev_diff = float(macd.iloc[-2] - signal_line.iloc[-2])
            curr_diff = float(macd.iloc[-1] - signal_line.iloc[-1])
            golden_cross = (prev_diff <= 0 and curr_diff > 0)
            death_cross = (prev_diff >= 0 and curr_diff < 0)

        # === 零线位置 ===
        above_zero = float(macd.iloc[-1]) > 0 if n > 0 else False

        # === 直方图转折 ===
        hist_turning_up = False
        hist_turning_down = False
        if n >= 3:
            h1 = float(histogram.iloc[-3])
            h2 = float(histogram.iloc[-2])
            h3 = float(histogram.iloc[-1])
            # 转折向上: 前两根下降(h1>h2)，当前回升(h3>h2)
            hist_turning_up = (h1 > h2 and h3 > h2)
            # 转折向下: 前两根上升(h1<h2)，当前回落(h3<h2)
            hist_turning_down = (h1 < h2 and h3 < h2)

        # === 背离检测 (近20根K线) ===
        bullish_divergence = False
        bearish_divergence = False
        lookback = min(20, n - 1)
        if lookback >= 5:
            recent_close = close.iloc[-lookback:].values
            recent_hist = histogram.iloc[-lookback:].values

            # 看涨背离: 价格创近期新低，但直方图未创新低
            price_at_new_low = recent_close[-1] <= np.min(recent_close)
            hist_not_new_low = recent_hist[-1] > np.min(recent_hist[:-1])
            bullish_divergence = (price_at_new_low and hist_not_new_low)

            # 看跌背离: 价格创近期新高，但直方图未创新高
            price_at_new_high = recent_close[-1] >= np.max(recent_close)
            hist_not_new_high = recent_hist[-1] < np.max(recent_hist[:-1])
            bearish_divergence = (price_at_new_high and hist_not_new_high)

        return {
            'macd': float(macd.iloc[-1]) if n > 0 else 0.0,
            'signal': float(signal_line.iloc[-1]) if n > 0 else 0.0,
            'histogram': float(histogram.iloc[-1]) if n > 0 else 0.0,
            'normalized': float(normalized.iloc[-1]) if n > 0 else 0.0,
            'macd_series': macd,
            'signal_series': signal_line,
            # Appel 黄金规则信号
            'golden_cross': golden_cross,
            'death_cross': death_cross,
            'above_zero': above_zero,
            'hist_turning_up': hist_turning_up,
            'hist_turning_down': hist_turning_down,
            'bullish_divergence': bullish_divergence,
            'bearish_divergence': bearish_divergence,
        }

    def get_latest(self, df):
        """获取最新的MACD值"""
        result = self.calculate(df)
        return result['macd'], result['signal'], result['histogram'], result['normalized']


class KDJCalculator:
    """KDJ指标 (9, 3, 3)"""

    def __init__(self, k_period=9, d_period=3, j_smooth=3):
        self.k_period = k_period
        self.d_period = d_period
        self.j_smooth = j_smooth

    def calculate(self, df):
        """
        计算KDJ
        Returns: (k, d, j, k_minus_d, golden_cross, death_cross)
            k: K值
            d: D值
            j: J值
            k_minus_d: K-D差值
            golden_cross: 是否金叉 (K上穿D)
            death_cross: 是否死叉 (K下穿D)
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # 计算RSV (Raw Stochastic Value)
        lowest_low = low.rolling(window=self.k_period).min()
        highest_high = high.rolling(window=self.k_period).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-9) * 100

        # 计算K值 (RSV的EMA)
        k = rsv.ewm(com=self.d_period - 1, adjust=False).mean()

        # 计算D值 (K的EMA)
        d = k.ewm(com=self.j_smooth - 1, adjust=False).mean()

        # 计算J值
        j = 3 * k - 2 * d

        # K-D差值
        k_minus_d = k - d

        # 金叉/死叉判断
        golden_cross = False
        death_cross = False
        if len(k) >= 2 and len(d) >= 2:
            # 金叉: K从下往上穿过D
            if k.iloc[-2] < d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
                golden_cross = True
            # 死叉: K从上往下穿过D
            if k.iloc[-2] > d.iloc[-2] and k.iloc[-1] < d.iloc[-1]:
                death_cross = True

        return {
            'k': k.iloc[-1] if len(k) > 0 else 50.0,
            'd': d.iloc[-1] if len(d) > 0 else 50.0,
            'j': j.iloc[-1] if len(j) > 0 else 50.0,
            'k_minus_d': k_minus_d.iloc[-1] if len(k_minus_d) > 0 else 0.0,
            'golden_cross': golden_cross,
            'death_cross': death_cross,
            'k_series': k,
            'd_series': d
        }

    def get_latest(self, df):
        """获取最新的KDJ值"""
        result = self.calculate(df)
        return result['k'], result['d'], result['j'], result['k_minus_d'], result['golden_cross'], result['death_cross']


class StochasticRSI:
    """随机RSI (Stochastic RSI)

    对 RSI 应用随机指标公式，比原始 RSI 更敏感。
    周期: RSI(14) → Stoch(14,14) → K(3) → D(3)
    """

    def __init__(self, rsi_period=14, stoch_period=14, k_smooth=3, d_smooth=3):
        self.rsi_p = rsi_period
        self.stoch_p = stoch_period
        self.k_smooth = k_smooth
        self.d_smooth = d_smooth

    def calculate(self, df):
        close = df['close']
        rsi = MathUtils.calc_rsi(close, self.rsi_p)

        rsi_min = rsi.rolling(window=self.stoch_p).min()
        rsi_max = rsi.rolling(window=self.stoch_p).max()
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min + 1e-9) * 100

        k = stoch_rsi.ewm(com=self.k_smooth - 1, adjust=False).mean()
        d = k.ewm(com=self.d_smooth - 1, adjust=False).mean()

        n = len(k)
        k_val = float(k.iloc[-1]) if n > 0 else 50.0
        d_val = float(d.iloc[-1]) if n > 0 else 50.0

        golden = False
        death = False
        if n >= 2:
            if k.iloc[-2] < d.iloc[-2] and k.iloc[-1] > d.iloc[-1]:
                golden = True
            if k.iloc[-2] > d.iloc[-2] and k.iloc[-1] < d.iloc[-1]:
                death = True

        return {
            'stoch_rsi_k': k_val, 'stoch_rsi_d': d_val,
            'stoch_rsi_golden': golden, 'stoch_rsi_death': death,
        }


class CCICalculator:
    """商品通道指数 (CCI)

    CCI = (TP - SMA(TP)) / (0.015 * MeanDeviation)
    TP = (H+L+C) / 3
    超买 > +100, 超卖 < -100
    """

    def __init__(self, period=20):
        self.period = period

    def calculate(self, df):
        tp = (df['high'] + df['low'] + df['close']) / 3
        sma = tp.rolling(window=self.period).mean()
        mad = tp.rolling(window=self.period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        cci = (tp - sma) / (0.015 * mad + 1e-9)

        n = len(cci)
        cci_val = float(cci.iloc[-1]) if n >= self.period else 0.0
        cci_prev = float(cci.iloc[-2]) if n >= self.period + 1 else 0.0

        return {
            'cci': cci_val,
            'cci_prev': cci_prev,
            'cci_overbought': cci_val > 100,
            'cci_oversold': cci_val < -100,
        }


class WilliamsPercentR:
    """威廉指标 (Williams %R)

    %R = (HH - Close) / (HH - LL) * -100
    范围: -100 (最低) 到 0 (最高)
    超买: > -20, 超卖: < -80
    """

    def __init__(self, period=14):
        self.period = period

    def calculate(self, df):
        hh = df['high'].rolling(window=self.period).max()
        ll = df['low'].rolling(window=self.period).min()
        wr = (hh - df['close']) / (hh - ll + 1e-9) * -100

        n = len(wr)
        wr_val = float(wr.iloc[-1]) if n >= self.period else -50.0

        return {
            'williams_r': wr_val,
            'wr_overbought': wr_val > -20,
            'wr_oversold': wr_val < -80,
        }
