"""景点 / 攻略语料存储 —— C 端个人出行的 RAG 检索语料

与「企业差旅政策文档」结构一致（title / content / category / tags），
因此直接复用 shared 公共层的 DocumentCorpusStore：关键词检索、增量向量
索引、语义检索三件事都不必重写一遍。

用途：个人出游场景下为行程规划提供景点与攻略依据（门票、建议游玩时长、
预约要求、避坑提示等），使生成结果不只排日程，而是有真实景点内容支撑。
"""
from shared.store.document_store import DocumentCorpusStore


class TravelGuideStore(DocumentCorpusStore):
    """景点 / 攻略语料存储"""
    _id_field = "guide_id"
    _id_prefix = "gd_"
