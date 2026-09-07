"""
会话管理器

支持会话隔离、上下文记忆、轮数裁剪。
"""
import time
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("journey-hub.session")


@dataclass
class SessionMessage:
    """单条会话消息"""
    role: str          # user | assistant | tool
    content: str
    timestamp: float = field(default_factory=time.time)


class SessionManager:
    """
    会话管理器

    支持 session_id 隔离、多轮对话上下文、自动裁剪。
    """

    def __init__(self, max_history: int = 20, max_tokens_estimate: int = 4000):
        self.max_history = max_history
        self.max_tokens_estimate = max_tokens_estimate
        self._sessions: Dict[str, List[SessionMessage]] = {}
        self._metadata: Dict[str, dict] = {}

    def append(self, session_id: str, role: str, content: str):
        """追加一条对话消息"""
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        self._sessions[session_id].append(
            SessionMessage(role=role, content=content)
        )

        # 裁剪：保留最近 max_history 条
        if len(self._sessions[session_id]) > self.max_history:
            self._sessions[session_id] = self._sessions[session_id][-self.max_history:]

    def get_history(self, session_id: str, last_n: int = 10) -> List[Dict[str, str]]:
        """获取最近 N 轮对话"""
        messages = self._sessions.get(session_id, [])
        history = []
        for msg in messages[-last_n:]:
            history.append({"role": msg.role, "content": msg.content})
        return history

    def get_context_prompt(self, session_id: str, max_chars: int = 2000) -> str:
        """获取格式化的上下文提示词"""
        history = self.get_history(session_id, last_n=5)
        if not history:
            return ""

        lines = ["以下是最近的对话历史："]
        total = 0
        for msg in reversed(history):
            line = f"[{msg['role']}]: {msg['content'][:200]}"
            total += len(line)
            if total > max_chars:
                break
            lines.append(line)

        return "\n".join(reversed(lines))

    def clear(self, session_id: str):
        """清除会话"""
        self._sessions.pop(session_id, None)
        self._metadata.pop(session_id, None)

    def list_sessions(self) -> list:
        """活跃会话概览（调试用）：[{session_id, message_count, last_message}]"""
        sessions = []
        for sid, messages in self._sessions.items():
            sessions.append({
                "session_id": sid,
                "message_count": len(messages),
                "last_message": messages[-1].content[:100] if messages else "",
            })
        return sessions

    def set_metadata(self, session_id: str, key: str, value):
        """设置会话元数据"""
        if session_id not in self._metadata:
            self._metadata[session_id] = {}
        self._metadata[session_id][key] = value

    def get_metadata(self, session_id: str, key: str, default=None):
        """读取会话元数据"""
        return self._metadata.get(session_id, {}).get(key, default)
