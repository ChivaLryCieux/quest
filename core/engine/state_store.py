"""运行时状态持久化。

把余额、持仓、Kelly 交易历史、回撤峰值写到 data/runtime/state.json，
进程崩溃 / 断电 / 重启后可恢复，避免权益曲线与仓位失联。

写入使用「临时文件 + os.replace」保证原子性，读取容错（文件损坏时
回退到空状态而不是崩溃）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class StateStore:
    """线程安全的 JSON 状态存储。"""

    def __init__(self, directory: str, filename: str = "state.json"):
        self.directory = os.path.abspath(directory)
        self.path = os.path.join(self.directory, filename)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ read

    def load(self) -> dict[str, Any]:
        """读取状态；文件不存在返回空 dict，损坏时告警并返回空 dict。"""
        with self._lock:
            if not os.path.exists(self.path):
                return {}
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ValueError("state root must be an object")
                return data
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning("State file unreadable (%s), starting fresh: %s", self.path, exc)
                return {}

    # ----------------------------------------------------------------- write

    def save(self, state: dict[str, Any]) -> bool:
        """原子写入状态，返回是否成功。"""
        payload = dict(state)
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload["saved_at"] = int(time.time() * 1000)

        with self._lock:
            try:
                os.makedirs(self.directory, exist_ok=True)
                tmp_path = f"{self.path}.tmp"
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.path)
                return True
            except OSError as exc:
                logger.error("Failed to persist state to %s: %s", self.path, exc)
                return False

    # --------------------------------------------------------------- helpers

    @property
    def exists(self) -> bool:
        return os.path.exists(self.path)

    def snapshot_meta(self) -> Optional[dict[str, Any]]:
        """只读取元信息（不触发完整恢复流程时用）。"""
        data = self.load()
        if not data:
            return None
        return {
            "saved_at": data.get("saved_at"),
            "balance": data.get("balance"),
            "schema_version": data.get("schema_version"),
        }
