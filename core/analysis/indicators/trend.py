import numpy as np
import pandas as pd
from .utils import MathUtils


class SuperTrend:
    """SuperTrend指标 (ATR周期10, 乘数3)"""

    def __init__(self, atr_period=10, multiplier=3.0):
        self.atr_period = atr_period
        self.multiplier = multiplier

    def calculate(self, df):
        """
        计算SuperTrend
        Returns: (value, direction)
            value: SuperTrend值
            direction: 1=绿(多), -1=红(空)
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # 计算ATR
        atr = MathUtils.calc_atr(df, self.atr_period)

        # 计算基础上下轨
        hl2 = (high + low) / 2
        upper_basic = hl2 + self.multiplier * atr
        lower_basic = hl2 - self.multiplier * atr

        # 初始化SuperTrend
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)

        # 第一个值
        supertrend.iloc[0] = upper_basic.iloc[0]
        direction.iloc[0] = -1

        # 递归计算
        for i in range(1, len(df)):
            # 更新上轨
            if lower_basic.iloc[i] > supertrend.iloc[i-1] or close.iloc[i-1] < supertrend.iloc[i-1]:
                upper = upper_basic.iloc[i]
            else:
                upper = min(upper_basic.iloc[i], supertrend.iloc[i-1])

            # 更新下轨
            if upper_basic.iloc[i] < supertrend.iloc[i-1] or close.iloc[i-1] > supertrend.iloc[i-1]:
                lower = lower_basic.iloc[i]
            else:
                lower = max(lower_basic.iloc[i], supertrend.iloc[i-1])

            # 判断方向和SuperTrend值
            if close.iloc[i] > supertrend.iloc[i-1]:
                supertrend.iloc[i] = lower
                direction.iloc[i] = 1  # 绿色(多)
            else:
                supertrend.iloc[i] = upper
                direction.iloc[i] = -1  # 红色(空)

        return {
            'value': supertrend.iloc[-1] if len(supertrend) > 0 else 0.0,
            'direction': direction.iloc[-1] if len(direction) > 0 else 0,
            'value_series': supertrend,
            'direction_series': direction
        }

    def get_latest(self, df):
        """获取最新的SuperTrend值和方向"""
        result = self.calculate(df)
        return result['value'], result['direction']


class ADXCalculator:
    """ADX指标 (Average Directional Index)

    用于判断趋势强度：
    - ADX > 25: 强趋势 → 适合趋势跟随
    - ADX 20-25: 弱趋势 → 谨慎交易
    - ADX < 20: 无趋势/震荡 → 禁止开仓
    """

    def __init__(self, period=14):
        self.period = period

    def calculate(self, df):
        """
        计算ADX (使用标准Wilder平滑)
        Returns: dict with adx, plus_di, minus_di, adx_rising
        """
        if len(df) < self.period * 2:
            return {
                'adx': 0.0, 'plus_di': 0.0, 'minus_di': 0.0,
                'adx_rising': False, 'adx_series': pd.Series(dtype=float),
                'plus_di_series': pd.Series(dtype=float),
                'minus_di_series': pd.Series(dtype=float)
            }

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        n = len(df)
        period = self.period

        # 计算 True Range, +DM, -DM
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)

        for i in range(1, n):
            h_diff = high[i] - high[i-1]
            l_diff = low[i-1] - low[i]

            tr[i] = max(high[i] - low[i],
                        abs(high[i] - close[i-1]),
                        abs(low[i] - close[i-1]))

            if h_diff > l_diff and h_diff > 0:
                plus_dm[i] = h_diff
            if l_diff > h_diff and l_diff > 0:
                minus_dm[i] = l_diff

        # Wilder平滑 (初始值用简单求和，之后递推)
        atr_smooth = np.zeros(n)
        plus_dm_smooth = np.zeros(n)
        minus_dm_smooth = np.zeros(n)

        # 初始值: 前period个的简单求和
        atr_smooth[period] = np.sum(tr[1:period+1])
        plus_dm_smooth[period] = np.sum(plus_dm[1:period+1])
        minus_dm_smooth[period] = np.sum(minus_dm[1:period+1])

        # Wilder递推
        for i in range(period + 1, n):
            atr_smooth[i] = atr_smooth[i-1] - atr_smooth[i-1] / period + tr[i]
            plus_dm_smooth[i] = plus_dm_smooth[i-1] - plus_dm_smooth[i-1] / period + plus_dm[i]
            minus_dm_smooth[i] = minus_dm_smooth[i-1] - minus_dm_smooth[i-1] / period + minus_dm[i]

        # +DI, -DI
        plus_di_arr = np.zeros(n)
        minus_di_arr = np.zeros(n)
        dx_arr = np.zeros(n)

        for i in range(period, n):
            if atr_smooth[i] > 0:
                plus_di_arr[i] = 100 * plus_dm_smooth[i] / atr_smooth[i]
                minus_di_arr[i] = 100 * minus_dm_smooth[i] / atr_smooth[i]

            di_sum = plus_di_arr[i] + minus_di_arr[i]
            if di_sum > 0:
                dx_arr[i] = 100 * abs(plus_di_arr[i] - minus_di_arr[i]) / di_sum

        # ADX: DX的Wilder平滑
        adx_arr = np.zeros(n)
        start = period * 2
        if start < n:
            adx_arr[start] = np.mean(dx_arr[period:start+1])
            for i in range(start + 1, n):
                adx_arr[i] = (adx_arr[i-1] * (period - 1) + dx_arr[i]) / period

        # 转为Series
        idx = df.index
        adx_series = pd.Series(adx_arr, index=idx)
        plus_di_series = pd.Series(plus_di_arr, index=idx)
        minus_di_series = pd.Series(minus_di_arr, index=idx)

        adx_val = float(adx_arr[-1])
        adx_rising = adx_arr[-1] > adx_arr[-3] if n >= 3 else False

        return {
            'adx': adx_val,
            'plus_di': float(plus_di_arr[-1]),
            'minus_di': float(minus_di_arr[-1]),
            'adx_rising': bool(adx_rising),
            'adx_series': adx_series,
            'plus_di_series': plus_di_series,
            'minus_di_series': minus_di_series
        }

    def get_latest(self, df):
        """获取最新ADX值"""
        result = self.calculate(df)
        return result['adx'], result['plus_di'], result['minus_di'], result['adx_rising']


class IchimokuCloud:
    """一目均衡图 (Ichimoku Kinko Hyo)

    五线系统:
      - Tenkan-sen (转换线): 9周期 (high+low)/2
      - Kijun-sen (基准线): 26周期
      - Senkou Span A (先行A): (Tenkan+Kijun)/2 前移26
      - Senkou Span B (先行B): 52周期 前移26
      - Chikou Span (延迟线): close 后移26

    返回最新值 + 多空信号。
    """

    def __init__(self, tenkan=9, kijun=26, senkou_b=52, displacement=26):
        self.tenkan_p = tenkan
        self.kijun_p = kijun
        self.senkou_b_p = senkou_b
        self.disp = displacement

    @staticmethod
    def _mid_channel(high, low, period):
        hh = high.rolling(window=period).max()
        ll = low.rolling(window=period).min()
        return (hh + ll) / 2

    def calculate(self, df):
        high, low, close = df['high'], df['low'], df['close']

        tenkan = self._mid_channel(high, low, self.tenkan_p)
        kijun = self._mid_channel(high, low, self.kijun_p)
        span_a = ((tenkan + kijun) / 2).shift(self.disp)
        span_b = self._mid_channel(high, low, self.senkou_b_p).shift(self.disp)
        chikou = close.shift(-self.disp)

        n = len(close)
        tk = float(tenkan.iloc[-1]) if n >= self.tenkan_p else 0.0
        kj = float(kijun.iloc[-1]) if n >= self.kijun_p else 0.0
        sa = float(span_a.iloc[-1]) if n >= self.tenkan_p + self.disp else 0.0
        sb = float(span_b.iloc[-1]) if n >= self.senkou_b_p + self.disp else 0.0
        ck = float(chikou.iloc[-1]) if n > self.disp else 0.0
        price = float(close.iloc[-1])

        # 信号: 价格相对于云的位置
        cloud_top = max(sa, sb)
        cloud_bottom = min(sa, sb)
        if price > cloud_top:
            cloud_signal = 1  # 多
        elif price < cloud_bottom:
            cloud_signal = -1  # 空
        else:
            cloud_signal = 0  # 云中

        # TK交叉
        tk_cross = 0
        if n >= 2:
            prev_diff = float(tenkan.iloc[-2] - kijun.iloc[-2])
            curr_diff = float(tenkan.iloc[-1] - kijun.iloc[-1])
            if prev_diff <= 0 < curr_diff:
                tk_cross = 1  # 金叉
            elif prev_diff >= 0 > curr_diff:
                tk_cross = -1  # 死叉

        return {
            'tenkan': tk, 'kijun': kj,
            'span_a': sa, 'span_b': sb,
            'chikou': ck,
            'cloud_top': cloud_top, 'cloud_bottom': cloud_bottom,
            'cloud_signal': cloud_signal,
            'tk_cross': tk_cross,
        }


class ParabolicSAR:
    """抛物线转向指标 (Parabolic SAR)

    趋势跟随止损系统。
    AF=0.02, step=0.02, max=0.2
    """

    def __init__(self, af_start=0.02, af_step=0.02, af_max=0.2):
        self.af_start = af_start
        self.af_step = af_step
        self.af_max = af_max

    def calculate(self, df):
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        n = len(df)

        if n < 2:
            return {'sar': close[-1] if n > 0 else 0.0, 'sar_direction': 0}

        sar = np.zeros(n)
        direction = np.zeros(n, dtype=int)  # 1=多, -1=空
        af = self.af_start
        ep = high[0]
        is_long = True

        sar[0] = low[0]
        direction[0] = 1

        for i in range(1, n):
            if is_long:
                sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
                sar[i] = min(sar[i], low[i - 1])
                if i >= 2:
                    sar[i] = min(sar[i], low[i - 2])

                if low[i] < sar[i]:
                    is_long = False
                    sar[i] = ep
                    ep = low[i]
                    af = self.af_start
                else:
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af + self.af_step, self.af_max)
            else:
                sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
                sar[i] = max(sar[i], high[i - 1])
                if i >= 2:
                    sar[i] = max(sar[i], high[i - 2])

                if high[i] > sar[i]:
                    is_long = True
                    sar[i] = ep
                    ep = high[i]
                    af = self.af_start
                else:
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af + self.af_step, self.af_max)

            direction[i] = 1 if is_long else -1

        return {
            'sar': float(sar[-1]),
            'sar_direction': int(direction[-1]),
        }
