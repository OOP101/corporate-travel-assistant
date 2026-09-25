"""core 层 Store 的持久化保证：原子写 + 进程内互斥 + 崩溃不损坏已有数据

这组测试针对 2026-09-26 修掉的 P0：
TripStore / ProfileStore 原先用 open(path, "w") + json.dump 裸写，
窗口期内被中断会留下半截 JSON，导致该条数据永久不可读。
现在两者都走 shared.store.base_store.atomic_write_json（temp + os.replace）并加了 RLock。
"""
import json
import os
import tempfile
import threading
from unittest.mock import patch

import pytest

from core.stores.profile_store import ProfileStore
from core.stores.trip_store import TripStore


# ---------------------------------------------------------------------------
# 原子写：中途失败不得损坏已有文件
# ---------------------------------------------------------------------------
def test_trip_write_is_atomic_on_failure():
    """写盘中途抛错时，磁盘上的旧文件必须完整可读（不被截断）。"""
    store = TripStore(data_dir=tempfile.mkdtemp())
    trip_id = store.save({"user_id": "u1", "title": "初始行程"})

    file_path = os.path.join(store.data_dir, f"{trip_id}.json")
    before = json.load(open(file_path, encoding="utf-8"))
    assert before["title"] == "初始行程"

    # 模拟序列化阶段崩溃（json.dump 抛错）
    with patch("shared.store.base_store.json.dump", side_effect=ValueError("boom")):
        store.update(trip_id, {"title": "改坏了"})

    # 关键断言：旧文件仍能被完整解析，内容未被半截覆盖
    after = json.load(open(file_path, encoding="utf-8"))
    assert after["title"] == "初始行程"
    # 且不留临时文件残骸
    assert not [f for f in os.listdir(store.data_dir) if f.endswith(".tmp")]


def test_profile_write_is_atomic_on_failure():
    store = ProfileStore(data_dir=tempfile.mkdtemp())
    store.save("u1", {"travel_style": "relaxed"})

    file_path = os.path.join(store.data_dir, "u1.json")
    before = json.load(open(file_path, encoding="utf-8"))
    assert before["travel_style"] == "relaxed"

    with patch("shared.store.base_store.json.dump", side_effect=ValueError("boom")):
        store.update("u1", {"travel_style": "changed"})

    after = json.load(open(file_path, encoding="utf-8"))
    assert after["travel_style"] == "relaxed"
    assert not [f for f in os.listdir(store.data_dir) if f.endswith(".tmp")]


# ---------------------------------------------------------------------------
# 并发：多线程写同一/不同记录，不产生损坏文件
# ---------------------------------------------------------------------------
def test_trip_concurrent_writes_no_corruption():
    store = TripStore(data_dir=tempfile.mkdtemp())
    errors = []

    def worker(i):
        try:
            for _ in range(10):
                store.save({"user_id": f"u{i}", "title": f"t{i}"})
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(store.list_all()) == 50
    # 每个文件都必须可解析，且无临时文件残留
    assert not [f for f in os.listdir(store.data_dir) if f.endswith(".tmp")]
    for f in os.listdir(store.data_dir):
        if f.endswith(".json"):
            json.load(open(os.path.join(store.data_dir, f), encoding="utf-8"))


def test_trip_concurrent_update_same_record_not_lost():
    """同一行程被并发更新：不允许出现半截/不可解析的文件。"""
    store = TripStore(data_dir=tempfile.mkdtemp())
    trip_id = store.save({"user_id": "u1", "title": "t", "counter": 0})
    errors = []

    def worker(i):
        try:
            for n in range(20):
                store.update(trip_id, {"counter": i * 100 + n})
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    data = json.load(open(os.path.join(store.data_dir, f"{trip_id}.json"), encoding="utf-8"))
    assert isinstance(data["counter"], int)  # 可解析
    assert data["trip_id"] == trip_id


# ---------------------------------------------------------------------------
# 行为回归：锁与原子写不得改变原有语义
# ---------------------------------------------------------------------------
def test_trip_crud_roundtrip_unaffected():
    store = TripStore(data_dir=tempfile.mkdtemp())
    trip_id = store.save({"user_id": "u1", "title": "a"})
    assert store.get(trip_id)["title"] == "a"

    store.update(trip_id, {"title": "b"})
    assert store.get(trip_id)["title"] == "b"
    assert store.get(trip_id)["trip_id"] == trip_id  # id 不可篡改

    assert store.list_by_user("u1")[0]["title"] == "b"
    assert store.delete(trip_id) is True
    assert store.get(trip_id) is None
    assert store.delete(trip_id) is False


def test_stores_reload_from_disk():
    trip_dir = tempfile.mkdtemp()
    trip_id = TripStore(data_dir=trip_dir).save({"user_id": "u1", "title": "durable"})
    assert TripStore(data_dir=trip_dir).get(trip_id)["title"] == "durable"

    prof_dir = tempfile.mkdtemp()
    ProfileStore(data_dir=prof_dir).save("u1", {"travel_style": "relaxed"})
    assert ProfileStore(data_dir=prof_dir).get("u1")["travel_style"] == "relaxed"


def test_corrupt_file_skipped_on_load():
    """坏文件应被跳过而不是让整个 Store 初始化失败。"""
    data_dir = tempfile.mkdtemp()
    with open(os.path.join(data_dir, "bad.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    store = TripStore(data_dir=data_dir)
    assert store.list_all() == []
