"""政策外接服务 —— Agent 工具出口（经工具总线注册给 Agent）"""
from core.agent.registry import ToolResult
from .service import PolicyService


def register_tools(registry, service: PolicyService):
    """把政策能力注册为 Agent 工具（v3：政策=外接服务，Agent 经总线调用）"""

    def policy_check(trip: dict, employee: dict = None) -> ToolResult:
        """差旅政策预检：返回违规项与结论文本（不审批）"""
        if not isinstance(trip, dict) or not trip:
            return ToolResult(data="没有可检查的行程草案。", success=False)
        event = service.preview_trip(trip, employee)
        if not event:
            return ToolResult(data="本次行程无需政策检查（个人出游或无匹配政策）。")
        mark = "⚠️" if event.get("has_violations") else "✅"
        lines = [f"{mark} 政策：{event.get('policy_name', '')} —— {event.get('content', '')}"]
        for v in event.get("violations") or []:
            lines.append(f"  · {v}")
        return ToolResult(data="\n".join(lines), success=True)

    def policy_docs_search(query: str, top_k: int = 3) -> ToolResult:
        """差旅政策文档 RAG 检索：返回原文摘录，供引用作答"""
        if not (query or "").strip():
            return ToolResult(data="请提供要检索的政策问题。", success=False)
        res = service.search_docs(query, top_k=top_k)
        docs = res.get("documents") or []
        if not docs:
            return ToolResult(data=f"政策知识库中未找到与「{query}」相关的内容。", success=False)
        lines = [f"检索模式：{res.get('mode')}"]
        for d in docs:
            excerpt = d.get("excerpt") or (d.get("content") or "")[:120]
            lines.append(f"《{d.get('title', '政策文档')}》{excerpt}")
        return ToolResult(data="\n".join(lines))

    registry.register("policy_check", policy_check, "差旅政策预检（违规项检查，不审批）")
    registry.register(
        "policy_docs_search", policy_docs_search,
        "差旅政策文档检索（RAG，返回原文摘录供引用）",
    )
