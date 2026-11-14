import logging
from datetime import datetime

from core.analysis.bocpd import IncrementalBOCPD
from core.utils.mailer import MailService

logger = logging.getLogger(__name__)


class AlertManager:
    KDJ_J_OVERBOUGHT = 100
    KDJ_J_OVERSOLD = 0
    KDJ_ADX_FILTER = 25
    ADX_ALERT_THRESHOLD = 75
    MACD_CROSS_ADX_FILTER = 35

    def __init__(self):
        self.mail_service = MailService()
        self.bocpd = IncrementalBOCPD()
        self._bocpd_fed_ts = None
        self.web_state = None
        self.last_bocpd_cp = None
        self.last_kdj_state = None
        self.adx_alert_active = False
        self.last_macd_cross_state = None

    def set_web_state(self, web_state):
        self.web_state = web_state

    @staticmethod
    def _last_fields(ring_5m):
        """从 CandleRing 取最后一根（成形中）蜡烛的 ts/close。"""
        last = ring_5m.last_row
        if last is None:
            return None, 0.0
        return int(last[0]), float(last[4])

    def check_and_alert(self, ring_5m, analysis):
        if ring_5m is None or len(ring_5m) == 0 or analysis is None:
            return

        self._check_bocpd_alert(ring_5m)
        self._check_kdj_j_alert(ring_5m, analysis)
        self._check_macd_cross_alert(ring_5m, analysis)
        self._check_adx_alert(ring_5m, analysis)

    def _check_macd_cross_alert(self, history_5m, analysis):
        adx = float(analysis.get('adx', 0.0))
        macd_golden_cross = bool(analysis.get('macd_golden_cross', False))
        macd_death_cross = bool(analysis.get('macd_death_cross', False))
        macd_above_zero = bool(analysis.get('macd_above_zero', False))
        macd = float(analysis.get('macd', 0.0))
        macd_signal = float(analysis.get('macd_signal', 0.0))

        if adx <= self.MACD_CROSS_ADX_FILTER:
            self.last_macd_cross_state = None
            return

        state = None
        label = None
        icon = None

        if macd_golden_cross and macd_above_zero:
            state = 'golden_above_zero'
            label = '水上金叉'
            icon = '🟢'
        elif macd_death_cross and not macd_above_zero:
            state = 'death_below_zero'
            label = '水下死叉'
            icon = '🔴'

        if state is None:
            self.last_macd_cross_state = None
            return

        if self.last_macd_cross_state == state:
            return

        last_ts, price = self._last_fields(history_5m)
        ts = datetime.fromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M:%S')

        subject = f"{icon} MACD交叉预警 | {label} | ADX {adx:.2f} > {self.MACD_CROSS_ADX_FILTER}"
        html = (
            f"<h3>MACD交叉触发预警</h3>"
            f"<p><b>状态:</b> {label}</p>"
            f"<p><b>MACD:</b> {macd:.6f}</p>"
            f"<p><b>Signal:</b> {macd_signal:.6f}</p>"
            f"<p><b>ADX:</b> {adx:.2f}</p>"
            f"<p><b>触发条件:</b> ADX>{self.MACD_CROSS_ADX_FILTER} 且出现{label}</p>"
            f"<p><b>时间:</b> {ts}</p>"
            f"<p><b>价格:</b> {price:.4f}</p>"
        )
        self.mail_service.send_alert(subject, html)

        # 更新 Web 状态
        if self.web_state:
            self.web_state.add_alert(
                alert_type="MACD",
                message=f"MACD交叉预警 | {label} | ADX={adx:.2f}",
                details={"state": state, "label": label, "macd": macd, "macd_signal": macd_signal, "adx": adx, "time": ts, "price": price},
            )

        self.last_macd_cross_state = state
        logger.warning("MACD cross alert triggered: state=%s, adx=%.2f", state, adx)

    def _check_bocpd_alert(self, ring_5m):
        # 增量喂入已收盘蜡烛（排除最后一根成形中蜡烛），按 ts 去重
        arr = ring_5m.array()
        cp_index = None
        cp_row = None
        for row in arr[:-1]:
            ts = row[0]
            if self._bocpd_fed_ts is not None and ts <= self._bocpd_fed_ts:
                continue
            self._bocpd_fed_ts = ts
            if self.bocpd.update(float(row[4])) is not None:
                cp_index = self.bocpd.last_cp_index
                cp_row = row

        if cp_index is None:
            return
        if self.last_bocpd_cp is not None and cp_index <= self.last_bocpd_cp:
            return

        ts = datetime.fromtimestamp(int(cp_row[0]) / 1000).strftime('%Y-%m-%d %H:%M:%S')
        price = float(cp_row[4])
        subject = f"🚨 BOCPD变点预警 | {ts}"
        html = (
            f"<h3>检测到BOCPD变点</h3>"
            f"<p><b>时间:</b> {ts}</p>"
            f"<p><b>价格:</b> {price:.4f}</p>"
            f"<p><b>变点索引:</b> {cp_index}</p>"
        )
        self.mail_service.send_alert(subject, html)

        # 更新 Web 状态
        if self.web_state:
            self.web_state.add_alert(
                alert_type="BOCPD",
                message=f"BOCPD变点预警 | 价格: {price:.4f}",
                details={"price": price, "index": cp_index, "time": ts},
            )

        self.last_bocpd_cp = cp_index
        logger.warning("BOCPD changepoint alert triggered at index=%s", cp_index)

    def _check_kdj_j_alert(self, history_5m, analysis):
        kdj_j = float(analysis.get('kdj_j', 50.0))
        adx = float(analysis.get('adx', 0.0))

        if adx <= self.KDJ_ADX_FILTER:
            self.last_kdj_state = None
            return

        if kdj_j >= self.KDJ_J_OVERBOUGHT:
            state = 'overbought'
            label = 'J值超买'
            icon = '🔴'
        elif kdj_j <= self.KDJ_J_OVERSOLD:
            state = 'oversold'
            label = 'J值超卖'
            icon = '🟢'
        else:
            self.last_kdj_state = None
            return

        if self.last_kdj_state == state:
            return

        last_ts, price = self._last_fields(history_5m)
        ts = datetime.fromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M:%S')

        subject = f"{icon} KDJ-J值预警 | {label} | ADX {adx:.2f} > {self.KDJ_ADX_FILTER}"
        html = (
            f"<h3>KDJ-J值触发预警</h3>"
            f"<p><b>状态:</b> {label}</p>"
            f"<p><b>J值:</b> {kdj_j:.2f}</p>"
            f"<p><b>ADX:</b> {adx:.2f}</p>"
            f"<p><b>触发条件:</b> ADX>{self.KDJ_ADX_FILTER} 且 J值触及极值</p>"
            f"<p><b>时间:</b> {ts}</p>"
            f"<p><b>价格:</b> {price:.4f}</p>"
        )
        self.mail_service.send_alert(subject, html)

        # 更新 Web 状态
        if self.web_state:
            self.web_state.add_alert(
                alert_type="KDJ",
                message=f"KDJ-J值预警 | {label} | J={kdj_j:.2f}",
                details={"j_value": kdj_j, "adx": adx, "state": state, "time": ts, "price": price},
            )

        self.last_kdj_state = state
        logger.warning("KDJ-J alert triggered: state=%s, j=%.2f, adx=%.2f", state, kdj_j, adx)

    def _check_adx_alert(self, history_5m, analysis):
        adx = float(analysis.get('adx', 0.0))

        if adx <= self.ADX_ALERT_THRESHOLD:
            self.adx_alert_active = False
            return

        if self.adx_alert_active:
            return

        last_ts, price = self._last_fields(history_5m)
        ts = datetime.fromtimestamp(last_ts / 1000).strftime('%Y-%m-%d %H:%M:%S')

        subject = "🟣 ADX强趋势预警 | ADX > 75"
        html = (
            f"<h3>ADX触发预警</h3>"
            f"<p><b>状态:</b> ADX超过75，趋势极强</p>"
            f"<p><b>ADX:</b> {adx:.2f}</p>"
            f"<p><b>时间:</b> {ts}</p>"
            f"<p><b>价格:</b> {price:.4f}</p>"
        )
        self.mail_service.send_alert(subject, html)

        # 更新 Web 状态
        if self.web_state:
            self.web_state.add_alert(
                alert_type="ADX",
                message=f"ADX强趋势预警 | ADX={adx:.2f} > 75",
                details={"adx": adx, "time": ts, "price": price},
            )

        self.adx_alert_active = True
        logger.warning("ADX alert triggered: adx=%.2f", adx)
