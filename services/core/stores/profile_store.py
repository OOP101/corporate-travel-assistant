"""
偏好画像存储 —— Agent 内核 · 用户画像持久化

内存存储 + JSON 文件持久化。
- 启动时从 data_dir 加载所有 .json 画像文件到内存。
- 每次 save/update/add_companion 同步写盘，写盘为原子操作（temp + os.replace）。
- 适合单实例演示；多实例需替换为数据库实现。

数据结构遵循 shared.models.PreferenceProfile。
"""
import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional

from shared.store.base_store import atomic_write_json

logger = logging.getLogger("core.store.profile")


# 默认画像字段 (与 PreferenceProfile 对齐)
_DEFAULT_PROFILE: dict = {
    "budget_daily_range": [200, 800],
    "travel_style": "",
    "dietary": [],
    "fitness_level": "normal",
    "accommodation_pref": "",
    "companions": [],
    "visited_cities": [],
    "extra": {},
}


class ProfileStore:
    """
    偏好画像存储 (内存 + JSON 持久化)

    用法:
        store = ProfileStore(data_dir="./data/profiles")
        profile = store.get("user_abc")
        store.save("user_abc", {...})
        store.update("user_abc", {"travel_style": "relaxed"})
    """

    def __init__(self, data_dir: str = "./data/profiles"):
        self.data_dir = data_dir
        self._profiles: Dict[str, dict] = {}  # user_id → profile dict
        # 进程内写锁：内存改动与写盘互斥（uvicorn 线程池并发跑 sync 端点）
        self._lock = threading.RLock()

        os.makedirs(self.data_dir, exist_ok=True)
        self._load()
        logger.info(f"ProfileStore 初始化完成，已加载 {len(self._profiles)} 条偏好画像")

    # ------------------------------------------------------------------
    # 增删改查
    # ------------------------------------------------------------------
    def get(self, user_id: str) -> dict:
        """
        获取用户偏好画像，不存在则返回空画像 (字段补全)。
        返回的字典包含 user_id 字段。
        """
        if user_id in self._profiles:
            profile = dict(self._profiles[user_id])
            profile["user_id"] = user_id
            return profile
        # 不存在 → 返回默认画像
        profile = json.loads(json.dumps(_DEFAULT_PROFILE))  # 深拷贝
        profile["user_id"] = user_id
        return profile

    def save(self, user_id: str, profile: dict) -> dict:
        """
        保存 (覆盖) 用户偏好画像。
        若缺少字段则用默认值补全；返回保存后的画像。
        """
        merged = json.loads(json.dumps(_DEFAULT_PROFILE))  # 深拷贝默认值
        merged.update(profile)
        merged["user_id"] = user_id
        merged["updated_at"] = time.time()
        if "created_at" not in merged or not merged["created_at"]:
            merged["created_at"] = time.time()

        # budget_daily_range 归一为 list
        bdr = merged.get("budget_daily_range")
        if isinstance(bdr, (list, tuple)):
            merged["budget_daily_range"] = list(bdr)
        else:
            merged["budget_daily_range"] = list(_DEFAULT_PROFILE["budget_daily_range"])

        with self._lock:
            self._profiles[user_id] = merged
            self._persist(user_id, merged)
        logger.info(f"偏好画像已保存: {user_id}")
        return merged

    def update(self, user_id: str, partial: dict) -> dict:
        """
        部分更新用户偏好画像: 用 partial 合并到已有画像。
        不存在则基于默认画像创建。返回更新后的画像。
        """
        current = self._profiles.get(user_id)
        if current is None:
            current = json.loads(json.dumps(_DEFAULT_PROFILE))
            current["user_id"] = user_id
            current["created_at"] = time.time()

        # 防止篡改 user_id
        partial = {k: v for k, v in partial.items() if k != "user_id"}
        current.update(partial)
        current["user_id"] = user_id
        current["updated_at"] = time.time()

        with self._lock:
            self._profiles[user_id] = current
            self._persist(user_id, current)
        logger.info(f"偏好画像已更新: {user_id}")
        return current

    # ------------------------------------------------------------------
    # 同行人 (companions) 便捷方法
    # ------------------------------------------------------------------
    def add_companion(self, user_id: str, companion: dict) -> dict:
        """
        向用户画像追加一位同行人 (companions 列表)。
        返回新增后的画像。
        """
        profile = self._profiles.get(user_id)
        if profile is None:
            profile = self.get(user_id)  # 触发默认画像
            profile["created_at"] = time.time()
        companions: List[dict] = list(profile.get("companions", []))
        companions.append(companion)
        profile["companions"] = companions
        profile["updated_at"] = time.time()
        with self._lock:
            self._profiles[user_id] = profile
            self._persist(user_id, profile)
        logger.info(f"同行人已添加: {user_id} → {companion.get('name', '')}")
        return profile

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _persist(self, user_id: str, profile: dict):
        """将单条画像原子写入 JSON 文件（文件名 = user_id.json）。"""
        file_path = os.path.join(self.data_dir, f"{user_id}.json")
        atomic_write_json(file_path, profile, logger_=logger, what=f"偏好画像 {user_id}")

    def _load(self):
        """启动时加载目录下所有 JSON 画像文件。"""
        if not os.path.isdir(self.data_dir):
            return
        for fname in os.listdir(self.data_dir):
            if not fname.endswith(".json"):
                continue
            file_path = os.path.join(self.data_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                user_id = profile.get("user_id") or fname[:-5]
                profile["user_id"] = user_id
                self._profiles[user_id] = profile
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"加载画像文件失败 {fname}: {e}")
