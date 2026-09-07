"""
Prometheus 指标定义 (shared 模块)

用法:
    from shared.metrics import (
        agent_request_duration,
        tool_call_counter,
        llm_token_counter,
        node_duration,
        trip_generation_duration,
        alert_pushed_counter,
    )
"""
import time
from contextlib import contextmanager

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


class _NoopMetric:
    """Prometheus 不可用时的空实现"""
    def labels(self, **kwargs):
        return self
    def inc(self, amount=1):
        pass
    def observe(self, amount):
        pass
    def set(self, amount):
        pass
    def time(self):
        return _noop_context()

    def __call__(self, func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper


@contextmanager
def _noop_context():
    yield


if PROMETHEUS_AVAILABLE:
    agent_request_duration = Histogram(
        "agent_request_duration_seconds",
        "Agent request latency",
        ["service", "intent"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
    )

    tool_call_counter = Counter(
        "agent_tool_calls_total",
        "Total tool call count",
        ["tool", "status"],
    )

    llm_token_counter = Counter(
        "agent_llm_tokens_total",
        "Total LLM token usage",
        ["model", "type"],
    )

    node_duration = Histogram(
        "agent_node_duration_seconds",
        "LangGraph node execution latency",
        ["service", "node"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
    )

    active_sessions = Gauge(
        "agent_active_sessions",
        "Number of active sessions",
        ["service"],
    )

    trip_generation_duration = Histogram(
        "trip_generation_duration_seconds",
        "Trip generation latency",
        ["status"],
        buckets=[1, 5, 10, 20, 30, 60],
    )

    alert_pushed_counter = Counter(
        "alert_pushed_total",
        "Total alerts pushed to users",
        ["type", "severity"],
    )

    monitor_check_counter = Counter(
        "monitor_checks_total",
        "Total monitor source checks",
        ["source", "status"],
    )

    http_requests_total = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["service", "method", "path", "status"],
    )

    http_request_duration = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency",
        ["service", "method", "path"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
    )

else:
    agent_request_duration = _NoopMetric()
    tool_call_counter = _NoopMetric()
    llm_token_counter = _NoopMetric()
    node_duration = _NoopMetric()
    active_sessions = _NoopMetric()
    trip_generation_duration = _NoopMetric()
    alert_pushed_counter = _NoopMetric()
    monitor_check_counter = _NoopMetric()
    http_requests_total = _NoopMetric()
    http_request_duration = _NoopMetric()


def get_metrics_response():
    """返回 Prometheus 格式的指标"""
    if PROMETHEUS_AVAILABLE:
        return generate_latest(), CONTENT_TYPE_LATEST
    return b"# Prometheus client not installed\n", "text/plain"
