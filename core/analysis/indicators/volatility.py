import numpy as np
import pandas as pd


class BollingerBands:
    """布林带指标 (20周期, 2倍标准差)"""

    def __init__(self, period=20, std_mult=2.0):
        self.period = period
        self.std_mult = std_mult

    def calculate(self, df):
        """
        计算布林带
        Returns: (middle, upper, lower, distance)
            middle: 中轨 (SMA)
            upper: 上轨
            lower: 下轨
            distance: 归一化距离 (close - middle) / (upper - lower)
        """
        close = df['close']
        middle = close.rolling(window=self.period).mean()
        std = close.rolling(window=self.period).std()
        upper = middle + self.std_mult * std
        lower = middle - self.std_mult * std

        # 归一化距离: (close - middle) / (upper - lower)
        band_width = upper - lower
        distance = (close - middle) / band_width.replace(0, np.nan)
        distance = distance.fillna(0)

        return {
            'middle': middle.iloc[-1] if len(middle) > 0 else 0.0,
            'upper': upper.iloc[-1] if len(upper) > 0 else 0.0,
            'lower': lower.iloc[-1] if len(lower) > 0 else 0.0,
            'distance': distance.iloc[-1] if len(distance) > 0 else 0.0,
            'middle_series': middle,
            'upper_series': upper,
            'lower_series': lower
        }

    def get_latest(self, df):
        """获取最新的布林带值"""
        result = self.calculate(df)
        return result['middle'], result['upper'], result['lower'], result['distance']
