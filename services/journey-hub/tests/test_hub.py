"""
行智 · Journey Hub 单元测试
"""
import sys
import os
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router.intent import IntentRouter, Intent
from tools.registry import ToolRegistry, ToolResult
from tools.handlers import ToolHandlers
from memory.session import SessionManager


class TestIntentRouter:
    """意图路由测试"""

    def setup_method(self):
        self.router = IntentRouter()

    def test_plan_intent(self):
        assert self.router.classify("帮我规划北京三日游") == Intent.PLAN
        assert self.router.classify("安排一下行程") == Intent.PLAN
        assert self.router.classify("去上海玩") == Intent.PLAN

    def test_manage_intent(self):
        assert self.router.classify("查看我的行程") == Intent.MANAGE
        assert self.router.classify("取消行程") == Intent.MANAGE
        assert self.router.classify("删除行程") == Intent.MANAGE
        assert self.router.classify("把西安3日游改名为西安古城之旅") == Intent.MANAGE
        assert self.router.classify("重命名行程") == Intent.MANAGE

    def test_chat_intent(self):
        assert self.router.classify("附近有什么好吃的") == Intent.CHAT
        assert self.router.classify("签证怎么办") == Intent.CHAT
        assert self.router.classify("你好") == Intent.CHAT


class TestToolRegistry:
    """工具注册表测试"""

    def test_register_and_execute(self):
        registry = ToolRegistry()

        def dummy_handler(query, **kwargs):
            return ToolResult(data="test result")

        registry.register("test_tool", dummy_handler, description="测试工具")
        result = registry.execute("test_tool", query="hello")
        assert result["success"]
        assert result["data"] == "test result"

    def test_unknown_tool(self):
        registry = ToolRegistry()
        result = registry.execute("nonexistent", query="hello")
        assert not result["success"]


class TestSessionManager:
    """会话管理器测试"""

    def setup_method(self):
        self.manager = SessionManager()

    def test_append_and_get(self):
        self.manager.append("s1", "user", "你好")
        self.manager.append("s1", "assistant", "你好！有什么可以帮你的？")
        history = self.manager.get_history("s1")
        assert len(history) == 2

    def test_isolation(self):
        self.manager.append("s1", "user", "会话1")
        self.manager.append("s2", "user", "会话2")
        h1 = self.manager.get_history("s1")
        h2 = self.manager.get_history("s2")
        assert h1[0]["content"] == "会话1"
        assert h2[0]["content"] == "会话2"

    def test_clear(self):
        self.manager.append("s1", "user", "test")
        self.manager.clear("s1")
        history = self.manager.get_history("s1")
        assert len(history) == 0

    def test_max_history_trim(self):
        manager = SessionManager(max_history=5)
        for i in range(10):
            manager.append("s1", "user", f"msg_{i}")
        history = manager.get_history("s1", last_n=100)
        assert len(history) <= 5
