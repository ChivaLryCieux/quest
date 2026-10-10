"""[Deprecated] 遗留的 PositionManager。

系统运行时已统一采用 core.models.position.Position 领域模型与 TradeExecutor / RiskManager 管理持仓。
保留此类仅为兼容旧版脚本。
"""

import copy
import logging
import threading
import warnings
from core.config.settings import Config

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(self):
        warnings.warn(
            "PositionManager is deprecated and will be removed. Use core.models.position.Position instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.positions = {}
        self.max_positions = Config.MAX_POSITIONS
        self.max_position_size = getattr(Config, 'MAX_POSITION_SIZE', 10000.0)
        self._lock = threading.Lock()

    def add_position(self, symbol, position_data):
        with self._lock:
            if len(self.positions) >= self.max_positions:
                return False, f"达到最大仓位数量限制 ({self.max_positions})"
            size = position_data.get('size', 0)
            if abs(size) == 0:
                return False, "仓位大小不能为0"
            if abs(size) > self.max_position_size:
                return False, f"仓位大小 ({abs(size)}) 超过限制 ({self.max_position_size})"
            if symbol in self.positions:
                logger.warning(f"覆盖已存在的仓位: {symbol}")
            self.positions[symbol] = position_data
            logger.info(f"仓位添加成功: {symbol} Size:{size}")
            return True, "仓位添加成功"

    def remove_position(self, symbol):
        with self._lock:
            if symbol in self.positions:
                del self.positions[symbol]
                return True, "仓位移除成功"
            return False, "仓位不存在"

    def update_position(self, symbol, updates):
        with self._lock:
            if symbol in self.positions:
                self.positions[symbol].update(updates)
                return True, "仓位更新成功"
            return False, "仓位不存在"

    def get_position(self, symbol):
        with self._lock:
            pos = self.positions.get(symbol, None)
            if pos:
                return pos.copy()
            return None

    def get_all_positions(self):
        with self._lock:
            return copy.deepcopy(self.positions)

    def calculate_total_exposure(self):
        with self._lock:
            total_exposure = 0.0
            for pos in self.positions.values():
                size = abs(pos.get('size', 0.0))
                entry_price = pos.get('entry_price', 0.0)
                if entry_price > 0:
                    total_exposure += size * entry_price
                else:
                    total_exposure += size
            return total_exposure

    def is_position_limit_reached(self):
        with self._lock:
            return len(self.positions) >= self.max_positions

    def clear_all_positions(self):
        with self._lock:
            self.positions.clear()