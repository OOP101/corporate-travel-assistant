"""
LLM 数据模型
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChatMessage:
    role: str          # system | user | assistant
    content: str


@dataclass
class ChatResponse:
    content: str
    model: str
    usage: Optional[dict] = None
    finish_reason: str = "stop"
