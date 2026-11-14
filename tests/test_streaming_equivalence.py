"""流式 vs 批量特征引擎数值等价性测试

将同一段合成K线历史分别喂给:
  - FeatureEngineer.calculate_features (批量, oracle)
  - StreamingFeatureEngine.update + context (增量)

在多个检查点对比 context 全部数值字段，容差 1e-9。
"""
import unittest

import numpy as np
import pandas as pd

from core.analysis.feature_engineering import FeatureEngineer
from core.analysis.streaming import StreamingFeatureEngine


def _make_candles(n=420, seed=7):
    rng = np.random.default_rng(seed)
    ts0 = 1_700_000_000_000
    price = 100.0
    rows = []
    for i in range(n):
        drift = 0.0004 * np.sin(i / 37.0) + rng.normal(0, 0.0018)
        o = price
        c = price * (1 + drift)
        hi = max(o, c) * (1 + abs(rng.normal(0, 0.0008)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.0008)))
        v = abs(rng.normal(500, 150)) * (1 + 0.5 * np.sin(i / 23.0))
        rows.append([ts0 + i * 300_000, o, hi, lo, c, v, v * 0.5])
        price = c
    return pd.DataFrame(
        rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy']
    )


# context 中需要逐值对比的字段（排除 dict/bool/str 类型）
NUMERIC_KEYS = [
    'price', 'atr', 'rsi',
    'bb_middle', 'bb_upper', 'bb_lower', 'bb_distance',
    'supertrend_value', 'supertrend_direction',
    'macd', 'macd_signal', 'macd_histogram', 'macd_normalized',
    'reversal_factor',
    'fast_macd', 'fast_macd_histogram',
    'kdj_k', 'kdj_d', 'kdj_j', 'k_minus_d',
    'adx', 'plus_di', 'minus_di',
    'vwap', 'vwap_distance', 'vwap_upper', 'vwap_lower',
    'relative_volume',
    'obi',
    'ichimoku_tenkan', 'ichimoku_kijun', 'ichimoku_span_a', 'ichimoku_span_b',
    'ichimoku_cloud_signal', 'ichimoku_tk_cross',
    'stoch_rsi_k', 'stoch_rsi_d',
    'obv', 'obv_trend',
    'cci', 'williams_r',
    'psar', 'psar_direction',
    'vwma', 'vwma_deviation', 'cmf',
    'vp_poc', 'vp_vah', 'vp_val',
]
BOOL_KEYS = [
    'macd_golden_cross', 'macd_death_cross', 'macd_above_zero',
    'macd_hist_turning_up', 'macd_hist_turning_down',
    'macd_bullish_divergence', 'macd_bearish_divergence',
    'fast_macd_golden_cross', 'fast_macd_death_cross',
    'fast_macd_above_zero', 'fast_macd_hist_turning_up',
    'kdj_golden_cross', 'kdj_death_cross', 'adx_rising',
    'stoch_rsi_golden', 'stoch_rsi_death',
    'obv_bearish_div', 'obv_bullish_div',
    'cci_overbought', 'cci_oversold',
    'wr_overbought', 'wr_oversold',
    'vwma_bullish', 'cmf_bullish', 'cmf_bearish',
]


def _compare_ctx(batch_ctx, stream_ctx, n):
    for key in NUMERIC_KEYS:
        b = float(batch_ctx[key])
        s = float(stream_ctx[key])
        if np.isnan(b) and np.isnan(s):
            continue
        tol = max(1e-9, abs(b) * 1e-9)
        assert abs(b - s) <= tol, f"n={n} key={key}: batch={b} stream={s}"
    for key in BOOL_KEYS:
        assert bool(batch_ctx[key]) == bool(stream_ctx[key]), (
            f"n={n} key={key}: batch={batch_ctx[key]} stream={stream_ctx[key]}"
        )
    for sub in ('momentum_values', 'volatility_values'):
        for k, bv in batch_ctx[sub].items():
            sv = stream_ctx[sub][k]
            tol = max(1e-9, abs(float(bv)) * 1e-9)
            assert abs(float(bv) - float(sv)) <= tol, f"n={n} {sub}.{k}: {bv} vs {sv}"


class TestStreamingEquivalence(unittest.TestCase):
    def test_streaming_matches_batch_at_checkpoints(self):
        df = _make_candles()
        engineer = FeatureEngineer()
        stream = StreamingFeatureEngine()

        checkpoints = {100, 150, 250, 300, 419, 420}
        for i, row in enumerate(df.itertuples(index=False, name=None), start=1):
            stream.update(row)
            if i in checkpoints:
                batch_tf, batch_ctx = engineer.calculate_features(
                    df.iloc[:i], float(df['close'].iloc[i - 1])
                )
                stream_tf, stream_ctx = stream.context(float(df['close'].iloc[i - 1]))
                self.assertIsNotNone(batch_ctx)
                self.assertIsNotNone(stream_ctx)
                _compare_ctx(batch_ctx, stream_ctx, i)
                np.testing.assert_allclose(
                    batch_tf[0], stream_tf[0], rtol=1e-9, atol=1e-9,
                    err_msg=f"tech_features mismatch at n={i}",
                )

    def test_every_bar_streaming_vs_batch_tail(self):
        """从 n=100 起每根都与批量对比末值。"""
        df = _make_candles(160, seed=11)
        engineer = FeatureEngineer()
        stream = StreamingFeatureEngine()
        for i, row in enumerate(df.itertuples(index=False, name=None), start=1):
            stream.update(row)
            if i < 100:
                continue
            _, batch_ctx = engineer.calculate_features(df.iloc[:i], 0.0)
            _, stream_ctx = stream.context(0.0)
            _compare_ctx(batch_ctx, stream_ctx, i)


class TestRingSemantics(unittest.TestCase):
    def test_push_commits_on_ts_advance(self):
        from core.analysis.ring import CandleRing
        ring = CandleRing(5)
        assert ring.push([1, 1, 2, 0.5, 1.5, 10, 5])[0] == 'appended'
        assert ring.push([1, 1, 2, 0.5, 1.6, 11, 5])[0] == 'updated'
        res, closed = ring.push([2, 1.6, 3, 1, 2.5, 20, 10])
        assert res == 'committed'
        assert closed[4] == 1.6  # 上一根以最后的成形值收盘
        assert ring.last_ts == 2
        assert ring.push([0, 9, 9, 9, 9, 9, 9])[0] == 'stale'

    def test_wraparound_order(self):
        from core.analysis.ring import CandleRing
        ring = CandleRing(4)
        for i in range(6):
            ring.push([i, i, i + 1, i - 1, i, i, i])
        arr = ring.array()
        assert arr[:, 0].tolist() == [2, 3, 4, 5]
        assert ring.column('close')[-1] == 5


if __name__ == '__main__':
    unittest.main()
