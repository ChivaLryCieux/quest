"""风险与资金管理模块 (Risk & Capital Management)

- manager: 动态止损/止盈/追踪止损与熔断机制 (RiskManager)
- position_sizer: 基于 Kelly Criterion 与回撤防护的动态仓位管理 (PositionSizer)
- position: [已废弃] 遗留仓位字典管理器 (PositionManager)
"""

from .manager import RiskManager
from .position_sizer import PositionSizer
from .position import PositionManager

__all__ = [
    'RiskManager',
    'PositionSizer',
    'PositionManager',
]