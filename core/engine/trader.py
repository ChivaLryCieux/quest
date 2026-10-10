import json
import logging
import time

from core.config.settings import Config
from core.errors import OrderError
from core.models.position import Position
from core.risk.position_sizer import PositionSizer

logger = logging.getLogger(__name__)


class TradeExecutor:
    """负责具体的交易执行、持仓管理和止盈止损逻辑。"""

    BREAKEVEN_ACTIVATE = 0.002
    TRAIL_ACTIVATE = 0.004
    TRAIL_LOCK_RATIO = 0.50

    def __init__(self, exchange_service, risk_manager, ui_manager, brain):
        self.exchange = exchange_service
        self.risk = risk_manager
        self.ui = ui_manager
        self.brain = brain

        self.redis_client = None
        self.web_state = None
        self.balance = Config.PAPER_BALANCE
        self.position = self._empty_position()
        self.position_sizer = PositionSizer()

        self.profit_flip_count = 0
        self.was_in_profit = False
        self.max_pnl_pct = 0.0
        self.trade_snapshots = []
        self.last_snapshot_time = 0
        self.last_traded_candle_timestamp = 0
        self.ENTRY_WINDOW_SECONDS = 45

    def set_redis_client(self, client):
        self.redis_client = client

    def set_web_state(self, web_state):
        self.web_state = web_state

    def update_balance(self, new_balance):
        self.balance = new_balance

    @staticmethod
    def _empty_position():
        return Position(leverage=Config.DEFAULT_LEVERAGE)

    @property
    def position_dict(self):
        """兼容旧调用方：把 Position 以 dict 形式暴露。"""
        if isinstance(self.position, Position):
            return self.position.to_dict()
        return self.position

    def tick(self, curr_price, funding_rate, analysis_data, timestamp):
        self._record_trade_snapshot(curr_price)

        if not self.position.is_flat:
            self._manage_position(curr_price, funding_rate)

        self._check_entry(analysis_data, curr_price, funding_rate, timestamp)

    def _record_trade_snapshot(self, curr_price):
        if not (Config.ENABLE_MAIL_REPORT and not self.position.is_flat):
            return

        now = time.time()
        if now - self.last_snapshot_time < 15:
            return

        pnl = self.position.unrealized_pnl(curr_price)
        self.trade_snapshots.append({
            "time": now,
            "price": curr_price,
            "pnl": pnl,
            "regime": self.brain.state,
        })
        self.last_snapshot_time = now

    def _manage_position(self, curr_price, funding_rate):
        pos = self.position
        raw_pnl_pct = self._calculate_raw_pnl_pct(curr_price)

        if raw_pnl_pct > self.max_pnl_pct:
            self.max_pnl_pct = raw_pnl_pct

        self._apply_breakeven(pos)
        self._apply_trailing_stop(pos)

        analysis = self.brain.analyze()
        atr = analysis.get('atr', 0.0) if analysis else 0.0

        reversal_factor = analysis.get('reversal_factor', 0.0) if analysis else 0.0

        should_exit, reason = self.risk.check_exit_conditions(
            pos,
            curr_price,
            time.time() * 1000,
            self.profit_flip_count,
            atr,
            self.balance,
            reversal_factor,
        )
        if should_exit:
            self.execute_exit(reason, curr_price, funding_rate)

    def _apply_breakeven(self, pos):
        if self.max_pnl_pct < self.BREAKEVEN_ACTIVATE:
            return

        if pos.is_long and pos.sl < pos.entry_price:
            pos.sl = pos.entry_price
            logger.info(f"🛡️ 保本锁定 | Peak={self.max_pnl_pct*100:.2f}% → SL=入场价")
        elif pos.direction == -1 and pos.sl > pos.entry_price:
            pos.sl = pos.entry_price
            logger.info(f"🛡️ 保本锁定 | Peak={self.max_pnl_pct*100:.2f}% → SL=入场价")

    def _apply_trailing_stop(self, pos):
        if self.max_pnl_pct < self.TRAIL_ACTIVATE:
            return

        locked_pnl = self.max_pnl_pct * self.TRAIL_LOCK_RATIO
        trail_sl_price = (
            pos.entry_price * (1 + locked_pnl)
            if pos.is_long
            else pos.entry_price * (1 - locked_pnl)
        )

        if pos.is_long and trail_sl_price > pos.sl:
            old_sl = pos.sl
            pos.sl = trail_sl_price
            if old_sl <= pos.entry_price:
                logger.info(f"🔒 追踪止损激活 | Peak={self.max_pnl_pct*100:.2f}% → SL锁定+{locked_pnl*100:.2f}%")
        elif pos.direction == -1 and trail_sl_price < pos.sl:
            old_sl = pos.sl
            pos.sl = trail_sl_price
            if old_sl >= pos.entry_price:
                logger.info(f"🔒 追踪止损激活 | Peak={self.max_pnl_pct*100:.2f}% → SL锁定+{locked_pnl*100:.2f}%")

    def _check_entry(self, analysis, curr_price, funding_rate, timestamp):
        if not analysis:
            return
        if not self.position.is_flat:
            return
        if self.risk.is_in_cooldown():
            return
        if self.last_traded_candle_timestamp == timestamp:
            return

        time_since_open = (time.time() * 1000) - timestamp
        if time_since_open >= (self.ENTRY_WINDOW_SECONDS * 1000):
            return

        self._attempt_entry(analysis, curr_price, funding_rate, timestamp)

    def _attempt_entry(self, data, price, funding_rate, timestamp):
        sig, lev = self.brain.get_entry_signal(data, price)
        regime = self.brain.state

        if sig == 0:
            return

        is_risky, fr_msg = self.risk.check_funding_rate_risk(sig, funding_rate)
        if is_risky:
            self.ui.log_msg(f"跳过交易: {fr_msg}", "warning")
            return

        amount = self._calculate_order_amount(price, lev, analysis_data=data, signal_strength=1.0)
        if amount <= 0:
            return

        side = 'buy' if sig == 1 else 'sell'
        try:
            self.exchange.execute_order(side, amount)
        except OrderError as exc:
            self.ui.log_msg(f"开仓下单失败: {exc}", "error")
            logger.error("Entry order failed: %s", exc)
            return
        except Exception as exc:
            # 兼容 Dummy/旧 exchange（如测试替身）抛出的非 OrderError
            self.ui.log_msg(f"开仓下单失败: {exc}", "error")
            logger.error("Entry order failed: %s", exc)
            return

        self.last_traded_candle_timestamp = timestamp
        self.position = self._build_position(sig, amount, price, data, lev)

        self.ui.log_entry(
            regime,
            self.brain.color,
            sig,
            lev,
            price,
            self.position.sl,
            self.position.tp,
            macd=data.get('macd_histogram', 0.0),
            bb_mid=data.get('bb_middle', 0.0),
            st_val=data.get('supertrend_value', 0.0),
        )

        # 更新 Web 状态
        if self.web_state:
            side_str = "LONG" if sig == 1 else "SHORT"
            self.web_state.log_entry(
                side=side_str,
                price=price,
                leverage=lev,
                sl=self.position.sl,
                tp=self.position.tp,
                regime=regime,
            )

        self.profit_flip_count, self.was_in_profit = 0, False
        self.max_pnl_pct = 0.0

    def _calculate_order_amount(self, price, leverage, analysis_data=None, signal_strength=1.0):
        """计算下单数量 - 使用Kelly Criterion + 动态仓位"""
        atr = float(analysis_data.get('atr', 0.0)) if analysis_data else 0.0

        # 使用PositionSizer计算最优仓位
        amount, lev, info = self.position_sizer.get_position_size(
            price=price,
            atr=atr,
            signal_strength=signal_strength,
            balance=self.balance,
            fee_rate=Config.TAKER_FEE_RATE,
        )

        if info.get('trade_count', 0) >= 20:
            logger.info(
                f"📊 仓位决策 | Kelly={info['kelly_alloc']:.1%} "
                f"DD缩放={info['dd_scale']:.2f} 信号加权={info['signal_scale']:.2f} "
                f"→ 仓位={info['final_alloc']:.1%} 杠杆={info['leverage']:.1f}x "
                f"胜率={info['win_rate']:.1%} 盈亏比={info['avg_rr_ratio']:.2f}"
            )

        return self.exchange.get_precision_amount(amount, price)

    def _build_position(self, signal, amount, price, analysis_data, leverage):
        atr = float(analysis_data.get('atr', 0.0)) if analysis_data else 0.0
        reversal = float(analysis_data.get('reversal_factor', 0.0)) if analysis_data else 0.0

        atr_scale = min(1.4, max(0.85, 1.0 + atr * 18.0))
        rev_scale = min(1.25, max(0.9, 1.0 + abs(reversal) * 0.2))
        sl_dist = price * Config.MAX_SL_DISTANCE * atr_scale
        tp_dist = price * Config.MIN_TP_DISTANCE * atr_scale * rev_scale
        is_long = signal == 1

        return Position(
            size=amount if is_long else -amount,
            entry_price=price,
            entry_time=int(time.time() * 1000),
            sl=price - sl_dist if is_long else price + sl_dist,
            tp=price + tp_dist if is_long else price - tp_dist,
            leverage=leverage,
        )

    def _calculate_raw_pnl_pct(self, curr_price):
        return self.position.raw_pnl_pct(curr_price)

    def execute_exit(self, reason, price, funding_rate=0.0):
        pos = self.position
        if pos.is_flat:
            return

        pos_size = pos.size
        side = 'sell' if pos_size > 0 else 'buy'
        try:
            self.exchange.execute_order(side, abs(pos_size), params={'reduceOnly': True})
        except OrderError as exc:
            # 平仓失败必须保留持仓，不能记账！
            self.ui.log_msg(f"平仓下单失败，持仓保留: {exc}", "error")
            logger.error("Exit order failed, position kept: %s", exc)
            return
        except Exception as exc:
            self.ui.log_msg(f"平仓下单失败，持仓保留: {exc}", "error")
            logger.error("Exit order failed, position kept: %s", exc)
            return

        entry = pos.entry_price
        raw_pnl = (price - entry) * pos_size
        fee = abs(pos_size) * (entry + price) * Config.TAKER_FEE_RATE
        net_pnl = raw_pnl - fee

        self.balance += net_pnl
        self.max_pnl_pct = 0.0
        margin_used = pos.margin_used(Config.DEFAULT_LEVERAGE)
        _, cd_msg = self.risk.activate_circuit_breaker(net_pnl, margin_used)

        # 更新PositionSizer
        duration_min = (time.time() * 1000 - pos.entry_time) / 60000.0
        self.position_sizer.record_trade(net_pnl, duration_min)
        self.position_sizer.update_equity(self.balance)

        self.ui.log_exit(reason, price, net_pnl, fee, self.balance, cd_msg)
        self._report_trade_exit(pos_size, entry, price, net_pnl, fee, reason)

        # 更新 Web 状态
        if self.web_state:
            self.web_state.log_exit(
                reason=reason,
                price=price,
                pnl=net_pnl,
                fee=fee,
                balance=self.balance,
            )

        self.trade_snapshots = []
        self.last_snapshot_time = 0
        self.position = self._empty_position()

    def _report_trade_exit(self, pos_size, entry, price, net_pnl, fee, reason):
        if not (Config.ENABLE_MAIL_REPORT and self.redis_client):
            return

        try:
            pos = self.position if isinstance(self.position, Position) else Position.from_dict(self.position)
            trade_record = {
                "entry_time": pos.entry_time,
                "exit_time": int(time.time() * 1000),
                "mode": "Live" if self.exchange.is_live else "Paper",
                "action": "做多" if pos_size > 0 else "做空",
                "entry_price": entry,
                "exit_price": price,
                "amount": abs(pos_size),
                "leverage": pos.leverage,
                "pnl": net_pnl,
                "fee": fee,
                "balance": self.balance,
                "regime": self.brain.state,
                "reason": reason,
                "cluster": pos.cluster,
                "snapshots": self.trade_snapshots,
            }
            self.redis_client.rpush('trade_journal_pending', json.dumps(trade_record))
        except Exception as exc:
            logger.error(f"[Report] Redis Error: {exc}")
