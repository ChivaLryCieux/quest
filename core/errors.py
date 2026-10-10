"""统一异常分层。

- QuestError:       框架内所有可预期错误的基类
- ConfigError:      配置缺失 / 非法（启动前可拦截）
- ConnectionError:  交易所连接 / WS / REST 失败
- DataError:        行情、历史 K 线不可用
- OrderError:       下单被拒 / 资金不足 / 网络失败

目标：实盘关键路径（下单）失败时抛异常而不是静默回 False，
让调用方决定是跳过本 tick 还是进入降级，而不是用旧数据交易。
"""


class QuestError(Exception):
    """框架基类异常。"""


class ConfigError(QuestError):
    """配置错误。"""


class ConnectionError(QuestError):
    """交易所连接错误。"""


class DataError(QuestError):
    """行情数据错误。"""


class OrderError(QuestError):
    """下单执行错误。"""
