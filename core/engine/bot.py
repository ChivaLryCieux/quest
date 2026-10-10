import concurrent.futures
import json
import logging
import sys
import threading
import time

import pandas as pd
import redis
from colorama import init

from core.config.exchange import ExchangeService
from core.config.settings import Config
from core.config.mode import TradingMode, can_switch, parse_mode
from core.engine.trader import TradeExecutor
from core.engine.alert_manager import AlertManager
from core.engine.state_store import StateStore
from core.models.position import Position
from core.risk.manager import RiskManager
from core.strategy.brain import StrategyBrain
from core.ui.display import DisplayManager
from core.ui.input import KeyListener
from core.utils.logging_config import setup_logging
from core.web.state import WebState
from core.web.runner import WebRunner

init(autoreset=True)

setup_logging(
    log_level=Config.LOG_LEVEL,
    log_dir=Config.LOG_DIR,
    log_file=Config.LOG_FILE,
    console_output=Config.LOG_TO_CONSOLE,
    max_bytes=Config.LOG_MAX_BYTES,
    backup_count=Config.LOG_BACKUP_COUNT,
)

logger = logging.getLogger(__name__)


class QuantBot:
    WARMUP_TIMEOUT_SECONDS = 30
    LOOP_SLEEP_SECONDS = 0.05

    def __init__(self):
        Config.setup_proxy()
        self.ui = DisplayManager()
        self.key_listener = KeyListener()

        # 默认进入看盘模式（不交易）；模式可由 WebUI 运行时切换
        self.trading_mode = TradingMode.DASHBOARD
        self.is_live = False
        self.mode_name = self.trading_mode.label
        self._mode_lock = threading.Lock()
        logger.info(f"Initial Mode: {self.mode_name} (运行时可在 WebUI 切换)")

        self._validate_runtime_config()

        self.exchange = ExchangeService(self.is_live)
        self.brain = StrategyBrain()
        self.risk = RiskManager()
        self.trader = TradeExecutor(self.exchange, self.risk, self.ui, self.brain)
        self.alert_manager = AlertManager()

        # 运行时状态持久化（余额 / 持仓 / Kelly 历史）
        self.state_store = StateStore(Config.STATE_DIR, Config.STATE_FILE)
        self._last_state_save = 0.0
        self._last_saved_balance = None
        self._restore_runtime_state()

        self.redis_client = self._init_redis()

        # Web GUI
        self.web_state = WebState()
        self.web_runner = None

        # 将 WebState 注入到 trader 和 alert_manager
        self.trader.set_web_state(self.web_state)
        self.alert_manager.set_web_state(self.web_state)

        self.current_candle_timestamp = 0
        self.last_tick_analysis = None
        self.last_tick_price = 0.0
        self.last_btc_price = 0.0
        self.exchange_connected = False
        self.bot_lock = threading.Lock()
        # 防止 WebUI 连点导致并发切换
        self._switch_lock = threading.Lock()

    def _validate_runtime_config(self):
        # 初始 DASHBOARD 模式不要求 API Key；切换到 LIVE 时由 switch_mode 校验
        issues = Config.validate_for_mode(is_live=self.is_live)
        if not issues:
            return

        for issue in issues:
            logger.error("Config validation failed: %s", issue)
        raise SystemExit("配置校验失败，请修正 .env 或 core/config/settings.py 后重试")

    def _restore_runtime_state(self):
        """启动时恢复余额 / 持仓 / Kelly 交易历史。"""
        data = self.state_store.load()
        if not data:
            return

        try:
            balance = float(data.get("balance", 0.0) or 0.0)
            if balance > 0:
                self.trader.update_balance(balance)

            pos_data = data.get("position") or {}
            if not Position.from_dict(pos_data).is_flat:
                self.trader.position = Position.from_dict(pos_data)
                logger.info(
                    "Restored open position: size=%s entry=%s",
                    self.trader.position.size,
                    self.trader.position.entry_price,
                )

            # 恢复 Kelly / 回撤状态
            sizer = self.trader.position_sizer
            for rec in data.get("trade_history", []):
                sizer.record_trade(float(rec.get("pnl", 0.0)), float(rec.get("duration_min", 0.0)))
            peak = float(data.get("peak_equity", 0.0) or 0.0)
            if peak > 0:
                sizer.peak_equity = peak
                sizer.current_equity = balance if balance > 0 else peak

            saved_at = data.get("saved_at")
            self._last_saved_balance = self.trader.balance
            logger.info("Runtime state restored (balance=%.2f, saved_at=%s)", balance, saved_at)
        except (TypeError, ValueError) as exc:
            logger.warning("Failed to restore runtime state, starting fresh: %s", exc)

    def _persist_runtime_state(self, force: bool = False) -> bool:
        """按间隔或强制写入状态（余额变化 = 交易完成时立即落盘）。"""
        now = time.time()
        balance = self.trader.balance
        # 余额变化说明发生了平仓，立即持久化，避免崩溃丢交易
        balance_changed = (
            self._last_saved_balance is not None
            and abs(balance - self._last_saved_balance) > 1e-9
        )
        if not force and not balance_changed:
            if (now - self._last_state_save) < Config.STATE_SAVE_INTERVAL_SEC:
                return False

        sizer = self.trader.position_sizer
        state = {
            "symbol": Config.SYMBOL,
            "mode": self.trading_mode.value,
            "balance": balance,
            "position": self.trader.position.to_dict(),
            "peak_equity": sizer.peak_equity,
            "current_equity": sizer.current_equity,
            "trade_history": [
                {"pnl": t.pnl, "duration_min": t.duration_min}
                for t in sizer.trade_history
            ],
        }
        ok = self.state_store.save(state)
        if ok:
            self._last_state_save = now
            self._last_saved_balance = balance
        return ok

    async def handle_control(self, request):
        """WebUI 控制命令路由（由 /api/control 调用）。

        锁策略：
        - switch_mode / switch_symbol 内部各自管理 bot_lock —— 网络
          预热必须在锁外执行，否则主循环会被几十秒的 IO 卡死；
        - exit / pause / resume 这类瞬时操作直接持锁执行。
        """
        action = request.action
        if action == "switch_mode":
            if not request.mode:
                raise ValueError("switch_mode 需要 mode 参数")
            return self.switch_mode(request.mode)
        if action == "switch_symbol":
            if not request.symbol:
                raise ValueError("switch_symbol 需要 symbol 参数")
            return self.switch_symbol(request.symbol)
        if action == "exit":
            with self.bot_lock:
                self._exit_procedure()
            return "Exiting..."
        if action in ("pause", "resume"):
            return f"Action {action} acknowledged (no-op)"
        raise ValueError(f"Unknown action: {action}")


    def switch_mode(self, target_mode_str):
        """切换交易模式（仅允许单向升级：DASHBOARD -> PAPER -> LIVE）

        切换到 LIVE 需校验 API Key；有持仓时禁止切换。
        成功返回 message 字符串；失败抛 ValueError（由 server.py 的 except 捕获）。
        """
        target = parse_mode(target_mode_str)

        with self._mode_lock:
            current = self.trading_mode

            # 1. 单向升级校验
            if not can_switch(current, target):
                msg = f"不允许降级或同级切换: {current.value} -> {target.value}"
                logger.warning(msg)
                raise ValueError(msg)

            # 2. 无持仓校验
            if not self.trader.position.is_flat:
                msg = f"当前有持仓，禁止切换模式 (size={self.trader.position.size})"
                logger.warning(msg)
                raise ValueError(msg)

            # 3. LIVE 模式校验 API Key
            if target == TradingMode.LIVE:
                issues = Config.validate_for_mode(is_live=True)
                if issues:
                    msg = f"实盘模式校验失败: {'; '.join(issues)}"
                    logger.error(msg)
                    raise ValueError(msg)

            # 4. 锁外：创建并连接新的 ExchangeService（网络 IO）
            #    连接期间主循环继续用旧 exchange 正常交易，不被卡住
            new_is_live = (target == TradingMode.LIVE)
            new_exchange = ExchangeService(new_is_live)
            self.ui.log_msg(f"正在切换到 {target.label} 模式...", "info")

            ok, err_msg = new_exchange.connect()
            if not ok:
                new_exchange.close()
                msg = f"切换失败: 交易所重连失败 ({err_msg})"
                logger.error(msg)
                raise ValueError(msg)

            # 锁外取余额（走新 exchange 自己的 api_lock，与主循环无竞争）
            balance_info = new_exchange.fetch_balance()

            # 5. 锁内：原子交换共享状态
            with self.bot_lock:
                if not self.trader.position.is_flat:
                    # 极小概率：连接期间产生了持仓，放弃切换
                    new_exchange.close()
                    msg = f"当前有持仓，禁止切换模式 (size={self.trader.position.size})"
                    logger.warning(msg)
                    raise ValueError(msg)

                old_exchange = self.exchange
                self.exchange = new_exchange
                self.trader.exchange = new_exchange
                self.is_live = new_is_live
                self.trading_mode = target
                self.mode_name = target.label

                if balance_info:
                    self.trader.update_balance(balance_info['total'])

            # 锁外关闭旧连接
            old_exchange.close()

            # 6. 更新 Web 状态
            self.web_state.set_trading_mode(target.value)
            self.web_state.update_account(
                balance=self.trader.balance,
                mode=target.value.capitalize(),
                symbol=Config.SYMBOL,
            )

            if balance_info:
                self.ui.log_msg(
                    f"{target.label} Balance: Free ${balance_info['free']:.2f} | "
                    f"Total ${balance_info['total']:.2f}",
                    "success",
                )

            self.ui.log_msg(f"✅ 已切换到 {target.label} 模式", "success")
            logger.info(f"Trading mode switched: {current.value} -> {target.value}")
            return f"已切换到 {target.label} 模式"

    def switch_symbol(self, target_symbol: str):
        """切换交易/看盘标的。

        两阶段设计：
        - 阶段 1（不持 bot_lock）：历史拉取 + 独立 brain 预热，
          主循环继续用旧标的正常跑，不被几十秒的 IO 卡死；
        - 阶段 2（持 bot_lock）：原子交换 brain/exchange/tick 缓存。
        """
        new_symbol = Config.normalize_symbol(target_symbol)

        if new_symbol == self.exchange.symbol:
            return f"Already on {new_symbol}"

        if not self._switch_lock.acquire(blocking=False):
            raise ValueError("已有切换任务进行中，请稍候")

        try:
            logger.info(f"Switching trading/watching symbol to {new_symbol}...")
            self.ui.log_msg(f"Switching symbol to {new_symbol}...", "info")
            self.web_state.set_status("switching")

            # ---------- 阶段 1：锁外预热（历史拉取 + 独立 brain） ----------
            new_brain, analysis, last_ts = self._build_warmup_brain(new_symbol)

            # ---------- 阶段 2：锁内原子交换 ----------
            with self.bot_lock:
                Config.set_symbol(new_symbol)
                self.exchange.apply_symbol(new_symbol)
                self.brain = new_brain
                self.trader.brain = new_brain
                self.last_tick_analysis = analysis
                self.last_tick_price = 0.0
                self.last_btc_price = 0.0
                if last_ts:
                    self.current_candle_timestamp = last_ts

            self._push_warmup_market(new_brain, analysis)
            self.web_state.update_account(
                balance=self.trader.balance,
                mode=self.trading_mode.value.capitalize(),
                symbol=new_symbol,
            )
            self.web_state.set_status("running")

            self.ui.log_msg(f"✅ Symbol switched to {new_symbol}", "success")
            return f"Successfully switched to {new_symbol}"
        except Exception as exc:
            self.web_state.set_status("running")
            logger.exception("switch_symbol failed")
            raise ValueError(f"切换标的异常: {exc}") from exc
        finally:
            self._switch_lock.release()

    def _init_redis(self):
        if not Config.ENABLE_MAIL_REPORT:
            return None

        try:
            client = redis.Redis(**Config.redis_kwargs())
            client.ping()
            logger.info("Report Service Connected")
            self.trader.set_redis_client(client)
            return client
        except Exception as exc:
            logger.error(f"Report Service Connection Failed: {exc}")
            return None

    def run(self):
        self.ui.log_startup()

        # 1. 先启动 Web 服务器（无论交易所连接是否成功）
        self._start_web_server()

        # 2. 尝试连接交易所
        ok, msg = self.exchange.connect()
        if not ok:
            self.ui.log_msg(f"Connection Failed: {msg}", "error")
            self.web_state.set_status("exchange_error")
            self.web_state.update_system(
                exchange_connected=False,
                error_message=msg,
            )
            self.ui.log_msg("Web GUI is still running. Press 'q' to exit.", "warning")

            # 即使交易所连接失败，也进入主循环（保持 Web GUI 运行）
            self._run_idle_loop()
            return

        # 交易所连接成功
        self.exchange_connected = True
        self.ui.log_msg("Exchange Connected", "success")
        self.web_state.update_system(exchange_connected=True)

        self._fetch_balance()
        self._warmup_models()

        self.ui.log_msg("System Started, Listening...", "success")
        self.web_state.set_status("running")

        # 正常主循环
        self._run_main_loop()

    def _run_idle_loop(self):
        """交易所连接失败时的空闲循环，保持 Web GUI 运行"""
        while True:
            try:
                self._check_user_input()
                time.sleep(0.5)  # 降低 CPU 占用
            except KeyboardInterrupt:
                self._exit_procedure()
            except Exception as exc:
                logger.error(f"Idle Loop Error: {exc}")
                time.sleep(1)

    def _run_main_loop(self):
        """正常交易主循环"""
        while True:
            try:
                self._check_user_input()
                self._tick()
                self._persist_runtime_state()  # 内部按 STATE_SAVE_INTERVAL_SEC 节流
                time.sleep(self.LOOP_SLEEP_SECONDS)
            except KeyboardInterrupt:
                self._exit_procedure()
            except Exception as exc:
                logger.error(f"Loop Error: {exc}")
                time.sleep(1)

    def _start_web_server(self):
        """启动 Web 服务器"""
        if not Config.WEB_ENABLED:
            self.ui.log_msg("Web GUI disabled", "info")
            return

        try:
            self.web_runner = WebRunner(
                state=self.web_state,
                host=Config.WEB_HOST,
                port=Config.WEB_PORT,
                auto_open=Config.WEB_AUTO_OPEN,
                control_callback=self.handle_control,
            )
            self.web_runner.start()

            url = self.web_runner.get_url()
            self.ui.log_msg(f"Web GUI: {url}", "success")

            # 初始化 Web 状态
            self.web_state.update_account(
                balance=self.trader.balance,
                mode=self.trading_mode.value.capitalize(),
                symbol=Config.SYMBOL,
            )
            self.web_state.set_status("initializing")
            self.web_state.set_ws_connected(True)
            self.web_state.set_trading_mode(self.trading_mode.value)

        except Exception as exc:
            logger.error(f"Web server start failed: {exc}")
            self.ui.log_msg(f"Web GUI failed: {exc}", "error")

    def _fetch_balance(self):
        try:
            info = self.exchange.fetch_balance()
            if not info:
                self.ui.log_msg("Failed to fetch balance", "error")
                return

            mode_label = self.trading_mode.label
            self.ui.log_msg(
                f"{mode_label} Balance: Free ${info['free']:.2f} | Total ${info['total']:.2f}",
                "success",
            )
            self.trader.update_balance(info['total'])
        except Exception as exc:
            self.ui.log_msg(f"Fetch Balance Failed: {exc}", "error")

    def _warmup_models(self):
        self.ui.log_msg("Warming up models...", "info")
        try:
            brain, analysis, last_ts = self._build_warmup_brain(Config.SYMBOL)
            self.brain = brain
            self.trader.brain = brain
            # 立即存入初始分析，防止首个5m周期内指标显示 0.0
            self.last_tick_analysis = analysis
            if last_ts:
                self.current_candle_timestamp = last_ts
            self._push_warmup_market(brain, analysis)
        except Exception as exc:
            self.ui.log_msg(f"❌ Warmup Error: {exc}", "error")
            logger.exception("Warmup traceback")

    def _fetch_warmup_data(self, symbol=None):
        self.ui.log_msg("Fetching historical data from exchange...", "info")

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(self.exchange.fetch_initial_history, 100, symbol)
            try:
                return future.result(timeout=self.WARMUP_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                self.ui.log_msg(
                    f"⚠️ Warmup timeout ({self.WARMUP_TIMEOUT_SECONDS}s). Continuing with empty data...",
                    "warning",
                )
                return {'5m': [], '15m': [], '1h': [], '1d': []}

    def _build_warmup_brain(self, symbol):
        """锁外：为指定标的构建预热完成的新 StrategyBrain。

        返回 (brain, analysis, last_ts)；历史全空时返回 (空 brain, None, 0)。
        """
        data = self._fetch_warmup_data(symbol=symbol)
        candles_5m = data.get('5m', [])
        candles_15m = data.get('15m', [])
        candles_1h = data.get('1h', [])
        candles_1d = data.get('1d', [])

        new_brain = StrategyBrain()
        if not (candles_5m and candles_15m and candles_1h):
            self.ui.log_msg("⚠️ Warmup Data Empty - Starting with minimal state", "warning")
            return new_brain, None, 0

        self._ingest_warmup_candles(candles_5m, '5m', step=20, brain=new_brain)
        self._ingest_warmup_candles(candles_15m, '15m', step=10, brain=new_brain)
        self._ingest_warmup_candles(candles_1h, '1h', step=5, brain=new_brain)
        self._ingest_warmup_candles(candles_1d, '1d', step=1, brain=new_brain)
        self.ui.log_msg("✅ Warmup Complete", "success")

        initial_book = self.exchange._cached_latest.get('orderbook') if hasattr(self.exchange, '_cached_latest') else None
        return new_brain, new_brain.analyze(initial_book), candles_5m[-1][0]

    def _push_warmup_market(self, brain, analysis):
        """切换后把新标的 K 线推给 Web（不依赖 self.brain）。"""
        if not Config.WEB_ENABLED:
            return
        history_list = brain.history_5m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        history_15m = brain.history_15m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        history_1h = brain.history_1h[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        history_1d = brain.history_1d[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()

        self.web_state.update_market(
            kline_5m=history_list,
            kline_15m=history_15m,
            kline_1h=history_1h,
            kline_1d=history_1d
        )

    def _ingest_warmup_candles(self, candles, timeframe, step, brain=None):
        target = brain if brain is not None else self.brain
        self.ui.log_msg(f"Processing {len(candles)} {timeframe} candles...", "info")
        for index, candle in enumerate(candles, start=1):
            target.ingest_candle(candle, timeframe)
            if index % step == 0:
                self.ui.log_msg(f"  Processed {index}/{len(candles)} {timeframe} candles", "info")

    def _tick(self):
        with self.bot_lock:
            c_5m, c_15m, c_1h, book, fr, btc_price = self.exchange.get_latest_data()
            if not c_5m:
                return

            # 更新 Web 盘口五档挂单数据
            if book and Config.WEB_ENABLED:
                self.web_state.update_orderbook(book)

            timestamp = c_5m[0]
            curr_price = float(c_5m[4])
            self.last_tick_price = curr_price

            btc_chg = self._calculate_btc_change(btc_price)

            if not self.trader.position.is_flat:
                self.trader.tick(curr_price, fr, None, timestamp)

            if self.current_candle_timestamp == 0:
                self.current_candle_timestamp = timestamp
                self._ingest_realtime_candles(c_5m, c_15m, c_1h, btc_chg)
                if Config.WEB_ENABLED:
                    history_list = self.brain.history_5m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                    history_15m = self.brain.history_15m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                    history_1h = self.brain.history_1h[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                    self.web_state.update_market(
                        kline_5m=history_list,
                        kline_15m=history_15m,
                        kline_1h=history_1h
                    )
                return

            is_new_candle = timestamp > self.current_candle_timestamp
            if not is_new_candle:
                self._update_ui(curr_price, self.last_tick_analysis)
                return

            logger.info(f"[Candle Close] {self.current_candle_timestamp} -> {timestamp}")
            self.current_candle_timestamp = timestamp
            self._ingest_realtime_candles(c_5m, c_15m, c_1h, btc_chg)
            if Config.WEB_ENABLED:
                history_list = self.brain.history_5m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                history_15m = self.brain.history_15m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                history_1h = self.brain.history_1h[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
                self.web_state.update_market(
                    kline_5m=history_list,
                    kline_15m=history_15m,
                    kline_1h=history_1h
                )

            analysis = self.brain.analyze(book)
            # 仅在非看盘模式下尝试开仓；持仓管理（上方）对遗留持仓仍生效
            if (self.trading_mode != TradingMode.DASHBOARD
                    and self.trader.position.is_flat
                    and analysis):
                self.trader.tick(curr_price, fr, analysis, timestamp)

            self._update_ui(curr_price, analysis)
            self.alert_manager.check_and_alert(self.brain.history_5m, analysis)
            self._send_heartbeat(curr_price, analysis)
            if analysis:
                self.last_tick_analysis = analysis

    def _calculate_btc_change(self, btc_price):
        if self.last_btc_price == 0:
            self.last_btc_price = btc_price
            return 0.0

        btc_change = (btc_price - self.last_btc_price) / self.last_btc_price if self.last_btc_price > 0 else 0.0
        self.last_btc_price = btc_price
        return btc_change

    def _ingest_realtime_candles(self, c_5m, c_15m, c_1h, btc_chg):
        if c_15m:
            self.brain.ingest_candle(c_15m, '15m', btc_change_pct=btc_chg)
        if c_1h:
            self.brain.ingest_candle(c_1h, '1h', btc_change_pct=btc_chg)
        self.brain.ingest_candle(c_5m, '5m', btc_change_pct=btc_chg)

    def _update_ui(self, price, analysis):
        pos = self.trader.position
        unrealized = pos.unrealized_pnl(price)

        # 更新 Web 状态 (无论是否有策略分析结果，价格和余额都需要实时更新)
        self._update_web_state(price, analysis, unrealized)

        if not analysis:
            return

        self.ui.update_status(
            pos.size,
            self.brain.state,
            self.brain.color,
            unrealized,
            price,
            macd=analysis.get('macd_histogram', 0.0),
            adx=analysis.get('adx', 0.0),
            reversal=analysis.get('reversal_factor', 0.0),
        )

    def _update_web_state(self, price, analysis, unrealized_pnl):
        """更新 Web 共享状态"""
        if not Config.WEB_ENABLED:
            return

        # 更新价格
        self.web_state.update_price(price)

        # 确保 analysis 至少是个字典，防止 None.get() 报错
        analysis_data = analysis or {}

        # 更新策略状态
        self.web_state.update_strategy(
            state=self.brain.state,
            color=self.brain.color,
            adx=analysis_data.get('adx', 0.0),
            macd=analysis_data.get('macd_histogram', 0.0),
            reversal=analysis_data.get('reversal_factor', 0.0),
            supertrend_5m=analysis_data.get('supertrend_direction', 0),
            supertrend_15m=self.brain.signal_engine.supertrend_15m_direction,
            supertrend_1h=self.brain.signal_engine.supertrend_1h_direction,
        )

        # 更新持仓
        self.web_state.update_position(self.trader.position, unrealized_pnl)

        # 更新余额
        self.web_state.update_balance(self.trader.balance)

    def _send_heartbeat(self, price, analysis):
        if not (Config.ENABLE_MAIL_REPORT and self.redis_client):
            return

        try:
            change_24h = self._calculate_change_24h(price)
            data = {
                "timestamp": int(time.time() * 1000),
                "balance": self.trader.balance,
                "position_size": self.trader.position.size,
                "price": price,
                "regime": self.brain.state,
                "change_24h": round(change_24h, 2),
            }
            self.redis_client.set('bot_status_heartbeat', json.dumps(data), ex=10)
        except Exception:
            pass

    def _calculate_change_24h(self, price):
        hist = self.brain.history_5m
        if len(hist) >= 288:
            price_24h_ago = float(hist.iloc[-288]['close'])
            return (price - price_24h_ago) / price_24h_ago * 100
        if len(hist) > 1:
            price_first = float(hist.iloc[0]['close'])
            return (price - price_first) / price_first * 100
        return 0.0

    def _check_user_input(self):
        if self.key_listener.is_q_pressed():
            logger.warning("=== PAUSED === [0] Exit | [Enter] Continue")
            command = self.key_listener.safe_input("Cmd > ").strip()
            if command == '0':
                self._exit_procedure()

    def _exit_procedure(self):
        logger.info("Stopping...")
        self.web_state.set_status("stopping")

        # 停止 Web 服务器
        if self.web_runner:
            self.web_runner.stop()

        self.exchange.close()

        if not self.trader.position.is_flat:
            price = self.last_tick_price if self.last_tick_price > 0 else self.trader.position.entry_price
            self.trader.execute_exit("Manual Exit", price)

        # 退出前强制落盘，保证余额与交易历史不丢
        self._persist_runtime_state(force=True)

        sys.exit(0)
