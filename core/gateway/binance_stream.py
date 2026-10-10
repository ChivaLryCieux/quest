import json
import logging
import threading
import time

import websocket
from colorama import Fore, Style
from core.config.settings import Config

logger = logging.getLogger(__name__)


class MarketDataStreamer(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.ws = None

        # Binance Stream 名称必须小写，强制转换防止配置错误
        self.url = self._build_url()

        # 线程安全的数据存储
        self.lock = threading.Lock()
        self.data = {
            'kline_5m': None,
            'kline_15m': None,
            'kline_1h': None,
            'orderbook': None,
            'funding_rate': 0.0,
            'btc_price': 0.0,
            'is_ready': False
        }
        self.running = True
        self._last_update_time = time.time()

    @staticmethod
    def _build_url():
        """根据当前 Config.SYMBOL_WS 构造 Binance 组合流地址。"""
        symbol_lower = Config.SYMBOL_WS.lower()

        # 提取基础 WS 域名并拼接 streams 参数
        base_ws_url = Config.BINANCE_WS_URL
        if "?" in base_ws_url:
            base_ws_url = base_ws_url.split("?")[0]

        return (
            f"{base_ws_url}?streams="
            f"{symbol_lower}@kline_5m/"
            f"{symbol_lower}@kline_15m/"
            f"{symbol_lower}@kline_1h/"
            f"{symbol_lower}@depth20@100ms/"
            f"{symbol_lower}@markPrice/"
            f"btcusdt@kline_1m"
        )

    def set_symbol(self):
        """标的切换：重建订阅地址并触发重连，保留已缓存的数据。

        run() 每轮循环都会读取 self.url，所以这里只要关闭当前
        连接，线程就会用新地址自动重连，无需销毁重建线程。
        """
        self.url = self._build_url()
        ws = self.ws
        if ws is not None:
            try:
                ws.close()
            except Exception as exc:
                logger.warning(f"[WS] Failed to close for symbol switch: {exc}")
        logger.info(f"[WS] Subscribing to new symbol stream: {self.url}")

    def run(self):
        while self.running:
            try:
                logger.info(f"Connecting to WS: {self.url}")
                # 配置 WebSocket
                self.ws = websocket.WebSocketApp(
                    self.url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )

                # 设置代理
                proxy_opts = {}
                if Config.PROXY_ENABLED and Config.PROXY_HOST and Config.PROXY_PORT:
                    proxy_opts = {
                        "http_proxy_host": Config.PROXY_HOST,
                        "http_proxy_port": Config.PROXY_PORT,
                        "proxy_type": "http"
                    }

                # Ping/Pong 保持连接活跃
                self.ws.run_forever(ping_interval=30, ping_timeout=10, **proxy_opts)
            except Exception as e:
                logger.error(f"WS Critical Error: {e}")

            if self.running:
                logger.warning("WS Disconnected. Reconnecting in %.1fs...", Config.WS_RECONNECT_DELAY_SEC)
                time.sleep(Config.WS_RECONNECT_DELAY_SEC)

    def _on_open(self, ws):
        print(f"{Fore.GREEN}[WS] Connected to Binance Futures Stream{Style.RESET_ALL}")

    def _on_message(self, ws, message):
        try:
            # json.loads 比较耗时，放在锁外面执行
            msg = json.loads(message)
            stream = msg.get('stream')
            payload = msg.get('data')

            if not stream or not payload:
                return

            # 准备好数据结构，尽量减少在锁内的时间
            updates = {}

            # 1. K线数据处理
            if 'kline' in stream:
                k = payload['k']
                # 转换为浮点数列表
                kline_data = [
                    k['t'], float(k['o']), float(k['h']), float(k['l']),
                    float(k['c']), float(k['v']), float(k['Q'])
                ]

                if 'btcusdt' in stream:
                    updates['btc_price'] = float(k['c'])
                elif 'kline_5m' in stream:
                    updates['kline_5m'] = kline_data
                elif 'kline_15m' in stream:
                    updates['kline_15m'] = kline_data
                elif 'kline_1h' in stream:
                    updates['kline_1h'] = kline_data

            # 2. 深度数据处理
            elif 'depth20' in stream:
                updates['orderbook'] = {
                    'bids': [[float(p), float(v)] for p, v in payload['b']],
                    'asks': [[float(p), float(v)] for p, v in payload['a']]
                }

            # 3. 资金费率
            elif 'markPrice' in stream:
                if 'r' in payload:
                    updates['funding_rate'] = float(payload['r'])

            # 快速更新，减少锁占用时间
            with self.lock:
                self.data.update(updates)

                # 检查数据是否准备就绪
                if not self.data['is_ready']:
                    if (self.data['kline_5m'] is not None and
                            self.data['kline_15m'] is not None and
                            self.data['kline_1h'] is not None and
                            self.data['orderbook'] is not None):
                        self.data['is_ready'] = True
                        logger.info("Market Data Ready!")

                self._last_update_time = time.time()

        except Exception as e:
            logger.error(f"WS Message Parse Error: {e}")

    def _on_error(self, ws, error):
        logger.error(f"[WS Error] {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"[WS] Closed. Status: {close_status_code}, Msg: {close_msg}")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def get_latest(self):
        with self.lock:
            return self.data.copy()
