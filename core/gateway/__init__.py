"""交易所网关与数据源模块 (Gateway & Data Feeds)

解耦网络I/O、WebSocket流式订阅、国内行情源和交易所下单操作：
- binance_stream: Binance 永续合约 WebSocket 聚合行情流
- domestic_feed: 国内 A 股新浪直连行情源
- service: 统一门面 ExchangeService
"""

from .binance_stream import MarketDataStreamer
from .domestic_feed import DomesticDataStreamer
from .service import ExchangeService

__all__ = [
    "MarketDataStreamer",
    "DomesticDataStreamer",
    "ExchangeService",
]
