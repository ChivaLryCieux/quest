"""量化策略基础协议与抽象基类 (Base Strategy Protocol)

规范策略生命周期与事件处理，使得策略具备插拔与多策略组合能力。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseStrategy(ABC):
    """量化交易策略抽象基类。"""

    def __init__(self, name: str = "BaseStrategy"):
        self.name = name

    @abstractmethod
    def ingest_candle(
        self,
        item: list,
        timeframe: str = '5m',
        btc_change_pct: float = 0.0,
        obi_value: float = 0.0,
    ) -> None:
        """接收 K 线数据，更新内部状态与历史缓存。"""
        pass

    @abstractmethod
    def analyze(self, orderbook: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        """执行指标与信号分析，生成交易上下文。"""
        pass
