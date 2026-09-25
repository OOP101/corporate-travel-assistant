"""
JSON 持久化存储基类 —— 消除 trip_store / profile_store / template_store 的重复代码

三个 Store 共享: 内存 dict + JSON 文件持久化 + 加载/保存/删除模式。
"""
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from typing import Dict, List, Optional, Any

logger = logging.getLogger("shared.store.base")


def atomic_write_json(path: str, payload: Any, *, logger_: Optional[logging.Logger] = None,
                      what: str = "") -> bool:
    """原子写 JSON 文件：先写同目录临时文件，再 os.replace 覆盖目标。

    为什么必须这样写：直接 open(path, "w") + json.dump 的窗口期内进程被中断
    （被 kill / 断电 / 磁盘满），目标文件会停在半截，原数据随之损坏且无法解析。
    os.replace 在同一文件系统内是原子操作，所以目标要么是旧内容、要么是完整新内容。

    返回值：True 成功 / False 失败（失败已记日志，不抛异常，不阻断主流程）。
    """
    log = logger_ or logger
    tmp_path = None
    try:
        # 临时文件必须与目标同目录，否则跨盘 os.replace 失去原子性
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        tmp_path = None
        return True
    except (OSError, TypeError, ValueError) as e:
        log.error(f"{what or path} 持久化失败: {e}")
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass



class BaseJsonStore:
    """
    JSON 持久化存储基类。

    子类只需实现:
      - _id_field: 实体 ID 字段名 (如 "trip_id" / "user_id" / "template_id")
      - _id_prefix: 生成 ID 的前缀 (如 "trip_" / "user_" / "tpl_")
      - _default_entity(): 返回默认实体模板 (可选)
    """

    _id_field: str = "id"
    _id_prefix: str = "entity_"

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._entities: Dict[str, dict] = {}
        # 进程内写锁：save/update/delete 与持久化互斥（多线程 uvicorn 场景）
        self._lock = threading.RLock()

        os.makedirs(self.data_dir, exist_ok=True)
        self._load()
        logger.info(f"{self.__class__.__name__} 初始化完成，已加载 {len(self._entities)} 条记录")

    # ------------------------------------------------------------------
    # 公共 CRUD
    # ------------------------------------------------------------------
    def get(self, entity_id: str) -> Optional[dict]:
        """获取单条记录，不存在返回 None。"""
        return self._entities.get(entity_id)

    def list_all(self) -> List[dict]:
        """列出所有记录，按 updated_at 倒序。"""
        items = list(self._entities.values())
        items.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
        return items

    def save(self, entity: dict) -> str:
        """
        保存记录。若无 ID 则生成；更新 updated_at。
        返回实体 ID。
        """
        entity_id = entity.get(self._id_field) or f"{self._id_prefix}{uuid.uuid4().hex[:12]}"
        entity[self._id_field] = entity_id
        entity["updated_at"] = time.time()
        if "created_at" not in entity or not entity["created_at"]:
            entity["created_at"] = time.time()

        with self._lock:
            self._entities[entity_id] = entity
            self._persist(entity)
        logger.info(f"{self.__class__.__name__} 已保存: {entity_id}")
        return entity_id

    def update(self, entity_id: str, data: dict) -> Optional[dict]:
        """
        编辑记录: 用 data 覆盖/合并已有字段。
        返回更新后的记录；不存在返回 None。
        """
        with self._lock:
            if entity_id not in self._entities:
                return None
            entity = self._entities[entity_id]
            # 防止篡改 ID
            safe_data = {k: v for k, v in data.items() if k != self._id_field}
            entity.update(safe_data)
            entity[self._id_field] = entity_id
            entity["updated_at"] = time.time()
            self._persist(entity)
        logger.info(f"{self.__class__.__name__} 已更新: {entity_id}")
        return entity

    def delete(self, entity_id: str) -> bool:
        """删除记录。成功返回 True，不存在返回 False。"""
        with self._lock:
            if entity_id not in self._entities:
                return False
            del self._entities[entity_id]
        file_path = os.path.join(self.data_dir, f"{entity_id}.json")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            logger.warning(f"删除文件失败 {entity_id}: {e}")
        logger.info(f"{self.__class__.__name__} 已删除: {entity_id}")
        return True

    def count(self) -> int:
        """返回记录总数。"""
        return len(self._entities)

    # ------------------------------------------------------------------
    # 持久化（子类可覆盖）
    # ------------------------------------------------------------------
    def _persist(self, entity: dict):
        """将单条记录原子写入 JSON 文件（temp 文件 + os.replace，崩溃不损坏已有数据）。"""
        entity_id = entity.get(self._id_field, "unknown")
        file_path = os.path.join(self.data_dir, f"{entity_id}.json")
        atomic_write_json(
            file_path, entity,
            logger_=logger, what=f"{self.__class__.__name__} {entity_id}",
        )

    def _load(self):
        """启动时加载目录下所有 JSON 文件。"""
        if not os.path.isdir(self.data_dir):
            return
        for fname in os.listdir(self.data_dir):
            if not fname.endswith(".json"):
                continue
            file_path = os.path.join(self.data_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    entity = json.load(f)
                entity_id = entity.get(self._id_field) or fname[:-5]
                entity[self._id_field] = entity_id
                self._entities[entity_id] = entity
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"加载文件失败 {fname}: {e}")
