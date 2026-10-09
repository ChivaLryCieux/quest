# 共享交易模型：持仓 / 订单 / 交易记录
#
# 目标：终结 trader dict / web TradeRecord / report CSV 三套字段各写各的。
# Position 是第一个统一模型，实盘 / 纸盘 / 回测共用。

from .position import Position

__all__ = ["Position"]
