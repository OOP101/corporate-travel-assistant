"""
工具注册表 —— Agent 可用的全部工具

工具分类：
  1. plan_trip   → 调生成管线产出行程草案
  2. chat_query  → 用 LLM 回答旅行相关问题
  3. manage_trip → 直读直写行程存储

所有工具均通过 ToolRegistry 统一注册与调度。
"""
import logging
from typing import Dict, Any, Callable, List

logger = logging.getLogger("core.agent.registry")


class ToolResult:
    """工具执行结果"""

    def __init__(self, data: str, success: bool = True, requires_approval: bool = False):
        self.data = data
        self.success = success
        self.requires_approval = requires_approval

    def to_dict(self) -> dict:
        return {
            "data": self.data,
            "success": self.success,
            "requires_approval": self.requires_approval,
        }


class ToolRegistry:
    """
    Agent 工具注册表

    每个工具包含：
      - handler: 执行函数
      - description: 描述
      - requires_approval: 是否需要人工审批
    """

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        requires_approval: bool = False,
    ):
        """注册工具"""
        self._tools[name] = {
            "handler": handler,
            "description": description,
            "requires_approval": requires_approval,
        }
        logger.info(f"Tool registered: {name} (approval={requires_approval})")

    def execute(self, tool_name: str, **kwargs) -> dict:
        """
        执行工具

        Args:
            tool_name: 工具名
            **kwargs: 传递给 handler 的参数

        Returns:
            {"data": str, "success": bool, "requires_approval": bool}
        """
        if tool_name not in self._tools:
            return ToolResult(
                data=f"未知工具: {tool_name}。可用工具: {self.list_tool_names()}",
                success=False,
            ).to_dict()

        tool = self._tools[tool_name]
        try:
            result = tool["handler"](**kwargs)
            if isinstance(result, ToolResult):
                return result.to_dict()
            if isinstance(result, dict):
                return result
            return ToolResult(
                data=str(result),
                requires_approval=tool["requires_approval"],
            ).to_dict()
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return ToolResult(data=f"工具执行失败: {e}", success=False).to_dict()

    def get_handler(self, tool_name: str):
        """获取工具原始 handler（供流式透传等非 execute 场景使用）"""
        tool = self._tools.get(tool_name)
        return tool["handler"] if tool else None

    def list_tools(self) -> List[tuple]:
        """返回 [(name, description), ...]"""
        return [(name, info["description"]) for name, info in self._tools.items()]

    def list_tool_names(self) -> List[str]:
        """返回已注册工具名列表"""
        return list(self._tools.keys())

    def get_requires_approval(self, tool_name: str) -> bool:
        """查询工具是否需要审批"""
        return self._tools.get(tool_name, {}).get("requires_approval", False)
