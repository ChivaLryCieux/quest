"""标的与交易模式热切换控制器 (Symbol & Mode Switchers)

设计核心原则：
1. 阶段 1（网络 I/O 与历史预热）：必须在主循环锁（bot_lock）外部执行，杜绝卡死主交易 Tick；
2. 阶段 2（状态原子替换）：在 bot_lock 保护下瞬间完成数据结构替换；
3. 锁协议安全性：使用独立 switch_lock 互斥并发的 WebUI 切换请求。
"""

import concurrent.futures
import logging
import threading

from core.config.mode import TradingMode, can_switch, parse_mode
from core.config.settings import Config
from core.gateway.service import ExchangeService
from core.strategy.brain import StrategyBrain

logger = logging.getLogger(__name__)


class WarmupCoordinator:
    """负责跨多周期的历史 K 线数据拉取与策略大脑 (StrategyBrain) 预热。"""

    WARMUP_TIMEOUT_SECONDS = 30

    @classmethod
    def fetch_warmup_data(cls, exchange: ExchangeService, ui_manager, symbol=None):
        ui_manager.log_msg("Fetching historical data from exchange...", "info")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(exchange.fetch_initial_history, 100, symbol)
            try:
                return future.result(timeout=cls.WARMUP_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                ui_manager.log_msg(
                    f"⚠️ Warmup timeout ({cls.WARMUP_TIMEOUT_SECONDS}s). Continuing with empty data...",
                    "warning",
                )
                return {'5m': [], '15m': [], '1h': [], '1d': []}

    @classmethod
    def build_warmup_brain(cls, exchange: ExchangeService, ui_manager, symbol: str):
        """为指定标的构建预热完成的新 StrategyBrain。

        返回 (brain, analysis, last_ts)；历史全空时返回 (空 brain, None, 0)。
        """
        data = cls.fetch_warmup_data(exchange, ui_manager, symbol=symbol)
        candles_5m = data.get('5m', [])
        candles_15m = data.get('15m', [])
        candles_1h = data.get('1h', [])
        candles_1d = data.get('1d', [])

        new_brain = StrategyBrain()
        if not (candles_5m and candles_15m and candles_1h):
            ui_manager.log_msg("⚠️ Warmup Data Empty - Starting with minimal state", "warning")
            return new_brain, None, 0

        cls.ingest_warmup_candles(candles_5m, '5m', step=20, brain=new_brain, ui_manager=ui_manager)
        cls.ingest_warmup_candles(candles_15m, '15m', step=10, brain=new_brain, ui_manager=ui_manager)
        cls.ingest_warmup_candles(candles_1h, '1h', step=5, brain=new_brain, ui_manager=ui_manager)
        cls.ingest_warmup_candles(candles_1d, '1d', step=1, brain=new_brain, ui_manager=ui_manager)
        ui_manager.log_msg("✅ Warmup Complete", "success")

        initial_book = (
            exchange._cached_latest.get('orderbook')
            if hasattr(exchange, '_cached_latest')
            else None
        )
        return new_brain, new_brain.analyze(initial_book), candles_5m[-1][0]

    @staticmethod
    def ingest_warmup_candles(candles, timeframe, step, brain, ui_manager):
        ui_manager.log_msg(f"Processing {len(candles)} {timeframe} candles...", "info")
        for index, candle in enumerate(candles, start=1):
            brain.ingest_candle(candle, timeframe)
            if index % step == 0:
                ui_manager.log_msg(f"  Processed {index}/{len(candles)} {timeframe} candles", "info")

    @staticmethod
    def push_warmup_market(brain: StrategyBrain, web_state):
        """将预热完成的 K 线推入 Web 共享状态。"""
        if not Config.WEB_ENABLED or not web_state:
            return
        history_list = brain.history_5m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        history_15m = brain.history_15m[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        history_1h = brain.history_1h[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        history_1d = brain.history_1d[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()

        web_state.update_market(
            kline_5m=history_list,
            kline_15m=history_15m,
            kline_1h=history_1h,
            kline_1d=history_1d,
        )


class ModeSwitcher:
    """交易模式切换控制器（单向安全升级：DASHBOARD -> PAPER -> LIVE）。"""

    def __init__(self, bot):
        self.bot = bot

    def switch(self, target_mode_str: str) -> str:
        target = parse_mode(target_mode_str)
        bot = self.bot

        with bot._mode_lock:
            current = bot.trading_mode

            # 1. 单向升级校验
            if not can_switch(current, target):
                msg = f"不允许降级或同级切换: {current.value} -> {target.value}"
                logger.warning(msg)
                raise ValueError(msg)

            # 2. 无持仓校验
            if not bot.trader.position.is_flat:
                msg = f"当前有持仓，禁止切换模式 (size={bot.trader.position.size})"
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
            new_is_live = (target == TradingMode.LIVE)
            new_exchange = ExchangeService(new_is_live)
            bot.ui.log_msg(f"正在切换到 {target.label} 模式...", "info")

            ok, err_msg = new_exchange.connect()
            if not ok:
                new_exchange.close()
                msg = f"切换失败: 交易所重连失败 ({err_msg})"
                logger.error(msg)
                raise ValueError(msg)

            # 锁外取余额
            balance_info = new_exchange.fetch_balance()

            # 5. 锁内：原子交换共享状态
            with bot.bot_lock:
                if not bot.trader.position.is_flat:
                    new_exchange.close()
                    msg = f"当前有持仓，禁止切换模式 (size={bot.trader.position.size})"
                    logger.warning(msg)
                    raise ValueError(msg)

                old_exchange = bot.exchange
                bot.exchange = new_exchange
                bot.trader.exchange = new_exchange
                bot.is_live = new_is_live
                bot.trading_mode = target
                bot.mode_name = target.label

                if balance_info:
                    bot.trader.update_balance(balance_info['total'])

            # 锁外关闭旧连接
            old_exchange.close()

            # 6. 更新 Web 状态
            bot.web_state.set_trading_mode(target.value)
            bot.web_state.update_account(
                balance=bot.trader.balance,
                mode=target.value.capitalize(),
                symbol=Config.SYMBOL,
            )

            if balance_info:
                bot.ui.log_msg(
                    f"{target.label} Balance: Free ${balance_info['free']:.2f} | "
                    f"Total ${balance_info['total']:.2f}",
                    "success",
                )

            bot.ui.log_msg(f"✅ 已切换到 {target.label} 模式", "success")
            logger.info(f"Trading mode switched: {current.value} -> {target.value}")
            return f"已切换到 {target.label} 模式"


class SymbolSwitcher:
    """交易标的切换控制器（两阶段无感热切）。"""

    def __init__(self, bot):
        self.bot = bot

    def switch(self, target_symbol: str) -> str:
        bot = self.bot
        new_symbol = Config.normalize_symbol(target_symbol)

        if new_symbol == bot.exchange.symbol:
            return f"Already on {new_symbol}"

        if not bot._switch_lock.acquire(blocking=False):
            raise ValueError("已有切换任务进行中，请稍候")

        try:
            logger.info(f"Switching trading/watching symbol to {new_symbol}...")
            bot.ui.log_msg(f"Switching symbol to {new_symbol}...", "info")
            bot.web_state.set_status("switching")

            # ---------- 阶段 1：锁外预热（历史拉取 + 独立 brain） ----------
            new_brain, analysis, last_ts = WarmupCoordinator.build_warmup_brain(
                bot.exchange, bot.ui, new_symbol
            )

            # ---------- 阶段 2：锁内原子交换 ----------
            with bot.bot_lock:
                Config.set_symbol(new_symbol)
                bot.exchange.apply_symbol(new_symbol)
                bot.brain = new_brain
                bot.trader.brain = new_brain
                bot.last_tick_analysis = analysis
                bot.last_tick_price = 0.0
                bot.last_btc_price = 0.0
                if last_ts:
                    bot.current_candle_timestamp = last_ts

            WarmupCoordinator.push_warmup_market(new_brain, bot.web_state)
            bot.web_state.update_account(
                balance=bot.trader.balance,
                mode=bot.trading_mode.value.capitalize(),
                symbol=new_symbol,
            )
            bot.web_state.set_status("running")

            bot.ui.log_msg(f"✅ Symbol switched to {new_symbol}", "success")
            return f"Successfully switched to {new_symbol}"
        except Exception as exc:
            bot.web_state.set_status("running")
            logger.exception("switch_symbol failed")
            raise ValueError(f"切换标的异常: {exc}") from exc
        finally:
            bot._switch_lock.release()
