"""兼容垫片：保持 core.config.exchange 的向后兼容。

真实实现在 core.gateway.service，网络/I/O 逻辑已从 config 层移出。
"""

from core.gateway.service import ExchangeService
from core.gateway.binance_stream import MarketDataStreamer
from core.gateway.domestic_feed import DomesticDataStreamer

__all__ = [
    "ExchangeService",
    "MarketDataStreamer",
    "DomesticDataStreamer",
]
