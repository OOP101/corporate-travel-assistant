"""shared.store.base_store 测试：CRUD、原子写、并发写"""
import os
import tempfile
import threading

from shared.store.base_store import BaseJsonStore


class DemoStore(BaseJsonStore):
    _id_field = "demo_id"
    _id_prefix = "demo_"

    def _default_entity(self):
        return {"name": ""}


def make_store():
    return DemoStore(data_dir=tempfile.mkdtemp())


def test_save_get_update_delete_roundtrip():
    store = make_store()
    eid = store.save({"name": "a"})
    assert store.get(eid)["name"] == "a"

    store.update(eid, {"name": "b"})
    assert store.get(eid)["name"] == "b"
    # ID 不可篡改
    assert store.get(eid)["demo_id"] == eid

    assert store.delete(eid) is True
    assert store.get(eid) is None
    assert store.delete(eid) is False


def test_save_persists_one_file_per_entity():
    store = make_store()
    ids = [store.save({"name": f"n{i}"}) for i in range(10)]
    files = [f for f in os.listdir(store.data_dir) if f.endswith(".json")]
    assert sorted(files) == sorted(f"{i}.json" for i in ids)
    assert not [f for f in os.listdir(store.data_dir) if f.endswith(".tmp")]


def test_records_reload_from_disk():
    store = make_store()
    eid = store.save({"name": "durable"})
    # 新实例从磁盘加载
    store2 = DemoStore(data_dir=store.data_dir)
    assert store2.get(eid)["name"] == "durable"


def test_corrupt_file_skipped_on_load():
    data_dir = tempfile.mkdtemp()
    with open(os.path.join(data_dir, "bad.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    store = DemoStore(data_dir=data_dir)
    assert store.count() == 0  # 坏文件被跳过而不是崩溃


def test_concurrent_writes_no_corruption():
    store = make_store()
    errors = []

    def worker(i):
        try:
            for _ in range(10):
                store.save({"name": f"w{i}", "value": i})
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert store.count() == 50
    assert not [f for f in os.listdir(store.data_dir) if f.endswith(".tmp")]
