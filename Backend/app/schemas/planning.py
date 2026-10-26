"""Contracts shared by the model, executor, validator and API.

Place names come from Evidence, never from model-generated display labels.
Amounts are estimates in CNY per person for the whole trip, not live quotes.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Requirements(Contract):
    city: str = ""
    start_date: str = ""
    end_date: str = ""
    duration_days: int | None = Field(default=None, ge=1, le=14)
    budget_per_person: float | None = Field(default=None, gt=0, le=1_000_000)
    travelers: int = Field(default=1, ge=1, le=20)
    preferences: str = ""
    arrival_time: str | None = Field(
        default=None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="首日到达目的地城市的用户已知时刻；未知留空，不是开始游玩时刻",
    )
    departure_time: str | None = Field(
        default=None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="末日离开目的地城市的用户已知时刻；未知留空",
    )
    arrival_buffer_minutes: int = Field(
        default=60, ge=0, le=360, description="抵达后接驳留白，默认60分钟是假设，非导航"
    )
    departure_buffer_minutes: int = Field(
        default=90, ge=0, le=360, description="离开前接驳留白，默认90分钟是假设，非导航"
    )
    rest_dates: list[str] = Field(
        default_factory=list,
        max_length=14,
        description="用户明确只入住/休息/不观光的日期 YYYY-MM-DD；不得为绕过约束自行添加",
    )
    pace: Literal["relaxed", "balanced", "intensive"] = "balanced"
    must_visit: list[str] = Field(default_factory=list, max_length=8)
    avoid_places: list[str] = Field(default_factory=list, max_length=8)
    required_hotel: str = Field(
        default="",
        max_length=120,
        description="用户明确已订/必须使用的完整酒店名；安静/品牌喜好不填",
    )
    required_restaurants: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="用户明确必吃/已预约的餐厅名；仅要求至少安排一次，不限制其他餐厅",
    )
    reservation_notes: str = Field(
        default="",
        max_length=300,
        description="用户提供的预约时间原文；本版仅保护地点，尚未校验预约时刻",
    )
    daily_attraction_limit: int | None = Field(
        default=None, ge=1, le=5, description="用户明确要求的每天最多景点数；未说明则留空"
    )


class AnchorChange(Contract):
    target: Literal["hotel", "restaurant"]
    action: Literal["set", "clear"]
    name: str = Field(default="", max_length=120)
    user_quote: str = Field(
        min_length=1,
        max_length=300,
        description="本轮用户取消/替换明确要求的连续原文，不得引用历史或推测",
    )


class ScheduleRelease(Contract):
    target: Literal["arrival_time", "departure_time", "rest_date"]
    rest_date: str = ""
    user_quote: str = Field(
        min_length=1,
        max_length=300,
        description="本轮用户明确取消抵离时间限制或休息日的连续原文；疑问/否定不得取消",
    )


class RequestDecision(Contract):
    intent: Literal["new_trip", "modify_hotel", "modify_itinerary", "chat"]
    requirements: Requirements
    scope_clarification: str = Field(
        default="",
        max_length=500,
        description="区域或多城市旅行超出单城市能力时，向用户确认一个集中游玩的目的地；不得静默选择代表城市",
    )
    attraction_queries: list[str] = Field(default_factory=list, max_length=2)
    hotel_area: str = ""
    hotel_budget_level: Literal["经济型", "中档", "豪华", "民宿"] = "中档"
    food_query: str = "当地菜"
    anchor_reset_quote: str = Field(
        default="",
        max_length=300,
        description="仅用户明确开始一趟独立新旅行时填本轮原文；重新规划或改节奏不填",
    )
    anchor_changes: list[AnchorChange] = Field(default_factory=list, max_length=8)
    schedule_releases: list[ScheduleRelease] = Field(default_factory=list, max_length=16)
    choice_review: Literal["none", "hotel", "restaurant", "both"] = "none"
    hotel_profiles: list[Literal["经济型", "中档", "豪华", "民宿"]] = Field(
        default_factory=list, max_length=2
    )
    food_queries: list[str] = Field(default_factory=list, max_length=3)
    reply: str = ""
    refresh_categories: list[Literal["attraction", "hotel", "restaurant", "weather"]] = Field(
        default_factory=list, max_length=4
    )


class Evidence(Contract):
    evidence_id: str
    category: Literal["attraction", "hotel", "restaurant", "weather"]
    source: str = "高德地图 MCP"
    fetched_at: str
    city: str
    data: dict


class ChoiceSelection(Contract):
    token: str = Field(min_length=1, max_length=64)
    automatic: bool = False
    hotel_evidence_id: str | None = None
    restaurant_evidence_ids: list[str] = Field(default_factory=list, max_length=3)
    hotel_mode: Literal["prefer", "lock", "automatic"] = "lock"
    restaurant_mode: Literal["prefer", "lock", "automatic"] = "lock"


class RouteDraftDay(Contract):
    date: date
    theme: str = Field(max_length=80)
    attraction_evidence_ids: list[str] = Field(default_factory=list, max_length=5)


class RouteDraft(Contract):
    city: str
    days: list[RouteDraftDay] = Field(min_length=1, max_length=14)
    rationale: str = Field(min_length=1, max_length=500)


class Stop(Contract):
    evidence_id: str
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    # Free text is explanatory, never treated as verified place/price evidence.
    note: str = Field(default="", max_length=300)


class FlexibleMeal(Contract):
    anchor_evidence_id: str
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ItineraryDay(Contract):
    stay_anchor_evidence_id: str | None = None
    meal_breaks: list[FlexibleMeal] = Field(default_factory=list, max_length=2)
    date: date
    theme: str = Field(max_length=80)
    stops: list[Stop] = Field(default_factory=list, max_length=8)


class CostEstimate(Contract):
    accommodation: float = Field(ge=0)
    meals: float = Field(ge=0)
    transport: float = Field(ge=0)
    tickets: float = Field(ge=0)
    basis: str = Field(min_length=1, max_length=500)

    @property
    def total(self) -> float:
        return round(self.accommodation + self.meals + self.transport + self.tickets, 2)


class Itinerary(Contract):
    service_mode: Literal["specific", "browse"] = "specific"
    city: str
    days: list[ItineraryDay] = Field(min_length=1, max_length=14)
    hotel_evidence_id: str | None = None
    costs: CostEstimate
    suggestions: list[str] = Field(default_factory=list, max_length=6)


class HotelRevision(Contract):
    """Hotel-only edits cannot mutate days, meals or ticket costs."""

    hotel_evidence_id: str | None
    accommodation: float = Field(ge=0)
    basis: str = Field(min_length=1, max_length=500)


class ValidationIssue(Contract):
    code: str
    severity: Literal["error", "warning"]
    message: str
    day: str | None = None


class ValidationReport(Contract):
    passed: bool
    issues: list[ValidationIssue]
    checks: list[str]
    unverified_checks: list[str] = Field(default_factory=list)
