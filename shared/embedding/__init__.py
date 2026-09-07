"""
共享 Embedding 模块

用法（服务启动时初始化一次）：
    from shared.embedding import EmbeddingManager, init_embedder, get_embedder

    init_embedder(EmbeddingManager(
        provider=settings.embedding_provider,
        local_model=settings.embedding_model,
        api_base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        api_model=settings.embedding_model,
        dim=settings.embedding_dim,
    ))

调用方（向量不可用时自行降级为关键词检索）：
    embedder = get_embedder()
    if embedder and embedder.available:
        scores = embedder.rank(query, [doc["content"] for doc in docs])
"""
from .embedder import (
    BGE_DIMS,
    DEFAULT_LOCAL_MODEL,
    ApiEmbeddingProvider,
    BaseEmbeddingProvider,
    EmbeddingManager,
    LocalEmbeddingProvider,
    NoneEmbeddingProvider,
    cosine_similarity,
    get_embedder,
    init_embedder,
)

__all__ = [
    "BGE_DIMS",
    "DEFAULT_LOCAL_MODEL",
    "ApiEmbeddingProvider",
    "BaseEmbeddingProvider",
    "EmbeddingManager",
    "LocalEmbeddingProvider",
    "NoneEmbeddingProvider",
    "cosine_similarity",
    "get_embedder",
    "init_embedder",
]
