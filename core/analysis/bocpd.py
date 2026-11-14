import numpy as np
import pandas as pd
from scipy.special import gammaln


class IncrementalBOCPD:
    """BOCPD 增量检测器：常驻 run-length 后验，每根收盘 O(R) 更新。

    与 BOCPDDetector.detect_changepoints 的逐步语义等价
    （同一个递推公式，只是后验数组常驻而非每次重算）。
    当后验长度超过 max_runlen 时截断尾部（保留最高概率区），
    控制稳态开销。
    """

    MU0, KAPPA0, ALPHA0, BETA0 = 0.0, 0.1, 2.0, 0.0001

    def __init__(self, ema_span=5, hazard_lambda=30, drop_thresh=8,
                 min_gap=5, max_runlen=288):
        self.ema_alpha = 2.0 / (ema_span + 1)
        self.hazard = 1.0 / hazard_lambda
        self.drop_thresh = drop_thresh
        self.min_gap = min_gap
        self.max_runlen = max_runlen

        self._prev_close = None
        self._ema = 0.0
        self._ema_on = False

        self._lrl = np.array([0.0])                     # log run-length 后验
        self._mu = np.array([self.MU0])
        self._kappa = np.array([self.KAPPA0])
        self._alpha = np.array([self.ALPHA0])
        self._beta = np.array([self.BETA0])

        self._n = 0           # 已处理 close 数量
        self._prev_mode = 0
        self._last_cp = -min_gap
        self.last_cp_index: int | None = None

    @staticmethod
    def _st_logpdf(x, alpha, beta, kappa, mu):
        return BOCPDDetector._st_logpdf(x, alpha, beta, kappa, mu)

    def update(self, close_price: float) -> int | None:
        """喂入一根收盘价。若本根检测到变点，返回其 close 下标，否则 None。"""
        price = float(close_price)
        prev, self._prev_close = self._prev_close, price
        self._n += 1
        if prev is None:
            return None

        # signal = log_ret - ema_lag（ema 滞后一项，与批量 _build_signal 一致）
        r = np.log(max(price, 1e-10) / max(prev, 1e-10))
        if not self._ema_on:
            x = r - 0.0
            self._ema = r
            self._ema_on = True
        else:
            x = r - self._ema
            self._ema += (r - self._ema) * self.ema_alpha

        # BOCPD 单步：增长 run-length / 变点重启
        log_pred = self._st_logpdf(x, self._alpha, self._beta, self._kappa, self._mu)
        log_joint = self._lrl + log_pred
        next_lrl = np.concatenate([
            [np.logaddexp.reduce(log_joint) + np.log(self.hazard)],
            log_joint + np.log(1.0 - self.hazard),
        ])
        next_lrl -= np.logaddexp.reduce(next_lrl)
        self._lrl = next_lrl

        kappa_new = self._kappa + 1.0
        mu_new = (self._kappa * self._mu + x) / kappa_new
        alpha_new = self._alpha + 0.5
        beta_new = self._beta + self._kappa * (x - self._mu) ** 2 / (2.0 * kappa_new)
        self._mu = np.concatenate([[self.MU0], mu_new])
        self._kappa = np.concatenate([[self.KAPPA0], kappa_new])
        self._alpha = np.concatenate([[self.ALPHA0], alpha_new])
        self._beta = np.concatenate([[self.BETA0], beta_new])

        # 截断：保留前 max_runlen 个 run-length（最高概率区）
        if len(self._lrl) > self.max_runlen:
            self._lrl = self._lrl[:self.max_runlen]
            self._mu = self._mu[:self.max_runlen]
            self._kappa = self._kappa[:self.max_runlen]
            self._alpha = self._alpha[:self.max_runlen]
            self._beta = self._beta[:self.max_runlen]
            self._lrl -= np.logaddexp.reduce(self._lrl)

        mode = int(np.argmax(np.exp(self._lrl)))
        # 批量语义: mode_rl[0] = mode_rl[1]（首点重复，不产生 drop）
        # len(close)<30 时批量整体返回空 —— 变点登记占位但不触发
        cp = None
        if self._n == 2:
            self._prev_mode = mode
        elif self._n >= 3:
            if (self._prev_mode - mode) > self.drop_thresh and \
                    (self._n - 1) - self._last_cp >= self.min_gap:
                self._last_cp = self._n - 1
                if self._n >= 30:
                    self.last_cp_index = self._n - 1
                    cp = self._n - 1
            self._prev_mode = mode
        return cp


class BOCPDDetector:
    """BOCPD变点检测器（离线重算，在线触发）。"""

    def __init__(self, ema_span=5, hazard_lambda=30, drop_thresh=8, min_gap=5):
        self.ema_span = ema_span
        self.hazard_lambda = hazard_lambda
        self.drop_thresh = drop_thresh
        self.min_gap = min_gap

    @staticmethod
    def _st_logpdf(x, alpha, beta, kappa, mu):
        nu = 2.0 * alpha
        s2 = beta * (kappa + 1.0) / (alpha * kappa)
        return (
            gammaln((nu + 1.0) / 2.0)
            - gammaln(nu / 2.0)
            - 0.5 * np.log(np.pi * nu * s2)
            - (nu + 1.0) / 2.0 * np.log(1.0 + (x - mu) ** 2 / (nu * s2))
        )

    def _build_signal(self, close):
        log_ret = np.diff(np.log(np.maximum(close, 1e-10)))
        ema = pd.Series(log_ret).ewm(span=self.ema_span, adjust=False).mean().values
        ema_lag = np.concatenate([[0.0], ema[:-1]])
        return log_ret - ema_lag

    def _bocpd(self, signal, mu0=0.0, kappa0=0.1, alpha0=2.0, beta0=0.0001):
        if len(signal) == 0:
            return np.array([], dtype=int)

        hazard = 1.0 / self.hazard_lambda
        log_run_length = np.array([0.0])
        mu_arr = np.array([mu0])
        kappa_arr = np.array([kappa0])
        alpha_arr = np.array([alpha0])
        beta_arr = np.array([beta0])

        mode_rl = []
        for x in signal:
            log_pred = self._st_logpdf(x, alpha_arr, beta_arr, kappa_arr, mu_arr)
            log_joint = log_run_length + log_pred
            next_run_length = np.concatenate(
                [
                    [np.logaddexp.reduce(log_joint) + np.log(hazard)],
                    log_joint + np.log(1.0 - hazard),
                ]
            )
            next_run_length -= np.logaddexp.reduce(next_run_length)
            log_run_length = next_run_length
            mode_rl.append(int(np.argmax(np.exp(log_run_length))))

            kappa_new = kappa_arr + 1.0
            mu_new = (kappa_arr * mu_arr + x) / kappa_new
            alpha_new = alpha_arr + 0.5
            beta_new = beta_arr + kappa_arr * (x - mu_arr) ** 2 / (2.0 * kappa_new)

            mu_arr = np.concatenate([[mu0], mu_new])
            kappa_arr = np.concatenate([[kappa0], kappa_new])
            alpha_arr = np.concatenate([[alpha0], alpha_new])
            beta_arr = np.concatenate([[beta0], beta_new])

        mode_rl = np.array(mode_rl, dtype=int)
        return np.concatenate([[mode_rl[0]], mode_rl])

    def detect_changepoints(self, close_series):
        close = np.asarray(close_series, dtype=float)
        if len(close) < 30:
            return np.array([], dtype=int)

        mode_rl = self._bocpd(self._build_signal(close))
        if len(mode_rl) < 2:
            return np.array([], dtype=int)

        drops = np.where(np.diff(mode_rl) < -self.drop_thresh)[0] + 1
        changepoints = []
        last_cp = -self.min_gap
        for cp in drops:
            if cp - last_cp >= self.min_gap:
                changepoints.append(int(cp))
                last_cp = cp

        return np.array(changepoints, dtype=int)
