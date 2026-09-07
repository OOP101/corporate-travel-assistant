"""
策程 · Planner Core 单元测试
"""
import sys
import os
import pytest

# 确保 shared 和 planner-core 在 path 中
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.llm import LLMManager
from generators.itinerary import ItineraryGenerator
from generators.checklist import ChecklistGenerator
from store.trip_store import TripStore
from archive.summary import SummaryGenerator


class TestTripStore:
    """行程存储测试"""

    def setup_method(self):
        self.store = TripStore(data_dir="./data/test_trips")

    def test_save_and_get(self):
        trip = {"title": "测试行程", "destination": "北京", "days": []}
        trip_id = self.store.save(trip)
        assert trip_id is not None
        retrieved = self.store.get(trip_id)
        assert retrieved is not None
        assert retrieved["title"] == "测试行程"

    def test_list_by_user(self):
        trip = {"title": "用户行程", "user_id": "test_user", "days": []}
        self.store.save(trip)
        trips = self.store.list_by_user("test_user")
        assert len(trips) >= 1

    def test_delete(self):
        trip = {"title": "待删除", "days": []}
        trip_id = self.store.save(trip)
        self.store.delete(trip_id)
        assert self.store.get(trip_id) is None

    def test_update(self):
        trip = {"title": "原标题", "days": []}
        trip_id = self.store.save(trip)
        self.store.update(trip_id, {"title": "新标题"})
        updated = self.store.get(trip_id)
        assert updated["title"] == "新标题"


class TestItineraryGenerator:
    """行程生成器测试"""

    def setup_method(self):
        self.llm = LLMManager()
        self.gen = ItineraryGenerator(self.llm)

    def test_demo_generate(self):
        """LLM 不可用时应降级到 Demo 模式"""
        result = self.gen.generate("去成都玩3天")
        assert result is not None
        assert "trip_id" in result
        assert "days" in result
        assert len(result["days"]) > 0

    def test_demo_has_activities(self):
        """Demo 行程应包含活动"""
        result = self.gen.generate("北京5日游")
        for day in result.get("days", []):
            assert "activities" in day
            assert len(day["activities"]) > 0


class TestChecklistGenerator:
    """清单生成器测试"""

    def setup_method(self):
        self.llm = LLMManager()
        self.gen = ChecklistGenerator(self.llm)

    def test_default_checklist(self):
        """LLM 不可用时应返回默认清单"""
        trip = {"destination": "三亚", "days": [{"date": "2026-08-20", "activities": []}]}
        items = self.gen.generate(trip)
        assert isinstance(items, list)
        assert len(items) > 0


class TestSummaryGenerator:
    """总结生成器测试"""

    def setup_method(self):
        self.llm = LLMManager()
        self.gen = SummaryGenerator(self.llm)

    def test_rule_summary(self):
        """LLM 不可用时应走规则模板"""
        trip = {
            "title": "测试旅行",
            "destination": "上海",
            "days": [
                {
                    "date": "2026-08-20",
                    "activities": [
                        {"title": "外滩", "estimated_cost": 0, "type": "attraction"},
                        {"title": "午餐", "estimated_cost": 100, "type": "dining"},
                    ],
                }
            ],
        }
        summary = self.gen.generate(trip)
        assert "overview" in summary
        assert "expense_summary" in summary
