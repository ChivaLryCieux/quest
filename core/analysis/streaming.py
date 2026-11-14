"""流式特征引擎 (StreamingFeatureEngine)

与 FeatureEngineer.calculate_features 数值等价的增量实现：
- 递推类指标 (EMA/MACD/RSI/ATR/ADX/SuperTrend/PSAR/KDJ/StochRSI/OBV/CCI)
  以 O(1) 状态机逐根收盘蜡烛推进，替代每根 O(N) 全量重算；
- 窗口类指标 (BB/WilliamsR/VWAP/VWMA/CMF/VolumeProfile/momentum/volatility)
  从定长 deque 切片 O(window) 计算；
- 只在蜡烛收盘 (commit) 时喂入数据；成形中蜡烛不进入指标状态。

等价性由 tests/test_streaming_equivalence.py 逐字段验证（容差 1e-9）。
"""

from __future__ import annotations

from collections import deque

import numpy as np


class _Ema:
    """pandas ewm(alpha=a, adjust=False) 的标量递推等价物。"""
    __slots__ = ("a", "v", "on")

    def __init__(self, alpha: float):
        self.a = alpha
        self.v = 0.0
        self.on = False

    def push(self, x: float) -> float:
        if not self.on:
            self.v = x
            self.on = True
        else:
            self.v += (x - self.v) * self.a
        return self.v


class StreamingRSI:
    """MathUtils.calc_rsi(close, period) 等价物 (Wilder/EMA 平滑)。"""

    __slots__ = ("_mu", "_md", "_pc")

    def __init__(self, period: int = 14):
        self._mu = _Ema(1.0 / period)
        self._md = _Ema(1.0 / period)
        self._pc = None

    def update(self, close: float) -> float:
        pc, self._pc = self._pc, close
        if pc is None:
            return np.nan
        d = close - pc
        mu = self._mu.push(max(d, 0.0))
        md = self._md.push(max(-d, 0.0))
        if md == 0:
            return np.nan if mu == 0 else 100.0
        return 100.0 - 100.0 / (1.0 + mu / md)


class StreamingATR:
    """MathUtils.calc_atr(df, period) 等价物 (ewm alpha=1/p on TR)。"""

    __slots__ = ("_ema", "_pc")

    def __init__(self, period: int = 14):
        self._ema = _Ema(1.0 / period)
        self._pc = None

    def update(self, h: float, l: float, c: float) -> float:
        pc, self._pc = self._pc, c
        tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
        return self._ema.push(tr)


class StreamingSuperTrend:
    """indicators.trend.SuperTrend 等价物 (递归状态机)。"""

    __slots__ = ("mult", "_atr", "_pc", "_st", "_dir")

    def __init__(self, atr_period: int = 10, multiplier: float = 3.0):
        self.mult = multiplier
        self._atr = _Ema(1.0 / atr_period)
        self._pc = None
        self._st = None
        self._dir = 0

    def update(self, h: float, l: float, c: float):
        pc, self._pc = self._pc, c
        tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
        atr = self._atr.push(tr)
        hl2 = (h + l) / 2.0
        ub = hl2 + self.mult * atr
        lb = hl2 - self.mult * atr

        if self._st is None:
            self._st = ub
            self._dir = -1
            return self._st, self._dir

        st_prev = self._st
        if lb > st_prev or pc < st_prev:
            upper = ub
        else:
            upper = min(ub, st_prev)
        if ub < st_prev or pc > st_prev:
            lower = lb
        else:
            lower = max(lb, st_prev)

        if c > st_prev:
            self._st = lower
            self._dir = 1
        else:
            self._st = upper
            self._dir = -1
        return self._st, self._dir

    @property
    def direction(self) -> int:
        return self._dir

    @property
    def value(self) -> float:
        return 0.0 if self._st is None else self._st


class StreamingADX:
    """indicators.trend.ADXCalculator 等价物 (Wilder 平滑递推)。"""

    __slots__ = ("p", "i", "_prev", "_acc", "_atr", "_pdm", "_mdm",
                 "_dx_d", "_adx", "_adx_d", "_pdi", "_mdi")

    def __init__(self, period: int = 14):
        self.p = period
        self.i = 0
        self._prev = None          # (h, l, c)
        self._acc = []             # 累积阶段 tr/+dm/-dm
        self._atr = self._pdm = self._mdm = None
        self._dx_d = []            # seed 窗口 dx (i=p..2p)
        self._adx = None
        self._adx_d = deque(maxlen=3)
        self._pdi = self._mdi = 0.0

    def update(self, h: float, l: float, c: float):
        i = self.i
        self.i += 1
        prev, self._prev = self._prev, (h, l, c)
        if prev is None:
            self._adx_d.append(0.0)
            return self._result()
        ph, pl, pc = prev

        hd = h - ph
        ld = pl - l
        tr = max(h - l, abs(h - pc), abs(l - pc))
        pdm = hd if (hd > ld and hd > 0) else 0.0
        mdm = ld if (ld > hd and ld > 0) else 0.0

        p = self.p
        if i <= p:
            self._acc.append((tr, pdm, mdm))
            if i == p:
                self._atr = sum(t[0] for t in self._acc)
                self._pdm = sum(t[1] for t in self._acc)
                self._mdm = sum(t[2] for t in self._acc)
        else:
            self._atr = self._atr - self._atr / p + tr
            self._pdm = self._pdm - self._pdm / p + pdm
            self._mdm = self._mdm - self._mdm / p + mdm

        pdi = mdi = 0.0
        if i >= p and self._atr and self._atr > 0:
            pdi = 100.0 * self._pdm / self._atr
            mdi = 100.0 * self._mdm / self._atr
        self._pdi, self._mdi = pdi, mdi

        di_sum = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0

        start = 2 * p
        if p <= i <= start:
            self._dx_d.append(dx)
            if i == start:
                self._adx = float(np.mean(self._dx_d))
        elif i > start:
            self._adx = (self._adx * (p - 1) + dx) / p

        self._adx_d.append(self._adx if self._adx is not None else 0.0)
        return self._result()

    def _result(self):
        adx_d = self._adx_d
        rising = len(adx_d) >= 3 and adx_d[-1] > adx_d[-3]
        return {
            "adx": float(self._adx) if self._adx is not None else 0.0,
            "plus_di": float(self._pdi),
            "minus_di": float(self._mdi),
            "adx_rising": bool(rising),
        }


class StreamingMACD:
    """indicators.momentum.MACDCalculator 等价物。"""

    __slots__ = ("_ef", "_es", "_sg", "macd_d", "sig_d", "hist_d")

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self._ef = _Ema(2.0 / (fast + 1))
        self._es = _Ema(2.0 / (slow + 1))
        self._sg = _Ema(2.0 / (signal + 1))
        self.macd_d = deque(maxlen=3)
        self.sig_d = deque(maxlen=3)
        self.hist_d = deque(maxlen=20)

    def update(self, close: float):
        m = self._ef.push(close) - self._es.push(close)
        s = self._sg.push(m)
        h = m - s
        self.macd_d.append(m)
        self.sig_d.append(s)
        self.hist_d.append(h)
        return m, s, h


class StreamingKDJ:
    """indicators.momentum.KDJCalculator 等价物 (9,3,3)。"""

    __slots__ = ("kp", "_hh", "_ll", "_ke", "_de", "k_d", "d_d")

    def __init__(self, k_period: int = 9, d_period: int = 3, j_smooth: int = 3):
        self.kp = k_period
        self._hh = deque(maxlen=k_period)
        self._ll = deque(maxlen=k_period)
        self._ke = _Ema(1.0 / d_period)
        self._de = _Ema(1.0 / j_smooth)
        self.k_d = deque(maxlen=3)
        self.d_d = deque(maxlen=3)

    def update(self, h: float, l: float, c: float):
        self._hh.append(h)
        self._ll.append(l)
        if len(self._hh) < self.kp:
            self.k_d.append(np.nan)
            self.d_d.append(np.nan)
            return np.nan, np.nan, np.nan
        ll = min(self._ll)
        rsv = (c - ll) / (max(self._hh) - ll + 1e-9) * 100.0
        k = self._ke.push(rsv)
        d = self._de.push(k)
        self.k_d.append(k)
        self.d_d.append(d)
        return k, d, 3.0 * k - 2.0 * d


class StreamingStochRSI:
    """indicators.momentum.StochasticRSI 等价物 (14,14,3,3)。"""

    __slots__ = ("sp", "_rsi", "_rsi_d", "_ke", "_de", "k_d", "d_d")

    def __init__(self, rsi_period: int = 14, stoch_period: int = 14,
                 k_smooth: int = 3, d_smooth: int = 3):
        self.sp = stoch_period
        self._rsi = StreamingRSI(rsi_period)
        self._rsi_d = deque(maxlen=stoch_period)
        self._ke = _Ema(1.0 / k_smooth)
        self._de = _Ema(1.0 / d_smooth)
        self.k_d = deque(maxlen=3)
        self.d_d = deque(maxlen=3)

    def update(self, close: float):
        rsi = self._rsi.update(close)
        self._rsi_d.append(rsi)
        win = list(self._rsi_d)
        if len(win) < self.sp or np.isnan(win).any():
            self.k_d.append(np.nan)
            self.d_d.append(np.nan)
            return np.nan, np.nan
        lo, hi = min(win), max(win)
        stoch = (rsi - lo) / (hi - lo + 1e-9) * 100.0
        k = self._ke.push(stoch)
        d = self._de.push(k)
        self.k_d.append(k)
        self.d_d.append(d)
        return k, d


class StreamingPSAR:
    """indicators.trend.ParabolicSAR 等价物 (AF 递推状态机)。"""

    __slots__ = ("af0", "step", "afmax", "af", "ep", "is_long", "sar",
                 "_pl1", "_pl2", "_ph1", "_ph2")

    def __init__(self, af_start=0.02, af_step=0.02, af_max=0.2):
        self.af0 = af_start
        self.step = af_step
        self.afmax = af_max
        self.af = af_start
        self.ep = None
        self.is_long = True
        self.sar = None
        self._pl1 = self._pl2 = self._ph1 = self._ph2 = None

    def update(self, h: float, l: float):
        if self.sar is None:
            self.sar = l
            self.ep = h
            self._pl1, self._ph1 = l, h
            return self.sar, 1

        if self.is_long:
            sar = self.sar + self.af * (self.ep - self.sar)
            sar = min(sar, self._pl1)
            if self._pl2 is not None:
                sar = min(sar, self._pl2)
            if l < sar:
                self.is_long = False
                sar = self.ep
                self.ep = l
                self.af = self.af0
            elif h > self.ep:
                self.ep = h
                self.af = min(self.af + self.step, self.afmax)
        else:
            sar = self.sar + self.af * (self.ep - self.sar)
            sar = max(sar, self._ph1)
            if self._ph2 is not None:
                sar = max(sar, self._ph2)
            if h > sar:
                self.is_long = True
                sar = self.ep
                self.ep = h
                self.af = self.af0
            elif l < self.ep:
                self.ep = l
                self.af = min(self.af + self.step, self.afmax)

        self.sar = sar
        self._pl2, self._pl1 = self._pl1, l
        self._ph2, self._ph1 = self._ph1, h
        return self.sar, (1 if self.is_long else -1)


class StreamingCCI:
    """indicators.momentum.CCICalculator 等价物 (20)。"""

    __slots__ = ("p", "_tp", "cci_d")

    def __init__(self, period: int = 20):
        self.p = period
        self._tp = deque(maxlen=period)
        self.cci_d = deque(maxlen=2)

    def update(self, h: float, l: float, c: float):
        self._tp.append((h + l + c) / 3.0)
        if len(self._tp) < self.p:
            self.cci_d.append(np.nan)
            return np.nan
        win = np.asarray(self._tp)
        sma = win.mean()
        mad = np.abs(win - sma).mean()
        cci = (self._tp[-1] - sma) / (0.015 * mad + 1e-9)
        self.cci_d.append(cci)
        return cci


class StreamingOBV:
    """indicators.volume.OBVCalculator 等价物。"""

    __slots__ = ("obv", "obv_d", "_pc")

    def __init__(self):
        self.obv = 0.0
        self.obv_d = deque(maxlen=20)
        self._pc = None

    def update(self, close: float, volume: float):
        pc, self._pc = self._pc, close
        if pc is not None:
            d = close - pc
            self.obv += (1.0 if d > 0 else (-1.0 if d < 0 else 0.0)) * volume
        self.obv_d.append(self.obv)
        return self.obv


class _IchimokuState:
    """Ichimoku 递推窗口状态 (mid9/mid26/mid52 + 26 期前移)。"""

    __slots__ = ("_h", "_l", "mid_tk", "mid_kj", "mid52")

    def __init__(self):
        self._h = deque(maxlen=52)
        self._l = deque(maxlen=52)
        self.mid_tk = deque(maxlen=28)   # tenkan = mid(9)
        self.mid_kj = deque(maxlen=28)   # kijun  = mid(26)
        self.mid52 = deque(maxlen=28)    # span_b 原始 mid(52)

    def update(self, h: float, l: float):
        self._h.append(h)
        self._l.append(l)
        n = len(self._h)

        def mid(period: int) -> float:
            if n < period:
                return np.nan
            hh = max(list(self._h)[-period:])
            ll = min(list(self._l)[-period:])
            return (hh + ll) / 2.0

        self.mid_tk.append(mid(9))
        self.mid_kj.append(mid(26))
        self.mid52.append(mid(52))


class StreamingFeatureEngine:
    """全量特征上下文流式引擎（收盘蜡烛驱动）。

    update() 消费一根已收盘蜡烛 (O(1) 递推 + 小窗口)，
    context() 组装与 FeatureEngineer.calculate_features 相同键的 dict。
    """

    MOMENTUM_PERIODS = (1, 10, 50, 96)
    VOLATILITY_PERIODS = (5, 50, 96)
    VOL_MA_PERIOD = 96
    VWAP_PERIOD = 288
    MIN_BARS = 100
    _WIN = 560  # 覆盖 VWAP(288)/Ichimoku(52+26)/momentum(96)/VP(全部)

    def __init__(self):
        self.n = 0
        self._h = deque(maxlen=self._WIN)
        self._l = deque(maxlen=self._WIN)
        self._c = deque(maxlen=self._WIN)
        self._v = deque(maxlen=self._WIN)
        # VWAP 专用窗口：滚动和（每行 tp_diff_sq 用该行自己的 vwap_i，与批量一致）
        self._tp = deque(maxlen=self.VWAP_PERIOD)
        self._tpv = deque(maxlen=self.VWAP_PERIOD)
        self._wv = deque(maxlen=self.VWAP_PERIOD)
        self._tpds = deque(maxlen=self.VWAP_PERIOD)   # (tp_i - vwap_i)^2 * v_i
        self._s_tpv = self._s_wv = self._s_tpds = 0.0

        self.atr = StreamingATR(14)
        self.st = StreamingSuperTrend(10, 3.0)
        self.macd = StreamingMACD(12, 26, 9)
        self.fmacd = StreamingMACD(8, 17, 9)
        self.kdj = StreamingKDJ(9, 3, 3)
        self.adx = StreamingADX(14)
        self.stoch = StreamingStochRSI(14, 14, 3, 3)
        self.psar = StreamingPSAR()
        self.cci = StreamingCCI(20)
        self.obv = StreamingOBV()
        self.ichi = _IchimokuState()
        self._last_ts = None

    # ------------------------------------------------------------------ ingest

    def update(self, row) -> bool:
        """喂入一根已收盘蜡烛 [ts,o,h,l,c,v,tb]。同 ts 去重。"""
        ts = float(row[0])
        if self._last_ts is not None and ts <= self._last_ts:
            return False
        self._last_ts = ts
        o, h, l, c, v = (float(row[1]), float(row[2]), float(row[3]),
                         float(row[4]), float(row[5]))

        self._h.append(h)
        self._l.append(l)
        self._c.append(c)
        self._v.append(v)
        self.n += 1

        tp = (h + l + c) / 3.0
        if len(self._wv) == self.VWAP_PERIOD:
            self._s_tpv -= self._tpv[0]
            self._s_wv -= self._wv[0]
            self._s_tpds -= self._tpds[0]
        tpv = tp * v
        self._tp.append(tp)
        self._tpv.append(tpv)
        self._wv.append(v)
        self._s_tpv += tpv
        self._s_wv += v
        vwap_i = self._s_tpv / (self._s_wv + 1e-9)
        tpds = (tp - vwap_i) ** 2 * v
        self._tpds.append(tpds)
        self._s_tpds += tpds

        self.atr.update(h, l, c)
        self.st.update(h, l, c)
        self.macd.update(c)
        self.fmacd.update(c)
        self.kdj.update(h, l, c)
        self.adx.update(h, l, c)
        self.stoch.update(c)
        self.psar.update(h, l)
        self.cci.update(h, l, c)
        self.obv.update(c, v)
        self.ichi.update(h, l)
        return True

    # ------------------------------------------------------------------ context

    @staticmethod
    def _div_check(recent_price: np.ndarray, recent_sig: np.ndarray):
        """背离检测：与 MACD/OBV 批量实现相同窗口逻辑。"""
        bull = bear = False
        lb = len(recent_price)
        if lb >= 5:
            bull = (recent_price[-1] <= np.min(recent_price)
                    and recent_sig[-1] > np.min(recent_sig[:-1]))
            bear = (recent_price[-1] >= np.max(recent_price)
                    and recent_sig[-1] < np.max(recent_sig[:-1]))
        return bull, bear

    def context(self, curr_price=None, btc_change_pct=0.0, obi_value=0.0):
        """组装特征上下文（键与 FeatureEngineer.calculate_features 一致）。"""
        if self.n < self.MIN_BARS:
            return None, None

        close = np.asarray(self._c)
        high = np.asarray(self._h)
        low = np.asarray(self._l)
        vol = np.asarray(self._v)
        n = len(close)
        price = float(close[-1]) if curr_price is None else float(curr_price)

        # 1. 相对成交量 Vol/MA(Vol,96)
        rel_vol = float(vol[-1] / (vol[-self.VOL_MA_PERIOD:].mean() + 1e-9))

        # 2. 对数动量 (1,10,50,96)
        momentum_values = {
            f"T_{T}": (float(np.log(close[-1] / close[-(T + 1)])) if n > T else 0.0)
            for T in self.MOMENTUM_PERIODS
        }

        # 3. 滚动波动率 (5,50,96) —— pandas log(c/c.shift).fillna(0).tail(T).std()
        # 批量实现首元素 fillna(0)，长度 = n（n==T 边界会包含这个 0）
        log_returns = np.concatenate(([0.0], np.log(close[1:] / close[:-1])))
        volatility_values = {}
        for T in self.VOLATILITY_PERIODS:
            if len(log_returns) >= T:
                volatility_values[f"T_{T}"] = float(np.std(log_returns[-T:], ddof=1))
            else:
                volatility_values[f"T_{T}"] = 0.0

        # 4. MACD 标准 (12,26,9) + 快速 (8,17,9)
        m, s, hist = self.macd.macd_d[-1], self.macd.sig_d[-1], self.macd.hist_d[-1]
        fm, fs, fhist = self.fmacd.macd_d[-1], self.fmacd.sig_d[-1], self.fmacd.hist_d[-1]
        macd_normalized = m / close[-1] if close[-1] != 0 else 0.0

        prev_diff = self.macd.macd_d[-2] - self.macd.sig_d[-2]
        curr_diff = m - s
        golden_cross = prev_diff <= 0 < curr_diff
        death_cross = prev_diff >= 0 > curr_diff
        above_zero = m > 0

        f_prev_diff = self.fmacd.macd_d[-2] - self.fmacd.sig_d[-2]
        f_curr_diff = fm - fs
        f_golden = f_prev_diff <= 0 < f_curr_diff
        f_death = f_prev_diff >= 0 > f_curr_diff
        f_above = fm > 0

        h1, h2, h3 = self.macd.hist_d[-3], self.macd.hist_d[-2], self.macd.hist_d[-1]
        hist_turning_up = h1 > h2 and h3 > h2
        hist_turning_down = h1 < h2 and h3 < h2
        fh1, fh2, fh3 = self.fmacd.hist_d[-3], self.fmacd.hist_d[-2], self.fmacd.hist_d[-1]
        f_hist_up = fh1 > fh2 and fh3 > fh2

        lb = min(20, n - 1)
        if lb >= 5:
            macd_bull, macd_bear = self._div_check(close[-lb:], np.asarray(self.macd.hist_d)[-lb:])
        else:
            macd_bull = macd_bear = False

        # 5. 布林带 (20, 2.0)
        bw = close[-20:]
        bb_mid = float(bw.mean())
        bb_std = float(bw.std(ddof=1))
        bb_upper = bb_mid + 2.0 * bb_std
        bb_lower = bb_mid - 2.0 * bb_std
        width = bb_upper - bb_lower
        bb_distance = 0.0 if width == 0 else float((close[-1] - bb_mid) / width)

        # 6. SuperTrend / KDJ / ADX
        st_val, st_dir = self.st.value, self.st.direction
        k = self.kdj.k_d[-1]
        d = self.kdj.d_d[-1]
        j = 3.0 * k - 2.0 * d
        k_minus_d = k - d
        kdj_golden = self.kdj.k_d[-2] < self.kdj.d_d[-2] and k > d
        kdj_death = self.kdj.k_d[-2] > self.kdj.d_d[-2] and k < d
        adx_res = self.adx._result()

        # 7. VWAP (288) —— var = Σ(tp_i - vwap_i)^2·v_i / Σv（每行用自己的 vwap_i）
        sv = self._s_wv
        vwap = self._s_tpv / (sv + 1e-9)
        var = self._s_tpds / (sv + 1e-9)
        vwap_std = float(np.sqrt(max(0.0, var)))
        vwap_upper = vwap + 2.0 * vwap_std
        vwap_lower = vwap - 2.0 * vwap_std
        vwap_distance = float(np.clip((close[-1] - vwap) / (vwap + 1e-9) * 100.0, -5, 5))
        if np.isnan(vwap_distance):
            vwap_distance = 0.0

        # 8. Ichimoku —— n 对应 len(df)
        # span_a = (tenkan + kijun)/2 前移 26 → (mid_tk + mid_kj)/2 @ -27
        tk = self.ichi.mid_tk[-1]
        kj = self.ichi.mid_kj[-1]
        tenkan = float(tk) if n >= 9 and not np.isnan(tk) else 0.0
        kijun = float(kj) if n >= 26 and not np.isnan(kj) else 0.0
        if n >= 35 and len(self.ichi.mid_tk) >= 27 and len(self.ichi.mid_kj) >= 27:
            span_a = float((self.ichi.mid_tk[-27] + self.ichi.mid_kj[-27]) / 2.0)
        else:
            span_a = 0.0
        span_b = float(self.ichi.mid52[-27]) if (n >= 78 and len(self.ichi.mid52) >= 27) else 0.0
        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)
        last_close = float(close[-1])
        if last_close > cloud_top:
            cloud_signal = 1
        elif last_close < cloud_bottom:
            cloud_signal = -1
        else:
            cloud_signal = 0
        tk_cross = 0
        if len(self.ichi.mid_tk) >= 2 and len(self.ichi.mid_kj) >= 2:
            tk_prev_diff = self.ichi.mid_tk[-2] - self.ichi.mid_kj[-2]
            tk_curr_diff = tk - kj
            if not (np.isnan(tk_prev_diff) or np.isnan(tk_curr_diff)):
                if tk_prev_diff <= 0 < tk_curr_diff:
                    tk_cross = 1
                elif tk_prev_diff >= 0 > tk_curr_diff:
                    tk_cross = -1

        # 9. Stochastic RSI
        sk = self.stoch.k_d[-1]
        sd = self.stoch.d_d[-1]
        sk = 50.0 if np.isnan(sk) else float(sk)
        sd = 50.0 if np.isnan(sd) else float(sd)
        s_prev_k, s_prev_d = self.stoch.k_d[-2], self.stoch.d_d[-2]
        stoch_golden = stoch_death = False
        if not (np.isnan(s_prev_k) or np.isnan(s_prev_d) or np.isnan(self.stoch.k_d[-1])):
            stoch_golden = s_prev_k < s_prev_d and self.stoch.k_d[-1] > self.stoch.d_d[-1]
            stoch_death = s_prev_k > s_prev_d and self.stoch.k_d[-1] < self.stoch.d_d[-1]

        # 10. OBV
        obv_arr = np.asarray(self.obv.obv_d)
        obv_val = float(obv_arr[-1])
        obv_trend = 0.0
        if len(obv_arr) >= 10:
            y = obv_arr[-10:]
            x = np.arange(10, dtype=float)
            slope = np.polyfit(x, y, 1)[0]
            obv_trend = float(slope / (abs(obv_val) + 1e-9))
        obv_bull = obv_bear = False
        if len(obv_arr) >= 20 and n >= 20:
            obv_bull, obv_bear = self._div_check(close[-20:], obv_arr[-20:])

        # 11. CCI / WilliamsR
        cci_val = self.cci.cci_d[-1]
        cci_val = 0.0 if np.isnan(cci_val) else float(cci_val)
        cci_prev = self.cci.cci_d[-2] if len(self.cci.cci_d) >= 2 else np.nan
        cci_prev = 0.0 if np.isnan(cci_prev) else float(cci_prev)
        if n >= 14:
            hh14 = high[-14:].max()
            ll14 = low[-14:].min()
            wr_val = float((hh14 - close[-1]) / (hh14 - ll14 + 1e-9) * -100.0)
        else:
            wr_val = -50.0

        # 12. Parabolic SAR
        psar, psar_dir = self.psar.sar, (1 if self.psar.is_long else -1)

        # 13. VWMA / CMF (20)
        c20 = close[-20:]
        v20 = vol[-20:]
        cv_sum = float((c20 * v20).sum())
        v_sum = float(v20.sum())
        vwma_val = cv_sum / (v_sum + 1e-9) if n >= 20 else float(close[-1])
        sma_val = float(c20.mean()) if n >= 20 else 0.0
        vwma_dev = (vwma_val - sma_val) / (sma_val + 1e-9) * 100.0
        if n >= 20:
            hl = high[-20:] - low[-20:]
            mfm = ((c20 - low[-20:]) - (high[-20:] - c20)) / (hl + 1e-9)
            cmf_val = float((mfm * v20).sum() / (v_sum + 1e-9))
        else:
            cmf_val = 0.0

        # 14. Volume Profile (50 bins, 全窗口)
        p_min, p_max = close.min(), close.max()
        if p_max > p_min and n >= 10:
            idx = ((close - p_min) / (p_max - p_min) * 49).astype(int)
            idx = np.clip(idx, 0, 49)
            profile = np.bincount(idx, weights=vol, minlength=50)
            edges = np.linspace(p_min, p_max, 51)
            centers = (edges[:-1] + edges[1:]) / 2
            poc_i = int(np.argmax(profile))
            target = profile.sum() * 0.70
            acc = profile[poc_i]
            lo_i = hi_i = poc_i
            while acc < target and (lo_i > 0 or hi_i < 49):
                e_lo = profile[lo_i - 1] if lo_i > 0 else 0
                e_hi = profile[hi_i + 1] if hi_i < 49 else 0
                if e_lo >= e_hi and lo_i > 0:
                    lo_i -= 1
                    acc += profile[lo_i]
                elif hi_i < 49:
                    hi_i += 1
                    acc += profile[hi_i]
                else:
                    lo_i -= 1
                    acc += profile[lo_i]
            vp_poc, vp_vah, vp_val = float(centers[poc_i]), float(centers[hi_i]), float(centers[lo_i])
        else:
            # 批量实现回退: len<10 → close[-1]; max==min → price_min(≡close[-1])
            vp_poc = vp_vah = vp_val = last_close

        # 15. RSI 标量（复用 StochRSI 内部 RSI(14) 序列）
        last_rsi = self._last_rsi()

        # 反转因子
        reversal_raw = 0.0
        if macd_bull:
            reversal_raw += 0.55
        if macd_bear:
            reversal_raw -= 0.55
        if k < 25 and bb_distance < -0.45:
            reversal_raw += 0.25
        if k > 75 and bb_distance > 0.45:
            reversal_raw -= 0.25
        if hist_turning_up:
            reversal_raw += 0.15
        if hist_turning_down:
            reversal_raw -= 0.15
        reversal_factor = float(np.clip(reversal_raw, -1.0, 1.0))

        tech_features = np.array([
            rel_vol,
            momentum_values.get("T_1", 0.0),
            momentum_values.get("T_10", 0.0),
            momentum_values.get("T_50", 0.0),
            momentum_values.get("T_96", 0.0),
            volatility_values.get("T_5", 0.0),
            volatility_values.get("T_50", 0.0),
            volatility_values.get("T_96", 0.0),
            macd_normalized,
            bb_distance,
            float(st_dir),
            k_minus_d,
            float(cloud_signal),
            sk / 100.0,
            obv_trend,
            cci_val / 200.0,
            (wr_val + 50) / 50.0,
            float(psar_dir),
            vwma_dev / 10.0,
            cmf_val,
        ]).reshape(1, -1)

        context = {
            "price": price,
            "atr": self.atr._ema.v,
            "rsi": last_rsi,
            "bb_middle": bb_mid,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_distance": bb_distance,
            "supertrend_value": st_val,
            "supertrend_direction": st_dir,
            "macd": m,
            "macd_signal": s,
            "macd_histogram": hist,
            "macd_normalized": macd_normalized,
            "macd_golden_cross": golden_cross,
            "macd_death_cross": death_cross,
            "macd_above_zero": above_zero,
            "macd_hist_turning_up": hist_turning_up,
            "macd_hist_turning_down": hist_turning_down,
            "macd_bullish_divergence": macd_bull,
            "macd_bearish_divergence": macd_bear,
            "reversal_factor": reversal_factor,
            "fast_macd": fm,
            "fast_macd_histogram": fhist,
            "fast_macd_golden_cross": f_golden,
            "fast_macd_death_cross": f_death,
            "fast_macd_above_zero": f_above,
            "fast_macd_hist_turning_up": f_hist_up,
            "kdj_k": k,
            "kdj_d": d,
            "kdj_j": j,
            "k_minus_d": k_minus_d,
            "kdj_golden_cross": kdj_golden,
            "kdj_death_cross": kdj_death,
            "adx": adx_res["adx"],
            "plus_di": adx_res["plus_di"],
            "minus_di": adx_res["minus_di"],
            "adx_rising": adx_res["adx_rising"],
            "vwap": vwap,
            "vwap_distance": vwap_distance,
            "vwap_upper": vwap_upper,
            "vwap_lower": vwap_lower,
            "relative_volume": rel_vol,
            "momentum_values": momentum_values,
            "volatility_values": volatility_values,
            "obi": obi_value,
            "ichimoku_tenkan": tenkan,
            "ichimoku_kijun": kijun,
            "ichimoku_span_a": span_a,
            "ichimoku_span_b": span_b,
            "ichimoku_cloud_signal": cloud_signal,
            "ichimoku_tk_cross": tk_cross,
            "stoch_rsi_k": sk,
            "stoch_rsi_d": sd,
            "stoch_rsi_golden": stoch_golden,
            "stoch_rsi_death": stoch_death,
            "obv": obv_val,
            "obv_trend": obv_trend,
            "obv_bearish_div": obv_bear,
            "obv_bullish_div": obv_bull,
            "cci": cci_val,
            "cci_overbought": cci_val > 100,
            "cci_oversold": cci_val < -100,
            "williams_r": wr_val,
            "wr_overbought": wr_val > -20,
            "wr_oversold": wr_val < -80,
            "psar": psar,
            "psar_direction": psar_dir,
            "vwma": vwma_val,
            "vwma_deviation": vwma_dev,
            "vwma_bullish": vwma_val > sma_val,
            "cmf": cmf_val,
            "cmf_bullish": cmf_val > 0.05,
            "cmf_bearish": cmf_val < -0.05,
            "vp_poc": vp_poc,
            "vp_vah": vp_vah,
            "vp_val": vp_val,
        }
        return tech_features, context

    def _last_rsi(self) -> float:
        rsi_d = self.stoch._rsi_d
        if not rsi_d:
            return np.nan
        return float(rsi_d[-1])

    # ------------------------------------------------------------------ 只读视图

    @property
    def closes(self) -> np.ndarray:
        """已收盘 close 数组（按时间序）。"""
        return np.asarray(self._c)

    @property
    def volumes(self) -> np.ndarray:
        return np.asarray(self._v)

    @property
    def highs(self) -> np.ndarray:
        return np.asarray(self._h)

    @property
    def lows(self) -> np.ndarray:
        return np.asarray(self._l)

    # ------------------------------------------------------------------ 兼容门面

    def calculate_features(self, history_df, curr_price, btc_change_pct=0.0, obi_value=0.0):
        """与 FeatureEngineer 相同的批量接口：逐行喂入后返回最后上下文。"""
        for row in history_df.itertuples(index=False, name=None):
            self.update(row)
        return self.context(curr_price, btc_change_pct, obi_value)
