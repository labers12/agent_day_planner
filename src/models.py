"""Data models — lightweight dataclasses for the domain."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class UserProfile:
    id: int = 0
    telegram_id: str = ""
    display_name: str = ""
    wake_time: str = "07:00"
    sleep_time: str = "23:00"
    prep_before_exit_min: int = 30
    onboarding_complete: bool = False
    onboarding_step: int = 0

    @classmethod
    def from_row(cls, row: dict) -> UserProfile:
        return cls(
            id=row.get("id", 0),
            telegram_id=str(row.get("telegram_id", "")),
            display_name=row.get("display_name", ""),
            wake_time=row.get("wake_time", "07:00"),
            sleep_time=row.get("sleep_time", "23:00"),
            prep_before_exit_min=row.get("prep_before_exit_min", 30),
            onboarding_complete=bool(row.get("onboarding_complete", 0)),
            onboarding_step=row.get("onboarding_step", 0),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["onboarding_complete"] = int(self.onboarding_complete)
        return d


@dataclass
class Location:
    id: int = 0
    name: str = ""
    travel_minutes_one_way: int = 0
    notes: str = ""

    @classmethod
    def from_row(cls, row: dict) -> Location:
        return cls(**{k: row[k] for k in ("id", "name", "travel_minutes_one_way", "notes") if k in row})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UniversityClass:
    id: int = 0
    day_of_week: int = 0
    week_parity: str = "any"
    start_time: str = ""
    end_time: str = ""
    subject: str = ""
    lecture_type: str = ""
    building: str = ""
    room: str = ""
    teacher: str = ""

    @classmethod
    def from_row(cls, row: dict) -> UniversityClass:
        return cls(**{k: row.get(k, "") for k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Task:
    id: int = 0
    title: str = ""
    description: str = ""
    deadline: Optional[str] = None
    estimated_hours: float = 1.0
    cognitive_load: int = 3
    status: str = "pending"
    scheduled_date: Optional[str] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    original_date: Optional[str] = None
    location_name: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> Task:
        return cls(**{k: row.get(k) for k in cls.__dataclass_fields__ if k in row})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Habit:
    id: int = 0
    title: str = ""
    description: str = ""
    times_per_week: int = 3
    duration_minutes: int = 60
    location_name: Optional[str] = None
    cognitive_load: int = 2
    physical_load: int = 3
    preferred_time: str = "evening"
    active: bool = True

    @classmethod
    def from_row(cls, row: dict) -> Habit:
        obj = cls(**{k: row.get(k) for k in cls.__dataclass_fields__ if k in row})
        obj.active = bool(row.get("active", 1))
        return obj

    def to_dict(self) -> dict:
        d = asdict(self)
        d["active"] = int(self.active)
        return d


@dataclass
class HabitSlot:
    id: int = 0
    habit_id: int = 0
    week_start: str = ""
    scheduled_date: str = ""
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    status: str = "pending"

    @classmethod
    def from_row(cls, row: dict) -> HabitSlot:
        return cls(**{k: row.get(k) for k in cls.__dataclass_fields__ if k in row})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DailyPlanItem:
    id: int = 0
    plan_date: str = ""
    slot_type: str = ""
    reference_id: Optional[int] = None
    title: str = ""
    start_time: str = ""
    end_time: str = ""
    cognitive_cost: int = 0
    physical_cost: int = 0
    notes: str = ""
    status: str = "planned"

    @classmethod
    def from_row(cls, row: dict) -> DailyPlanItem:
        return cls(**{k: row.get(k) for k in cls.__dataclass_fields__ if k in row})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DailyStatus:
    id: int = 0
    status_date: str = ""
    energy_level: str = "normal"
    mental_budget: int = 70
    physical_budget: int = 70
    notes: str = ""

    @classmethod
    def from_row(cls, row: dict) -> DailyStatus:
        return cls(**{k: row.get(k) for k in cls.__dataclass_fields__ if k in row})

    def to_dict(self) -> dict:
        return asdict(self)
