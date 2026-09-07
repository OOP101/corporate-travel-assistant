"""模型与 LLM 配置管理 —— 管理员运行时配置

- 可用模型列表与默认模型：存储于配置 Store，管理员可增删改，前端模型选择器实时拉取
- LLM 服务商配置（base_url / api_key）：管理员可在线更新，立即生效（重新注册 provider）并持久化
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.auth import require_admin
from shared.store.base_store import BaseJsonStore

logger = logging.getLogger("journey-hub.admin")

router = APIRouter(tags=["系统管理"])

DEFAULT_MODELS = [
    {"model_id": "hy-mt2-pro", "label": "混元 Pro"},
    {"model_id": "deepseek-v4-flash", "label": "DeepSeek V4"},
    {"model_id": "glm-5-turbo", "label": "GLM Turbo"},
]

CONFIG_ID = "app"


class ConfigStore(BaseJsonStore):
    """系统配置存储（单实体 app：模型列表 / 默认模型 / LLM 服务配置）"""
    _id_field = "config_id"
    _id_prefix = "cfg_"


def _get_config_store(request):
    store = getattr(request.app.state, "config_store", None)
    if store is None:
        raise HTTPException(503, "服务未就绪")
    return store


# ---------------------------------------------------------------------------
# 模型列表（登录用户可读）
# ---------------------------------------------------------------------------
class ModelItem(BaseModel):
    model_id: str = Field(..., description="模型 ID（透传给 LLM 服务商）")
    label: str = Field(..., description="显示名称")


class ModelsConfig(BaseModel):
    available_models: List[ModelItem] = Field(..., min_length=1)
    default_model: str = Field(..., description="默认模型 ID（须在列表中）")


@router.get("/agent/models")
def list_models(request: Request):
    """可用模型列表与默认模型（前端模型选择器数据源；未配置时返回内置默认）"""
    store = _get_config_store(request)
    cfg = store.get(CONFIG_ID) or {}
    models = cfg.get("available_models") or DEFAULT_MODELS
    default_model = cfg.get("default_model") or (models[0]["model_id"] if models else "")
    return {"models": models, "default_model": default_model}


@router.put("/admin/models")
def update_models(req: ModelsConfig, request: Request, _admin=Depends(require_admin)):
    """更新可用模型列表与默认模型（管理员）"""
    store = _get_config_store(request)
    ids = [m.model_id for m in req.available_models]
    if req.default_model not in ids:
        raise HTTPException(400, f"default_model 必须在模型列表中: {ids}")
    store.update(CONFIG_ID, {
        "available_models": [m.model_dump() for m in req.available_models],
        "default_model": req.default_model,
    })
    logger.info(f"models_updated by {_admin['username']}: {[m.model_id for m in req.available_models]}")
    return {"status": "ok", "models": [m.model_dump() for m in req.available_models], "default_model": req.default_model}


# ---------------------------------------------------------------------------
# LLM 服务商配置（管理员）
# ---------------------------------------------------------------------------
class LLMConfigUpdate(BaseModel):
    llm_base_url: Optional[str] = Field(default=None, description="OpenAI 兼容 base_url")
    llm_api_key: Optional[str] = Field(default=None, description="API Key（留空不修改）")


def _mask_key(key: str) -> str:
    if not key:
        return ""
    return key[:6] + "****" + key[-4:] if len(key) > 12 else "****"


@router.get("/admin/llm-config")
def get_llm_config(request: Request, _admin=Depends(require_admin)):
    """查看 LLM 服务商配置（Key 脱敏）"""
    store = _get_config_store(request)
    cfg = store.get(CONFIG_ID) or {}
    llm = getattr(request.app.state, "llm_manager", None)
    return {
        "llm_base_url": cfg.get("llm_base_url", ""),
        "llm_api_key_masked": _mask_key(cfg.get("llm_api_key", "")),
        "llm_available": bool(llm and llm.is_available()),
        "model": cfg.get("default_model", ""),
    }


@router.put("/admin/llm-config")
def update_llm_config(req: LLMConfigUpdate, request: Request, _admin=Depends(require_admin)):
    """在线更新 LLM 服务商配置（立即生效并持久化；Key 留空表示不修改）"""
    store = _get_config_store(request)
    cfg = store.get(CONFIG_ID) or {}
    patch = {}

    if req.llm_base_url:
        patch["llm_base_url"] = req.llm_base_url.strip()
    if req.llm_api_key:
        patch["llm_api_key"] = req.llm_api_key.strip()

    if not patch:
        raise HTTPException(400, "未提供任何要更新的字段")

    new_cfg = {**cfg, **patch}
    store.update(CONFIG_ID, patch)

    # 运行时热更新：重新注册 LLM provider
    llm = getattr(request.app.state, "llm_manager", None)
    if llm:
        llm.register(
            "openai_compatible",
            api_key=new_cfg.get("llm_api_key", ""),
            base_url=new_cfg.get("llm_base_url", ""),
            model=new_cfg.get("default_model", ""),
        )

    logger.info(f"llm_config_updated by {_admin['username']}: base_url={patch.get('llm_base_url', '(unchanged)')}")
    return {
        "status": "ok",
        "llm_base_url": new_cfg.get("llm_base_url", ""),
        "llm_api_key_masked": _mask_key(new_cfg.get("llm_api_key", "")),
        "llm_available": bool(llm and llm.is_available()),
    }
