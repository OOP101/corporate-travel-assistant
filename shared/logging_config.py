"""
统一日志配置 (shared 模块)

用法:
    from shared.logging_config import setup_logging
    setup_logging(level="INFO", service="core")
"""
import logging
import sys
import json
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """结构化 JSON 日志格式"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "unknown"),
            "module": record.name,
            "message": record.getMessage(),
            "line": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key not in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName", "service",
            }:
                log_entry[key] = value

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """开发环境可读格式"""

    def format(self, record: logging.LogRecord) -> str:
        service = getattr(record, "service", "unknown")
        return (
            f"[{self.formatTime(record)}] "
            f"[{record.levelname:<5}] "
            f"[{service}] "
            f"{record.getMessage()}"
        )


def setup_logging(
    level: str = "INFO",
    service: str = "unknown",
    use_json: bool = False,
):
    """配置全局日志"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = JSONFormatter() if use_json else ConsoleFormatter()
    handler.setFormatter(formatter)
    root.addHandler(handler)

    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.service = service
        return record

    logging.setLogRecordFactory(record_factory)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
