"""行程模板 Router —— 模板保存 / 查询 / 应用 (PRD F4.3 / 7.5)"""
import copy

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api import deps

router = APIRouter()


class SaveTemplateRequest(BaseModel):
    template_name: str = Field(..., description="模板名称")
    tags: list = Field(default_factory=list, description="标签 城市/天数/风格/季节")


class ApplyTemplateRequest(BaseModel):
    user_id: str = Field(default=None, description="新行程归属用户 (默认当前用户)")
    overrides: dict = Field(default_factory=dict, description="覆盖字段 如 title/budget_total/start_date")


@router.post("/trips/{trip_id}/template", tags=["行程模板"])
async def save_trip_as_template(
    trip_id: str,
    req: SaveTemplateRequest,
    session_id: str = Query(default=""),
):
    """
    保存行程为模板。

    body: {"template_name": "成都3日亲子", "tags": ["成都","3天","亲子"]}
    会复制行程快照并附加模板元数据 (template_id / template_name / tags)。
    """
    trip = deps.trip_store.get(trip_id)
    if not trip:
        raise HTTPException(404, f"行程不存在: {trip_id}")
    owner = trip.get("user_id") or ""
    if session_id and owner and session_id != owner:
        raise HTTPException(404, f"行程不存在: {trip_id}")

    template = deps.template_store.save_as_template(
        trip,
        template_name=req.template_name,
        tags=req.tags,
    )
    return {
        "status": "ok",
        "template_id": template["template_id"],
        "template": template,
    }


@router.get("/templates", tags=["行程模板"])
async def list_templates(tags: str = Query(default="", description="逗号分隔标签 如 成都,亲子")):
    """
    模板列表，支持 ?tags=成都,亲子 过滤 (OR 语义：匹配任一标签即返回)。
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    templates = deps.template_store.list_templates(tags=tag_list)
    return {"templates": templates, "count": len(templates)}


@router.get("/templates/{template_id}", tags=["行程模板"])
async def get_template(template_id: str):
    """模板详情"""
    template = deps.template_store.get_template(template_id)
    if not template:
        raise HTTPException(404, f"模板不存在: {template_id}")
    return template


@router.post("/templates/{template_id}/apply", tags=["行程模板"])
async def apply_template(template_id: str, req: ApplyTemplateRequest, request: Request):
    """
    基于模板创建新行程。

    - 复制模板快照，清空模板元数据，生成新 trip_id。
    - 用 req.overrides 覆盖字段 (如 title/budget_total/start_date)。
    - 用 req.user_id 或当前 workspace 作为归属用户。
    """
    template = deps.template_store.get_template(template_id)
    if not template:
        raise HTTPException(404, f"模板不存在: {template_id}")

    # 深拷贝模板，去除模板专有字段
    new_trip = copy.deepcopy(template)
    for key in ("template_id", "template_name", "tags", "source_trip_id"):
        new_trip.pop(key, None)

    # 覆盖字段
    overrides = req.overrides or {}
    new_trip.update(overrides)

    # 归属用户
    user_id = req.user_id or getattr(request.state, "workspace_id", "default")
    new_trip["user_id"] = user_id

    # 保存为新行程 (TripStore.save 会生成 trip_id 与时间戳)
    trip_id = deps.trip_store.save(new_trip)
    saved = deps.trip_store.get(trip_id)
    return {
        "status": "ok",
        "template_id": template_id,
        "trip_id": trip_id,
        "trip": saved,
    }


@router.delete("/templates/{template_id}", tags=["行程模板"])
async def delete_template(template_id: str):
    """删除模板"""
    deleted = deps.template_store.delete_template(template_id)
    if not deleted:
        raise HTTPException(404, f"模板不存在: {template_id}")
    return {"status": "ok", "template_id": template_id}
