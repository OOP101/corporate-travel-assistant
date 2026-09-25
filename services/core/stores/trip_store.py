"""
行程存储 —— 策程 · Planner Core

内存存储 + JSON 文件持久化。
- 启动时从 data_dir 加载所有 .json 行程文件到内存。
- 每次 save/update/delete 同步写盘。
- 适合单实例演示；多实例需替换为数据库实现。
"""
import json
import logging
import os
import time
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger("core.store.trip")


class TripStore:
    """
    行程存储 (内存 + JSON 持久化)

    用法:
        store = TripStore(data_dir="./data/trips")
        trip_id = store.save(trip_dict)
        trip = store.get(trip_id)
        trips = store.list_by_user("default")
    """

    def __init__(self, data_dir: str = "./data/trips"):
        self.data_dir = data_dir
        self._trips: Dict[str, dict] = {}  # trip_id → trip dict

        os.makedirs(self.data_dir, exist_ok=True)
        self._load()
        logger.info(f"TripStore 初始化完成，已加载 {len(self._trips)} 条行程")

    # ------------------------------------------------------------------
    # 增删改查
    # ------------------------------------------------------------------
    def save(self, trip: dict) -> str:
        """
        保存行程。

        若 trip 无 trip_id 则生成；更新 updated_at。
        返回 trip_id。
        """
        trip_id = trip.get("trip_id") or f"trip_{uuid.uuid4().hex[:12]}"
        trip["trip_id"] = trip_id
        trip["updated_at"] = time.time()
        if "created_at" not in trip or not trip["created_at"]:
            trip["created_at"] = time.time()

        self._trips[trip_id] = trip
        self._persist(trip)
        logger.info(f"行程已保存: {trip_id}")
        return trip_id

    def get(self, trip_id: str) -> Optional[dict]:
        """获取单条行程，不存在返回 None。"""
        return self._trips.get(trip_id)

    def list_by_user(self, user_id: str) -> List[dict]:
        """按 user_id 查询行程列表，按更新时间倒序。"""
        items = [t for t in self._trips.values() if t.get("user_id", "default") == user_id]
        items.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
        return items

    def list_all(self) -> List[dict]:
        """全部行程列表，按更新时间倒序（对齐 P1 BaseJsonStore.list_all 接口）。"""
        items = list(self._trips.values())
        items.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
        return items

    def update(self, trip_id: str, data: dict) -> Optional[dict]:
        """
        编辑行程: 用 data 覆盖/合并已有字段。
        返回更新后的行程；不存在返回 None。
        """
        if trip_id not in self._trips:
            return None
        trip = self._trips[trip_id]
        trip.update(data)
        trip["trip_id"] = trip_id  # 防止篡改 id
        trip["updated_at"] = time.time()
        self._persist(trip)
        logger.info(f"行程已更新: {trip_id}")
        return trip

    def delete(self, trip_id: str) -> bool:
        """删除行程。成功返回 True，不存在返回 False。"""
        if trip_id not in self._trips:
            return False
        del self._trips[trip_id]
        file_path = os.path.join(self.data_dir, f"{trip_id}.json")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            logger.warning(f"删除行程文件失败 {trip_id}: {e}")
        logger.info(f"行程已删除: {trip_id}")
        return True

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _persist(self, trip: dict):
        """将单条行程写入 JSON 文件。"""
        trip_id = trip.get("trip_id", "unknown")
        file_path = os.path.join(self.data_dir, f"{trip_id}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(trip, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"行程持久化失败 {trip_id}: {e}")

    def _load(self):
        """启动时加载目录下所有 JSON 行程文件。"""
        if not os.path.isdir(self.data_dir):
            return
        for fname in os.listdir(self.data_dir):
            if not fname.endswith(".json"):
                continue
            file_path = os.path.join(self.data_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    trip = json.load(f)
                trip_id = trip.get("trip_id") or fname[:-5]
                trip["trip_id"] = trip_id
                self._trips[trip_id] = trip
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"加载行程文件失败 {fname}: {e}")
