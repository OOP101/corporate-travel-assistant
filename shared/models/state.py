"""
共享数据模型 —— 行程核心数据结构

行程 (Trip) → 每日安排 (TripDay) → 时段活动 (Activity)
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum
import time
import uuid


class TripStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ActivityType(str, Enum):
    TRANSPORT = "transport"
    ATTRACTION = "attraction"
    DINING = "dining"
    ACCOMMODATION = "accommodation"
    SHOPPING = "shopping"
    REST = "rest"
    MEETING = "meeting"
    OTHER = "other"


@dataclass
class Location:
    name: str = ""
    lat: float = 0.0
    lng: float = 0.0
    address: str = ""


@dataclass
class Activity:
    time_start: str = ""        # "09:00"
    time_end: str = ""          # "11:30"
    type: str = "other"         # ActivityType value
    title: str = ""
    location: Location = field(default_factory=Location)
    description: str = ""
    ticket_price: float = 0
    booking_required: bool = False
    booking_url: str = ""
    tips: str = ""
    estimated_cost: float = 0
    status: str = "scheduled"   # scheduled | completed | skipped | changed

    def to_dict(self) -> dict:
        return {
            "time_start": self.time_start,
            "time_end": self.time_end,
            "type": self.type,
            "title": self.title,
            "location": {
                "name": self.location.name,
                "lat": self.location.lat,
                "lng": self.location.lng,
                "address": self.location.address,
            },
            "description": self.description,
            "ticket_price": self.ticket_price,
            "booking_required": self.booking_required,
            "booking_url": self.booking_url,
            "tips": self.tips,
            "estimated_cost": self.estimated_cost,
            "status": self.status,
        }


@dataclass
class TripDay:
    date: str = ""              # "2026-08-20"
    theme: str = ""
    activities: List[Activity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "theme": self.theme,
            "activities": [a.to_dict() for a in self.activities],
        }


@dataclass
class TravelPartyMember:
    name: str = ""
    role: str = "adult"         # adult | child | elder
    age: int = 0
    notes: str = ""


@dataclass
class Trip:
    trip_id: str = field(default_factory=lambda: f"trip_{uuid.uuid4().hex[:12]}")
    user_id: str = "default"
    title: str = ""
    destination: str = ""
    origin: str = ""
    start_date: str = ""
    end_date: str = ""
    budget_total: float = 0
    travel_party: List[TravelPartyMember] = field(default_factory=list)
    days: List[TripDay] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    status: str = TripStatus.PLANNED.value
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "trip_id": self.trip_id,
            "user_id": self.user_id,
            "title": self.title,
            "destination": self.destination,
            "origin": self.origin,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "budget_total": self.budget_total,
            "travel_party": [
                {"name": m.name, "role": m.role, "age": m.age, "notes": m.notes}
                for m in self.travel_party
            ],
            "days": [d.to_dict() for d in self.days],
            "checklist": self.checklist,
            "preferences": self.preferences,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class AlertEvent:
    """感知引擎产出的提醒事件"""
    alert_id: str = field(default_factory=lambda: f"alert_{uuid.uuid4().hex[:12]}")
    trip_id: str = ""
    user_id: str = ""
    type: str = ""              # flight_delay | weather_warning | traffic_jam | attraction_closed
    severity: str = "info"      # info | warning | critical
    title: str = ""
    message: str = ""
    suggested_action: str = ""
    source: str = ""
    created_at: float = field(default_factory=time.time)
    delivered: bool = False

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "trip_id": self.trip_id,
            "user_id": self.user_id,
            "type": self.type,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "suggested_action": self.suggested_action,
            "source": self.source,
            "created_at": self.created_at,
            "delivered": self.delivered,
        }


@dataclass
class PreferenceProfile:
    """用户偏好画像"""
    user_id: str = "default"
    budget_daily_range: tuple = (200, 800)
    travel_style: str = ""         # relaxed | compact | adventure | cultural
    dietary: List[str] = field(default_factory=list)
    fitness_level: str = "normal"  # low | normal | high
    accommodation_pref: str = ""   # hotel | hostel | homestay
    companions: List[dict] = field(default_factory=list)
    visited_cities: List[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "budget_daily_range": list(self.budget_daily_range),
            "travel_style": self.travel_style,
            "dietary": self.dietary,
            "fitness_level": self.fitness_level,
            "accommodation_pref": self.accommodation_pref,
            "companions": self.companions,
            "visited_cities": self.visited_cities,
            "extra": self.extra,
        }
