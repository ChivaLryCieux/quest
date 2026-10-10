"""量化策略层 (Strategy Framework)

- base: 策略抽象基类与协议 (BaseStrategy)
- microstructure: 盘口微观结构与深度失衡分析 (OrderBookAnalyzer)
- analyzers: 短线多信号投票引擎 (SignalEngine)
- brain: 多周期共识 CTA 策略大脑 (StrategyBrain)
"""

from .base import BaseStrategy
from .microstructure import OrderBookAnalyzer
from .analyzers import SignalEngine
from .brain import StrategyBrain

__all__ = [
    'BaseStrategy',
    'OrderBookAnalyzer',
    'SignalEngine',
    'StrategyBrain',
]