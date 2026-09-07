"""
服务间 HTTP 客户端 (shared 模块)

用法:
    from shared.http_client import ServiceClient

    client = ServiceClient()
    result = client.get("http://planner-core:8002/trips")
    result = client.post("http://planner-core:8002/trips/generate", json={"query": "..."})
"""
import json as _json
import logging
import os
import time
from typing import Optional, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("shared.http")


def ensure_utf8_encoding(resp) -> None:
    """响应未声明 charset 时强制按 UTF-8 解码。

    requests 对无 charset 的 text/* 响应按 RFC 2616 回退 ISO-8859-1 解码，
    导致 UTF-8 中文变成 latin-1 乱码（如 "深圳" → "æ·±å³"）。
    服务端统一用 UTF-8，LLM / 服务间调用响应都适用。
    """
    declared = (resp.headers.get("Content-Type") or "").lower()
    if "charset" not in declared:
        resp.encoding = "utf-8"


class ServiceClient:
    """服务间调用客户端 - 连接池复用 + 自动重试 + 统一超时"""

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        api_key: str = None,
    ):
        self.timeout = timeout

        # 服务间调用默认携带鉴权头，保证目标服务的 APIKeyAuth 中间件放行
        self.default_headers = {}
        api_key = api_key or os.environ.get("DEV_API_KEY", "ak_dev_local")
        if api_key:
            self.default_headers["X-API-Key"] = api_key

        # 重试策略：仅对网关类 5xx / 连接错误重试（不含 404 等业务错误）
        self._retry = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "HEAD", "POST", "PUT", "DELETE"],
        )

    def _new_session(self) -> requests.Session:
        """每次请求新建并关闭的 Session。

        关键修复：本地/同机部署下，uvicorn 对 keep-alive 持久连接的复用会偶发返回
        404（连接已被服务端半关但客户端仍复用），导致服务间 GET/DELETE 调用失败。
        每次新建连接（与 curl 行为一致）可彻底规避，对低频服务间调用性能影响可忽略。
        """
        s = requests.Session()
        adapter = HTTPAdapter(max_retries=self._retry)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update(self.default_headers)
        return s

    def _request(self, method: str, url: str, headers: dict = None, **kwargs) -> Dict[str, Any]:
        """统一请求入口：合并鉴权头、校验状态码、记录耗时、解析 JSON"""
        start = time.time()
        merged_headers = {**self.default_headers, **(headers or {})}
        try:
            with self._new_session() as s:
                resp = s.request(method, url, headers=merged_headers, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                elapsed = (time.time() - start) * 1000
                logger.debug(f"{method} {url} → {resp.status_code} ({elapsed:.0f}ms)")
                return resp.json()
        except requests.RequestException as e:
            elapsed = (time.time() - start) * 1000
            logger.error(f"{method} {url} FAILED after {elapsed:.0f}ms: {e}")
            raise

    def get(self, url: str, params: dict = None, headers: dict = None) -> Dict[str, Any]:
        return self._request("GET", url, params=params, headers=headers)

    def post(self, url: str, json: dict = None, data: dict = None, headers: dict = None) -> Dict[str, Any]:
        return self._request("POST", url, json=json, data=data, headers=headers)

    def put(self, url: str, json: dict = None, headers: dict = None) -> Dict[str, Any]:
        return self._request("PUT", url, json=json, headers=headers)

    def delete(self, url: str, headers: dict = None) -> Dict[str, Any]:
        return self._request("DELETE", url, headers=headers)

    def post_stream(self, url: str, json: dict = None, headers: dict = None, timeout: int = 120):
        """
        POST 并消费 SSE 流，逐帧 yield 解析后的事件 dict。
        遇到 `data: [DONE]` 或流结束时终止。
        """
        merged_headers = {**self.default_headers, **(headers or {})}
        with self._new_session() as s:
            with s.post(
                url, json=json, headers=merged_headers, stream=True, timeout=timeout
            ) as resp:
                resp.raise_for_status()
                ensure_utf8_encoding(resp)
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        return
                    try:
                        yield _json.loads(data)
                    except ValueError:
                        logger.debug(f"非 JSON SSE 帧: {data[:80]}")
                        continue

    def health_check(self, url: str) -> bool:
        """检查服务是否健康"""
        try:
            with self._new_session() as s:
                resp = s.get(f"{url.rstrip('/')}/health", timeout=5)
                return resp.status_code == 200
        except Exception:
            return False
