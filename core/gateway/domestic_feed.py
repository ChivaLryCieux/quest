import logging
import threading
import time
from datetime import datetime, timezone, timedelta

import requests

logger = logging.getLogger(__name__)


class DomesticDataStreamer(threading.Thread):
    def __init__(self, symbol):
        super().__init__()
        self.daemon = True
        self.symbol = symbol.lower()
        self.lock = threading.Lock()
        self.running = True
        self.data = {
            'kline_5m': None,
            'kline_15m': None,
            'kline_1h': None,
            'orderbook': None,
            'funding_rate': 0.0,
            'btc_price': 0.0,
            'is_ready': False
        }

    def set_symbol(self, new_symbol):
        """标的切换：更新订阅代码，下一轮轮询即生效。"""
        self.symbol = new_symbol.lower()
        logger.info(f"[Domestic] Switching feed to {self.symbol}")

    def run(self):
        logger.info(f"Starting DomesticDataStreamer for {self.symbol}...")
        headers = {"Referer": "https://finance.sina.com.cn/"}
        url = f"http://hq.sinajs.cn/list={self.symbol}"

        while self.running:
            # 标的切换时 self.symbol 已更新，重建 URL 后继续轮询
            expected_url = f"http://hq.sinajs.cn/list={self.symbol}"
            if url != expected_url:
                url = expected_url
                logger.info(f"[Domestic] Feed URL updated: {url}")
            try:
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code == 200:
                    text = resp.content.decode('gbk')
                    if '"' in text:
                        data_str = text.split('"')[1]
                        if data_str.strip():
                            parts = data_str.split(',')
                            if len(parts) >= 32:
                                curr_price = float(parts[3])
                                open_price = float(parts[1]) if float(parts[1]) > 0 else curr_price
                                high_price = float(parts[4]) if float(parts[4]) > 0 else curr_price
                                low_price = float(parts[5]) if float(parts[5]) > 0 else curr_price
                                volume = float(parts[8])
                                date_str = parts[30]
                                time_str = parts[31]

                                tz_bj = timezone(timedelta(hours=8))
                                dt_str = f"{date_str} {time_str}"
                                try:
                                    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_bj)
                                except ValueError:
                                    dt = datetime.now(tz_bj)

                                timestamp_ms = int(dt.timestamp() * 1000)

                                bids = []
                                asks = []
                                for i in range(5):
                                    vol_idx = 10 + i * 2
                                    prc_idx = 11 + i * 2
                                    if float(parts[prc_idx]) > 0:
                                        bids.append([float(parts[prc_idx]), float(parts[vol_idx]) / 100.0])
                                for i in range(5):
                                    vol_idx = 20 + i * 2
                                    prc_idx = 21 + i * 2
                                    if float(parts[prc_idx]) > 0:
                                        asks.append([float(parts[prc_idx]), float(parts[vol_idx]) / 100.0])

                                orderbook = {
                                    "bids": bids,
                                    "asks": asks
                                }

                                def get_kline_candle(tf_sec):
                                    candle_ts_ms = (timestamp_ms // (tf_sec * 1000)) * (tf_sec * 1000)
                                    return [
                                        candle_ts_ms,
                                        open_price,
                                        high_price,
                                        low_price,
                                        curr_price,
                                        volume,
                                        volume * 0.5
                                    ]

                                with self.lock:
                                    self.data['orderbook'] = orderbook
                                    self.data['kline_5m'] = get_kline_candle(300)
                                    self.data['kline_15m'] = get_kline_candle(900)
                                    self.data['kline_1h'] = get_kline_candle(3600)
                                    self.data['is_ready'] = True
            except Exception as e:
                logger.error(f"Domestic polling error: {e}")
            time.sleep(2.0)

    def stop(self):
        self.running = False

    def get_latest(self):
        with self.lock:
            return self.data.copy()
