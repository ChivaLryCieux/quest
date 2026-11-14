import logging
import threading
import time
from datetime import datetime, timezone, timedelta

import requests

from core.analysis.tick_agg import TickAggregator

logger = logging.getLogger(__name__)


class DomesticDataStreamer(threading.Thread):
    def __init__(self, symbol, data_event: threading.Event | None = None):
        super().__init__()
        self.daemon = True
        self.symbol = symbol.lower()
        self.lock = threading.Lock()
        self.running = True
        self.data_event = data_event
        # tick -> 真实 OHLCV 蜡烛聚合（替代 OHLC 全填同价的假蜡烛）
        self._aggs = {
            'kline_5m': TickAggregator(300),
            'kline_15m': TickAggregator(900),
            'kline_1h': TickAggregator(3600),
        }
        self._finals = {}
        self._prev_day_vol = None
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
        """标的切换：更新订阅代码，重置蜡烛聚合状态。"""
        self.symbol = new_symbol.lower()
        with self.lock:
            self._aggs = {
                'kline_5m': TickAggregator(300),
                'kline_15m': TickAggregator(900),
                'kline_1h': TickAggregator(3600),
            }
            self._prev_day_vol = None
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

                                # 日累计成交量 -> tick 增量，再聚合成真实 OHLCV 蜡烛
                                prev_vol = self._prev_day_vol
                                self._prev_day_vol = volume
                                if prev_vol is None:
                                    tick_vol = 0.0
                                elif volume < prev_vol:
                                    tick_vol = volume  # 新交易日累计量重置
                                else:
                                    tick_vol = volume - prev_vol

                                with self.lock:
                                    self.data['orderbook'] = orderbook
                                    for key, agg in self._aggs.items():
                                        self.data[key] = agg.update(timestamp_ms, curr_price, tick_vol)
                                        closed = agg.pop_closed()
                                        if closed is not None:
                                            self._finals[key] = closed
                                    self.data['is_ready'] = True
                                if self.data_event is not None:
                                    self.data_event.set()
            except Exception as e:
                logger.error(f"Domestic polling error: {e}")
            time.sleep(2.0)

    def stop(self):
        self.running = False

    def get_latest(self):
        with self.lock:
            return self.data.copy()

    def pop_finals(self):
        """取走自上次以来聚合出的收盘K线 {kline_tf: row}。"""
        with self.lock:
            finals = self._finals
            self._finals = {}
        return finals
