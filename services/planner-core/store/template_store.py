"""
行程模板存储 —— 策程 · Planner Core

内存存储 + JSON 文件持久化。
- 启动时从 data_dir 加载所有 .json 模板文件到内存。
- 每次 save/update/delete 同步写盘。
- 适合单实例演示；多实例需替换为数据库实现。

模板 = 行程快照，附带 tags (城市/天数/风格/季节) 和 template_name 字段，
便于在多个用户间复用。模板本身不与具体 user_id 绑定 (可由所有用户查询/应用)。
"""
import copy
import json
import logging
import os
import time
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger("planner-core.store")


class TemplateStore:
    """
    行程模板存储 (内存 + JSON 持久化)

    用法:
        store = TemplateStore(data_dir="./data/templates")
        tpl_id = store.save_as_template(trip_dict, "成都3日亲子", tags=["成都","3天","亲子"])
        templates = store.list_templates(tags=["成都"])
        tpl = store.get_template(tpl_id)
        store.delete_template(tpl_id)
    """

    def __init__(self, data_dir: str = "./data/templates"):
        self.data_dir = data_dir
        self._templates: Dict[str, dict] = {}  # template_id → template dict

        os.makedirs(self.data_dir, exist_ok=True)
        self._load()
        logger.info(f"TemplateStore 初始化完成，已加载 {len(self._templates)} 条行程模板")

    # ------------------------------------------------------------------
    # 增删改查
    # ------------------------------------------------------------------
    def save_as_template(
        self,
        trip: dict,
        template_name: str,
        tags: Optional[List[str]] = None,
    ) -> dict:
        """
        将行程保存为模板 (快照)。

        - 复制 trip 数据，去除动态字段 (trip_id / user_id / status / 时间戳)。
        - 生成新 template_id，附加 template_name / tags / 元数据。
        - 返回保存后的模板字典。
        """
        tags = tags or []

        # 深拷贝行程，避免修改原对象
        snapshot = copy.deepcopy(trip)

        # 去除实例相关字段 (模板为通用快照)
        for key in ("trip_id", "user_id", "status", "created_at", "updated_at"):
            snapshot.pop(key, None)

        template_id = f"tpl_{uuid.uuid4().hex[:12]}"
        now = time.time()
        snapshot["template_id"] = template_id
        snapshot["template_name"] = template_name or (trip.get("title") or "未命名模板")
        snapshot["tags"] = tags
        snapshot["source_trip_id"] = trip.get("trip_id", "")
        snapshot["created_at"] = now
        snapshot["updated_at"] = now

        self._templates[template_id] = snapshot
        self._persist(snapshot)
        logger.info(f"行程模板已保存: {template_id} ({snapshot['template_name']})")
        return snapshot

    def get_template(self, template_id: str) -> Optional[dict]:
        """获取单条模板，不存在返回 None。"""
        return self._templates.get(template_id)

    def list_templates(self, tags: Optional[List[str]] = None) -> List[dict]:
        """
        列出模板，按创建时间倒序。

        Args:
            tags: 过滤标签 (城市/天数/风格/季节)，匹配任一即返回 (OR 语义)。
                  为空或 None 时返回全部。
        """
        items = list(self._templates.values())
        if tags:
            # 标准化比较 (去空格、小写)
            wanted = {str(t).strip().lower() for t in tags if t}
            filtered = []
            for tpl in items:
                tpl_tags = {str(t).strip().lower() for t in tpl.get("tags", []) if t}
                if tpl_tags & wanted:
                    filtered.append(tpl)
            items = filtered
        items.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return items

    def delete_template(self, template_id: str) -> bool:
        """删除模板。成功返回 True，不存在返回 False。"""
        if template_id not in self._templates:
            return False
        del self._templates[template_id]
        file_path = os.path.join(self.data_dir, f"{template_id}.json")
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            logger.warning(f"删除模板文件失败 {template_id}: {e}")
        logger.info(f"行程模板已删除: {template_id}")
        return True

    def update_template(self, template_id: str, data: dict) -> Optional[dict]:
        """
        编辑模板元数据 (如 template_name / tags)，不应覆盖快照内容。
        返回更新后的模板；不存在返回 None。
        """
        if template_id not in self._templates:
            return None
        tpl = self._templates[template_id]
        # 仅允许更新元数据字段
        for key in ("template_name", "tags"):
            if key in data:
                tpl[key] = data[key]
        tpl["template_id"] = template_id  # 防止篡改 id
        tpl["updated_at"] = time.time()
        self._persist(tpl)
        logger.info(f"行程模板已更新: {template_id}")
        return tpl

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _persist(self, template: dict):
        """将单条模板写入 JSON 文件。"""
        template_id = template.get("template_id", "unknown")
        file_path = os.path.join(self.data_dir, f"{template_id}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(template, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"模板持久化失败 {template_id}: {e}")

    def _load(self):
        """启动时加载目录下所有 JSON 模板文件。"""
        if not os.path.isdir(self.data_dir):
            return
        for fname in os.listdir(self.data_dir):
            if not fname.endswith(".json"):
                continue
            file_path = os.path.join(self.data_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    template = json.load(f)
                template_id = template.get("template_id") or fname[:-5]
                template["template_id"] = template_id
                self._templates[template_id] = template
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"加载模板文件失败 {fname}: {e}")
