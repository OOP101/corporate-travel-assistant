"""
共享 Embedding 模块 —— 可插拔向量化能力

支持三种后端，按配置自动选择，全部不可用时降级为「无向量」，
由调用方回落到关键词检索（与项目现有的 Mock/规则降级策略保持一致）：

  1. local : sentence-transformers 加载 BAAI/bge-large-zh-v1.5
             （需 pip install sentence-transformers，数据不出企业，适合私有化部署）
  2. api   : OpenAI 兼容 /embeddings 接口（如 TokenHub kinfra-text-embedding）
             （零额外依赖，需控制台开通该模型权限）
  3. none  : 不启用，全部调用返回空向量

选型说明：默认 local 模型为 BAAI/bge-large-zh-v1.5（MTEB 中文榜前列）。
注意 bge 系列维度：small=512 / base=768 / large=1024，large 并非 512 维。
"""
import math
import logging
from typing import List, Sequence, Optional

logger = logging.getLogger("shared.embedding")

# bge 系列维度对照（便于按成本选择规格）
BGE_DIMS = {
    "BAAI/bge-small-zh-v1.5": 512,
    "BAAI/bge-base-zh-v1.5": 768,
    "BAAI/bge-large-zh-v1.5": 1024,
}

DEFAULT_LOCAL_MODEL = "BAAI/bge-large-zh-v1.5"


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度，维度不一致或空向量返回 0"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class BaseEmbeddingProvider:
    """Embedding 后端基类"""

    name = "base"
    dim = 0

    def is_available(self) -> bool:
        return True

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class NoneEmbeddingProvider(BaseEmbeddingProvider):
    """不启用向量（降级态）"""

    name = "none"

    def is_available(self) -> bool:
        return False

    def embed(self, texts: List[str]) -> List[List[float]]:
        return []


class ApiEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI 兼容 /embeddings 接口"""

    name = "api"

    def __init__(self, base_url: str, api_key: str, model: str, dim: int = 0, timeout: int = 30):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.dim = dim
        self.timeout = timeout

    def is_available(self) -> bool:
        if not (self.base_url and self.api_key and self.model):
            return False
        # 本地模型名（如 BAAI/bge-large-zh-v1.5）不是合法的 API 模型 id，
        # 直接判定不可用，避免每次检索都打一次必失败的请求
        if "/" in self.model:
            logger.debug(f"模型名 {self.model!r} 为本地模型路径，api 模式不可用")
            return False
        return True

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts or not self.is_available():
            return []
        import httpx

        resp = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model, "input": list(texts)},
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = sorted(payload.get("data", []), key=lambda d: d.get("index", 0))
        vectors = [r.get("embedding", []) for r in rows]
        if not self.dim and vectors and vectors[0]:
            self.dim = len(vectors[0])
        return vectors


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """本地 sentence-transformers 模型（bge 系列）"""

    name = "local"

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL, dim: int = 0):
        self.model_name = model_name or DEFAULT_LOCAL_MODEL
        self.dim = dim or BGE_DIMS.get(self.model_name, 0)
        self._model = None

    def is_available(self) -> bool:
        try:
            import sentence_transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"加载本地 embedding 模型: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(list(texts), normalize_embeddings=True)
        result = [v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors]
        if not self.dim and result and result[0]:
            self.dim = len(result[0])
        return result


class EmbeddingManager:
    """
    Embedding 管理器

    provider 选择策略（settings.embedding_provider）：
      auto  → local 可用则用 local，否则 api 可用则用 api，否则 none
      local/api/none → 强制指定
    """

    def __init__(
        self,
        provider: str = "auto",
        local_model: str = DEFAULT_LOCAL_MODEL,
        api_base_url: str = "",
        api_key: str = "",
        api_model: str = "",
        dim: int = 0,
    ):
        self.requested = (provider or "auto").lower()
        self._dim_hint = dim  # 配置指定的维度，0 表示由后端自动推断
        self._provider: BaseEmbeddingProvider = self._resolve(
            provider=self.requested,
            local_model=local_model,
            api_base_url=api_base_url,
            api_key=api_key,
            api_model=api_model,
            dim=dim,
        )

    def _resolve(self, provider, local_model, api_base_url, api_key, api_model, dim) -> BaseEmbeddingProvider:
        local = LocalEmbeddingProvider(model_name=local_model, dim=dim)
        api = ApiEmbeddingProvider(base_url=api_base_url, api_key=api_key, model=api_model, dim=dim)

        if provider == "local":
            chosen = local if local.is_available() else NoneEmbeddingProvider()
        elif provider == "api":
            chosen = api if api.is_available() else NoneEmbeddingProvider()
        elif provider == "none":
            chosen = NoneEmbeddingProvider()
        else:  # auto
            if local.is_available():
                chosen = local
            elif api.is_available():
                chosen = api
            else:
                chosen = NoneEmbeddingProvider()

        mode = chosen.name
        if mode == "none":
            logger.warning(
                "Embedding 未启用（local 缺少 sentence-transformers 依赖，或 api 未配置/无权限），"
                "向量检索将降级为关键词检索"
            )
        else:
            logger.info(f"Embedding 后端已就绪: {mode}")
        return chosen

    @property
    def available(self) -> bool:
        return self._provider.is_available()

    @property
    def mode(self) -> str:
        return self._provider.name

    @property
    def dim(self) -> int:
        return getattr(self._provider, "dim", 0) or self._dim_hint

    @property
    def model_name(self) -> str:
        """当前生效的模型名（api / local 各自的模型）"""
        return getattr(self._provider, "model", None) or getattr(
            self._provider, "model_name", ""
        )

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        批量向量化；不可用时返回空列表（调用方负责降级）。

        熔断：首次调用失败即把后端降级为 none，避免每次检索都重复
        发起注定失败的网络请求 / 重复报错。
        """
        if not texts:
            return []
        try:
            return self._provider.embed(list(texts))
        except Exception as e:
            logger.error(
                f"向量化失败（后端 {self._provider.name}），本次及后续请求降级为关键词检索: {e}"
            )
            self._provider = NoneEmbeddingProvider()
            return []

    def embed_one(self, text: str) -> List[float]:
        """单条向量化；失败返回空列表"""
        vectors = self.embed([text]) if text else []
        return vectors[0] if vectors else []

    def rank(self, query: str, candidates: List[str]) -> List[float]:
        """计算 query 与每个候选文本的相似度；不可用或失败返回空列表"""
        if not query or not candidates or not self.available:
            return []
        vectors = self.embed([query] + list(candidates))
        if len(vectors) != len(candidates) + 1:
            return []
        q, rest = vectors[0], vectors[1:]
        return [cosine_similarity(q, v) for v in rest]


_manager: Optional[EmbeddingManager] = None


def init_embedder(manager: EmbeddingManager) -> None:
    """由服务启动时注入（与 LLMManager 用法一致）"""
    global _manager
    _manager = manager


def get_embedder() -> Optional[EmbeddingManager]:
    """获取全局 Embedding 管理器，未初始化返回 None"""
    return _manager
