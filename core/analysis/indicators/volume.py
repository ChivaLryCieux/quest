import numpy as np
import pandas as pd


class VWAPCalculator:
    """VWAP指标 (Volume Weighted Average Price)

    用于确认交易方向：
    - 价格 > VWAP: 买方主导 → 偏向做多
    - 价格 < VWAP: 卖方主导 → 偏向做空

    使用滚动窗口VWAP (适配5分钟K线，288根=1天)
    """

    def __init__(self, period=288):
        self.period = period  # 滚动窗口 (288根5分钟K线 = 1天)

    def calculate(self, df):
        """
        计算VWAP
        Returns: dict with vwap, distance (百分比), upper_band, lower_band
        """
        close = df['close']
        volume = df['volume']
        high = df['high']
        low = df['low']

        # 典型价格 = (High + Low + Close) / 3
        typical_price = (high + low + close) / 3

        # 使用min_periods=1避免NaN
        win = min(self.period, len(df))
        tp_vol = typical_price * volume
        rolling_tp_vol = tp_vol.rolling(window=win, min_periods=1).sum()
        rolling_vol = volume.rolling(window=win, min_periods=1).sum()

        vwap = rolling_tp_vol / (rolling_vol + 1e-9)

        # VWAP标准差带
        tp_diff_sq = ((typical_price - vwap) ** 2) * volume
        rolling_var = tp_diff_sq.rolling(window=win, min_periods=1).sum() / (rolling_vol + 1e-9)
        vwap_std = np.sqrt(rolling_var.clip(lower=0))

        upper_band = vwap + 2 * vwap_std
        lower_band = vwap - 2 * vwap_std

        # 百分比距离: (close - vwap) / vwap * 100
        # 正值=价格在VWAP上方, 负值=价格在VWAP下方
        distance = ((close - vwap) / (vwap + 1e-9)) * 100
        distance = distance.fillna(0).clip(-5, 5)

        vwap_val = float(vwap.iloc[-1]) if len(vwap) > 0 else float(close.iloc[-1])
        dist_val = float(distance.iloc[-1]) if len(distance) > 0 else 0.0

        # NaN保护
        if np.isnan(vwap_val):
            vwap_val = float(close.iloc[-1])
        if np.isnan(dist_val):
            dist_val = 0.0

        return {
            'vwap': vwap_val,
            'distance': dist_val,
            'upper_band': float(upper_band.iloc[-1]) if len(upper_band) > 0 else 0.0,
            'lower_band': float(lower_band.iloc[-1]) if len(lower_band) > 0 else 0.0,
            'vwap_series': vwap,
            'distance_series': distance
        }

    def get_latest(self, df):
        """获取最新的VWAP值"""
        result = self.calculate(df)
        return result['vwap'], result['distance']


class OBVCalculator:
    """能量潮 (On Balance Volume)

    累积量: close>prev_close → +vol; close<prev_close → -vol
    用于检测量价背离。
    """

    def calculate(self, df):
        close = df['close']
        volume = df['volume']
        direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv = (volume * direction).cumsum()

        n = len(obv)
        obv_val = float(obv.iloc[-1]) if n > 0 else 0.0

        # OBV趋势: 用10周期线性回归斜率
        obv_trend = 0.0
        if n >= 10:
            y = obv.iloc[-10:].values
            x = np.arange(10, dtype=float)
            slope = np.polyfit(x, y, 1)[0]
            obv_trend = slope / (abs(obv_val) + 1e-9)

        # 量价背离: 价格新高但OBV未新高(看跌) / 价格新低但OBV未新低(看涨)
        bear_div = False
        bull_div = False
        if n >= 20:
            recent_close = close.iloc[-20:].values
            recent_obv = obv.iloc[-20:].values
            if recent_close[-1] >= np.max(recent_close) and recent_obv[-1] < np.max(recent_obv[:-1]):
                bear_div = True
            if recent_close[-1] <= np.min(recent_close) and recent_obv[-1] > np.min(recent_obv[:-1]):
                bull_div = True

        return {
            'obv': obv_val, 'obv_trend': obv_trend,
            'obv_bearish_div': bear_div, 'obv_bullish_div': bull_div,
        }


class VWMACalculator:
    """成交量加权移动平均 (VWMA)

    VWMA = SUM(close * volume, N) / SUM(volume, N)
    与SMA的区别在于考虑了成交量权重。
    """

    def __init__(self, period=20):
        self.period = period

    def calculate(self, df):
        cv = df['close'] * df['volume']
        vwma = cv.rolling(window=self.period).sum() / (df['volume'].rolling(window=self.period).sum() + 1e-9)
        sma = df['close'].rolling(window=self.period).mean()

        n = len(vwma)
        vwma_val = float(vwma.iloc[-1]) if n >= self.period else float(df['close'].iloc[-1])
        sma_val = float(sma.iloc[-1]) if n >= self.period else 0.0

        # VWMA > SMA → 买方主导 (正偏差)
        deviation = (vwma_val - sma_val) / (sma_val + 1e-9) * 100

        return {
            'vwma': vwma_val,
            'vwma_sma_deviation': deviation,
            'vwma_bullish': vwma_val > sma_val,
        }


class ChaikinMoneyFlow:
    """蔡金资金流量 (CMF)

    MF Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
    MF Volume = MF Multiplier * Volume
    CMF = SUM(MFV, 20) / SUM(Volume, 20)
    范围: [-1, 1]
    > 0 → 买方主导, < 0 → 卖方主导
    """

    def __init__(self, period=20):
        self.period = period

    def calculate(self, df):
        hl = df['high'] - df['low']
        mf_mult = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (hl + 1e-9)
        mf_vol = mf_mult * df['volume']
        cmf = mf_vol.rolling(window=self.period).sum() / (df['volume'].rolling(window=self.period).sum() + 1e-9)

        n = len(cmf)
        cmf_val = float(cmf.iloc[-1]) if n >= self.period else 0.0

        return {
            'cmf': cmf_val,
            'cmf_bullish': cmf_val > 0.05,
            'cmf_bearish': cmf_val < -0.05,
        }


class VolumeProfile:
    """成交量分布 (Volume Profile)

    将价格区间分为N个bin，统计每个价格区间的累计成交量。
    返回POC(最大成交量价格)、VAH(价值区高值)、VAL(价值区低值)。
    """

    def __init__(self, bins=50, value_area_pct=0.70):
        self.bins = bins
        self.va_pct = value_area_pct

    def calculate(self, df):
        if len(df) < 10:
            price = float(df['close'].iloc[-1]) if len(df) > 0 else 0.0
            return {'poc': price, 'vah': price, 'val': price}

        prices = df['close'].values
        volumes = df['volume'].values
        price_min, price_max = prices.min(), prices.max()

        if price_max == price_min:
            return {'poc': price_min, 'vah': price_min, 'val': price_min}

        bin_edges = np.linspace(price_min, price_max, self.bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        vol_profile = np.zeros(self.bins)

        for p, v in zip(prices, volumes):
            idx = int((p - price_min) / (price_max - price_min) * (self.bins - 1))
            idx = max(0, min(self.bins - 1, idx))
            vol_profile[idx] += v

        # POC = 最大成交量价格
        poc_idx = np.argmax(vol_profile)
        poc = float(bin_centers[poc_idx])

        # Value Area: 从POC向两侧扩展，直到包含 va_pct 的总成交量
        total_vol = vol_profile.sum()
        target_vol = total_vol * self.va_pct
        accumulated = vol_profile[poc_idx]
        lo_idx, hi_idx = poc_idx, poc_idx

        while accumulated < target_vol and (lo_idx > 0 or hi_idx < self.bins - 1):
            expand_lo = vol_profile[lo_idx - 1] if lo_idx > 0 else 0
            expand_hi = vol_profile[hi_idx + 1] if hi_idx < self.bins - 1 else 0
            if expand_lo >= expand_hi and lo_idx > 0:
                lo_idx -= 1
                accumulated += vol_profile[lo_idx]
            elif hi_idx < self.bins - 1:
                hi_idx += 1
                accumulated += vol_profile[hi_idx]
            else:
                lo_idx -= 1
                accumulated += vol_profile[lo_idx]

        return {
            'poc': poc,
            'vah': float(bin_centers[hi_idx]),
            'val': float(bin_centers[lo_idx]),
        }
