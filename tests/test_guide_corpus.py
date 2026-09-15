"""景点/攻略语料 RAG 通道 的回归测试（2026-09-14）。

覆盖：
  1. `TravelGuideStore` 复用 `DocumentCorpusStore` 能力（主键前缀 / 关键词 / 分类检索）
  2. `ItineraryGenerator` 只在 personal 场景召回语料（商务场景不得被景点污染）
  3. 语料注入提示词、并挂到行程字典供前端展示「内容依据」
  4. 两套语料（政策文档 / 景点攻略）互不串档

不依赖已落盘的种子数据，全部使用 tmp_path 临时目录。
"""
import os
import sys

import pytest

PLANNER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "planner-core"
)


@pytest.fixture()
def guide_mods(tmp_path):
    """导入 planner-core 的 store 与 generators（保证解析到 planner-core 而非同名服务）。"""
    if PLANNER_DIR in sys.path:
        sys.path.remove(PLANNER_DIR)
    sys.path.insert(0, PLANNER_DIR)
    for _mod in [m for m in list(sys.modules) if m == "api" or m.startswith("api.")]:
        del sys.modules[_mod]

    from store import TravelGuideStore, PolicyDocumentStore  # noqa: E402
    from generators.itinerary import ItineraryGenerator      # noqa: E402

    store = TravelGuideStore(data_dir=str(tmp_path / "guide_docs"))
    store.save({
        "title": "杭州·西湖景区游玩攻略",
        "content": "西湖环湖免费开放，三潭印月上岛游船参考 55 元。建议游玩 3~4 小时。",
        "category": "attraction",
        "tags": ["杭州", "西湖", "景点"],
        "source": "测试语料",
    })
    store.save({
        "title": "成都·宽窄巷子与锦里古街攻略",
        "content": "以川西民居与市井小吃为主，建议各安排 1.5~2 小时。",
        "category": "food",
        "tags": ["成都", "小吃"],
        "source": "测试语料",
    })
    return store, PolicyDocumentStore, ItineraryGenerator


# ---------------------------------------------------------------------------
# 一、存储层：复用 DocumentCorpusStore
# ---------------------------------------------------------------------------
def test_guide_store_id_prefix_and_field(guide_mods):
    store, _, _ = guide_mods
    assert store._id_field == "guide_id"
    assert store._id_prefix == "gd_"
    gid = store.save({"title": "西安·兵马俑攻略", "content": "需实名预约"})
    assert gid.startswith("gd_")
    assert (store.get(gid) or {}).get("guide_id") == gid


def test_keyword_search_hits_city_name(guide_mods):
    store, _, _ = guide_mods
    docs = store.search_by_keyword("杭州")
    assert len(docs) == 1
    assert "西湖" in docs[0]["title"]


def test_category_search(guide_mods):
    store, _, _ = guide_mods
    food = store.search_by_category("food")
    assert [d["title"] for d in food] == ["成都·宽窄巷子与锦里古街攻略"]


def test_two_corpuses_do_not_mix(guide_mods, tmp_path):
    """政策文档与景点语料是两套独立主键空间。"""
    store, PolicyDocumentStore, _ = guide_mods
    pol = PolicyDocumentStore(data_dir=str(tmp_path / "policy_docs"))
    pid = pol.save({"title": "差旅费用报销制度", "content": "10 个工作日内提交"})
    assert pid.startswith("doc_")
    # 政策文档库里搜不到景点语料，反之亦然
    assert pol.search_by_keyword("西湖") == []
    assert store.search_by_keyword("报销") == []


# ---------------------------------------------------------------------------
# 二、生成器：仅 personal 场景召回
# ---------------------------------------------------------------------------
def _make_gen(ItineraryGenerator, store):
    return ItineraryGenerator(llm_manager=None, guide_store=store)


def test_retrieve_guides_for_personal_scene(guide_mods):
    store, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, store)
    docs = gen._retrieve_guides({"scene": "personal", "destination": "杭州"})
    assert len(docs) == 1
    assert "西湖" in docs[0]["title"]


@pytest.mark.parametrize("scene", ["business", "meeting", "visit", "team"])
def test_no_guides_for_business_scenes(guide_mods, scene):
    """企业场景禁景点：不得召回语料（否则会污染提示词）。"""
    store, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, store)
    assert gen._retrieve_guides({"scene": scene, "destination": "杭州"}) == []


def test_retrieve_guides_without_store_is_empty(guide_mods):
    _, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, None)
    assert gen._retrieve_guides({"scene": "personal", "destination": "杭州"}) == []


def test_retrieve_guides_without_destination_is_empty(guide_mods):
    store, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, store)
    assert gen._retrieve_guides({"scene": "personal"}) == []


def test_unknown_destination_returns_empty(guide_mods):
    """没有语料覆盖的城市 → 空召回，绝不编造。"""
    store, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, store)
    assert gen._retrieve_guides({"scene": "personal", "destination": "拉萨"}) == []


# ---------------------------------------------------------------------------
# 三、提示词注入 + 行程挂载
# ---------------------------------------------------------------------------
def test_guide_prompt_block_contains_title_and_excerpt(guide_mods):
    store, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, store)
    docs = gen._retrieve_guides({"scene": "personal", "destination": "杭州"})
    block = gen._guide_prompt_block(docs)
    assert "【景点/攻略语料" in block
    assert "西湖" in block
    assert "55 元" in block          # excerpt 保留原文依据


def test_guide_prompt_block_empty_when_no_docs(guide_mods):
    _, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, None)
    assert gen._guide_prompt_block([]) == ""


def test_attach_external_adds_guide_refs(guide_mods):
    store, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, store)
    gen._last_guides = gen._retrieve_guides({"scene": "personal", "destination": "杭州"})
    trip = gen._attach_external({"title": "杭州三日"}, gen._empty_ext())
    refs = trip.get("guide_refs")
    assert refs and refs[0]["guide_id"].startswith("gd_")
    assert "西湖" in refs[0]["title"]


def test_attach_external_no_guide_refs_when_empty(guide_mods):
    _, _, ItineraryGenerator = guide_mods
    gen = _make_gen(ItineraryGenerator, None)
    gen._last_guides = []
    trip = gen._attach_external({"title": "商务出差"}, gen._empty_ext())
    assert "guide_refs" not in trip
