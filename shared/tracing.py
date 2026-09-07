"""
链路追踪 (shared 模块)

用法:
    from shared.tracing import TraceContext, traced

    ctx = TraceContext(session_id="abc123")

    with traced(ctx, "route_intent"):
        result = route(state)

    with traced(ctx, "llm_call", attrs={"model": "deepseek-chat", "tokens": 500}):
        answer = llm.chat(messages)
"""
import time
import uuid
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("shared.tracing")


@dataclass
class Span:
    name: str
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    attrs: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str = ""

    @property
    def duration_ms(self) -> float:
        end = self.ended_at or time.time()
        return (end - self.started_at) * 1000

    def finish(self, status: str = "ok", error: str = ""):
        self.ended_at = time.time()
        self.status = status
        self.error = error


@dataclass
class TraceContext:
    """单次请求的追踪上下文"""
    session_id: str = ""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    spans: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def log(self):
        """输出结构化日志"""
        total_ms = (time.time() - self.created_at) * 1000
        span_data = []
        for s in self.spans:
            span_data.append({
                "name": s.name,
                "duration_ms": round(s.duration_ms, 1),
                "status": s.status,
                "attrs": s.attrs,
            })

        logger.info("trace_complete", extra={
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "total_ms": round(total_ms, 1),
            "span_count": len(self.spans),
            "spans": span_data,
        })


@contextmanager
def traced(ctx: TraceContext, span_name: str, attrs: Dict[str, Any] = None):
    """创建 span 并记录耗时"""
    span = Span(name=span_name, attrs=attrs or {})
    try:
        yield span
        span.finish("ok")
    except Exception as e:
        span.finish("error", str(e))
        raise
    finally:
        ctx.spans.append(span)
        logger.debug(f"[trace={ctx.trace_id}] {span_name} → {span.duration_ms:.1f}ms ({span.status})")
