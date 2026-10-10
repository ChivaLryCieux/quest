import numpy as np
import pandas as pd


class RollingVolatilityCalculator:
    def __init__(self, periods=[5, 10, 25, 50]):
        self.periods = periods

    def update(self, price):
        """Placeholder for online updates."""
        return {}

    def calculate_all_volatilities(self, prices_list):
        """Calculate volatilities from price list."""
        results = {}
        # Data validation
        if not prices_list or len(prices_list) < 2:
            for w in self.periods:
                results[f"T_{w}"] = 0.0
            return results

        try:
            # Convert to numpy array and calculate log returns
            arr = np.array(prices_list, dtype=float)
            arr = np.maximum(arr, 1e-9)  # Avoid log(0)
            log_returns = np.diff(np.log(arr))

            # Calculate volatility for each window
            for w in self.periods:
                if len(log_returns) >= w:
                    window_slice = log_returns[-w:]
                    vol = np.std(window_slice)
                    results[f"T_{w}"] = vol
                else:
                    if len(log_returns) > 0:
                        results[f"T_{w}"] = np.std(log_returns)
                    else:
                        results[f"T_{w}"] = 0.0

        except Exception:
            for w in self.periods:
                results[f"T_{w}"] = 0.0

        return results

    def calculate_from_history(self, history_df):
        """Calculate volatilities from DataFrame."""
        if len(history_df) < max(self.periods) + 2:
            return {f"T_{t}": 0.0 for t in self.periods}

        log_returns = np.log(history_df['close'] / history_df['close'].shift(1)).fillna(0)

        vol_values = {}
        for T in self.periods:
            if len(log_returns) >= T:
                vol = log_returns.tail(T).std()
                if np.isnan(vol):
                    vol = 0.0
                vol_values[f"T_{T}"] = vol
            else:
                vol_values[f"T_{T}"] = 0.0

        return vol_values


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
