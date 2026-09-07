"""
LLM 管理器 —— 多服务商注册表 + 统一调用接口

用法:
    llm = LLMManager()
    llm.register("deepseek", api_key="sk-xxx", base_url="https://api.deepseek.com/v1", model="deepseek-chat")

    # 流式
    for chunk in llm.chat_stream(messages=[{"role":"user","content":"你好"}]):
        print(chunk, end="")
"""
import json
import logging
import time
from typing import Optional, List, Dict, Generator
import requests

from shared.http_client import ensure_utf8_encoding
from shared.metrics import llm_token_counter

logger = logging.getLogger("shared.llm")


class LLMError(RuntimeError):
    """LLM 调用失败（网络异常 / HTTP 错误 / 输出无法解析为 JSON）"""


class LLMManager:
    """多服务商 LLM 注册表 (shared 模块 —— 全平台复用)"""

    def __init__(self, default_provider: str = "openai_compatible"):
        self.default_provider = default_provider
        # 未显式传 model 时使用的默认模型 id（由管理员配置下发）。
        # 命中 _model_routes 时按路由走，否则回退 default_provider，保持旧行为。
        self.default_model: Optional[str] = None
        self._providers: Dict[str, dict] = {}
        # model_id → provider_name 路由表（多模型接入用）。
        # 例：register_model_route("hy-mt2-pro", "tencent_maas") 后，
        # 任何带 model="hy-mt2-pro" 的调用都会走 tencent_maas 而非默认 provider。
        self._model_routes: Dict[str, str] = {}
        # 每次调用统计（耗时 + token）；埋点用，供 ItineraryGenerator 收集阶段耗时。
        # 由 chat/chat_json/chat_stream 写入；用 monotonic 计时，不受系统时间跳变影响。
        self._last_stats: Optional[Dict] = None

    def register(
        self,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        extra_headers: dict = None,
    ):
        self._providers[name] = {
            "api_key": api_key,
            "base_url": base_url.rstrip("/"),
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_headers": extra_headers or {},
        }
        logger.info(f"LLM provider registered: {name} ({model})")

    def register_model_route(self, model_id: str, provider_name: str):
        """把 model_id 路由到指定已注册 provider。

        调用方只需传 model="hy-mt2-pro"，无需关心底层是哪个服务商/key。
        未命中路由时回退到 default_provider（保持旧行为兼容）。
        """
        if provider_name not in self._providers:
            raise ValueError(f"路由目标 provider 未注册: {provider_name}。可用: {self.list_providers()}")
        self._model_routes[model_id] = provider_name
        logger.info(f"LLM model route: {model_id} -> {provider_name}")

    def get_last_stats(self) -> Optional[Dict]:
        """获取最近一次 chat / chat_json / chat_stream 调用的耗时与 token 统计。

        调用方（如行程生成器）在调用后立即读取，再调用会被覆盖。
        返回字典字段：duration_ms, model, prompt_tokens, completion_tokens,
        total_tokens, finish_reason, first_chunk_ms(仅流式), chunks(仅流式)。
        """
        return self._last_stats

    def chat(
        self,
        messages: List[Dict[str, str]],
        provider: str = None,
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
        timeout: int = 120,
        response_format: dict = None,
    ) -> str:
        cfg = self._get_config(provider, model)
        url = f"{cfg['base_url']}/chat/completions"

        payload = {
            "model": model or cfg["model"],
            "messages": messages,
            "temperature": temperature if temperature is not None else cfg["temperature"],
            "max_tokens": max_tokens or cfg["max_tokens"],
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            **cfg["extra_headers"],
        }

        logger.debug(f"LLM chat: provider={provider or self.default_provider}, model={cfg['model']}")
        t0 = time.monotonic()
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        # 响应未声明 charset 时强制 UTF-8 解码，避免中文乱码
        ensure_utf8_encoding(resp)
        data = resp.json()
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Token 用量追踪
        usage = data.get("usage", {})
        if usage:
            model_name = cfg["model"]
            llm_token_counter.labels(model=model_name, type="prompt").inc(usage.get("prompt_tokens", 0))
            llm_token_counter.labels(model=model_name, type="completion").inc(usage.get("completion_tokens", 0))

        content = data["choices"][0]["message"].get("content") or ""
        finish = data["choices"][0].get("finish_reason")
        # 埋点：每次调用都记录（chat_json 重试时会被最新一次覆盖）
        self._last_stats = {
            "duration_ms": duration_ms,
            "model": cfg["model"],
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "finish_reason": finish,
            "stream": False,
        }
        if not content.strip():
            # 推理模型（MiMo 等）思考 token 计入 max_tokens：思考烧光预算时正文为空、
            # finish_reason=length。显式报错让上层 chat_json 用更大预算重试。
            raise ValueError(f"LLM 返回空内容 (finish_reason={finish}，思考可能耗尽 max_tokens)")
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        provider: str = None,
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
        timeout: int = 120,
    ) -> dict:
        """调用 LLM 并返回 JSON 对象（强制 response_format=json_object）。

        网络/HTTP 异常或输出非法 JSON 时重试一次，仍失败抛 LLMError。
        注意：推理类模型（如 MiMo）会先消耗 token 思考再输出正文，且思考 token
        计入 max_tokens —— 实测简单参数提取的思考量就有 600~1700 token，
        预算不足时正文为空。因此下限抬高到 4096，且重试时预算翻倍。
        """
        max_tokens = max(max_tokens or 0, 4096)
        last_error: Optional[Exception] = None
        for attempt in range(2):
            if attempt:
                time.sleep(1)
                max_tokens *= 2  # 首次多为思考预算不足，重试翻倍提高成功率
            try:
                text = self.chat(
                    messages=messages,
                    provider=provider,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    response_format={"type": "json_object"},
                )
                # 清理可能的 markdown 代码块包裹
                text = text.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    # 兜底：部分模型输出带前导说明或格式瑕疵，提取首个 {...} 块重解析
                    import re as _re
                    match = _re.search(r"\{.*\}", text, _re.DOTALL)
                    if match:
                        return json.loads(match.group(0))
                    raise
            except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
                last_error = e
                logger.warning(f"chat_json 第 {attempt + 1} 次尝试失败: {e}")
        raise LLMError(f"LLM JSON 输出获取/解析失败（已重试）: {last_error}")

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        provider: str = None,
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
        timeout: int = 120,
    ) -> Generator[str, None, None]:
        cfg = self._get_config(provider, model)
        url = f"{cfg['base_url']}/chat/completions"

        payload = {
            "model": model or cfg["model"],
            "messages": messages,
            "temperature": temperature if temperature is not None else cfg["temperature"],
            "max_tokens": max_tokens or cfg["max_tokens"],
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            **cfg["extra_headers"],
        }

        logger.debug(f"LLM stream: provider={provider or self.default_provider}")
        t0 = time.monotonic()
        first_chunk_ms: Optional[int] = None
        chunks = 0
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        finish_reason = None
        model_id = model or cfg["model"]
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout, stream=True)
            resp.raise_for_status()

            # 响应未声明 charset 时强制 UTF-8 解码，否则中文变 latin-1 乱码
            ensure_utf8_encoding(resp)

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    choices = data.get("choices") or []
                    # 部分服务商（如 MiMo）会把 usage 放在无 choices 的尾帧里
                    usage_block = data.get("usage")
                    if usage_block:
                        prompt_tokens = usage_block.get("prompt_tokens", prompt_tokens)
                        completion_tokens = usage_block.get("completion_tokens", completion_tokens)
                        total_tokens = usage_block.get("total_tokens", total_tokens)
                    if not choices:
                        # 部分服务商（如 MiMo）会发送空 choices 帧（如思考阶段元信息），跳过
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content") or ""
                    if content:
                        if first_chunk_ms is None:
                            first_chunk_ms = int((time.monotonic() - t0) * 1000)
                        chunks += 1
                        yield content
                    # 记录 finish_reason（通常在最后一帧）
                    fr = choices[0].get("finish_reason")
                    if fr:
                        finish_reason = fr
                except json.JSONDecodeError:
                    continue

            duration_ms = int((time.monotonic() - t0) * 1000)
            self._last_stats = {
                "duration_ms": duration_ms,
                "model": model_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "finish_reason": finish_reason,
                "stream": True,
                "first_chunk_ms": first_chunk_ms,
                "chunks": chunks,
            }
            # 累计到 Prometheus
            if total_tokens:
                llm_token_counter.labels(model=model_id, type="prompt").inc(prompt_tokens)
                llm_token_counter.labels(model=model_id, type="completion").inc(completion_tokens)

        except requests.RequestException as e:
            # 错误文本不能作为正文 chunk yield——会混入下游的行程 JSON 导致解析失败。
            # 抛出让调用方（生成器/API 层）走各自的降级与错误帧协议。
            duration_ms = int((time.monotonic() - t0) * 1000)
            self._last_stats = {
                "duration_ms": duration_ms,
                "model": model_id,
                "error": str(e),
                "stream": True,
                "first_chunk_ms": first_chunk_ms,
                "chunks": chunks,
            }
            logger.error(f"LLM call failed: {e}")
            raise LLMError(f"LLM 调用失败: {e}") from e

    def is_available(self) -> bool:
        """检查 LLM 是否可用（有注册的服务商且 key 非空）"""
        for cfg in self._providers.values():
            if cfg.get("api_key"):
                return True
        return False

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    def _get_config(self, provider: str = None, model: str = None) -> dict:
        # 优先按 model_id 路由（多模型接入）：model="hy-mt2-pro" → 对应 provider
        # 未显式传 model 时，回落到管理员配置的 default_model，
        # 保证「下拉框默认模型」与「不传参时的实际调用模型」一致。
        model = model or self.default_model
        if model and model in self._model_routes:
            provider = self._model_routes[model]
        name = provider or self.default_provider
        if name not in self._providers:
            raise ValueError(f"未注册的 LLM 服务商: {name}。可用: {self.list_providers()}")
        return self._providers[name]
