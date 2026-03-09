from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CalendarEvent(BaseModel):
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str | None = None
    description: str | None = None
    is_all_day: bool = False
    html_link: str | None = None
    can_delete: bool = False
    linked_account_id: str | None = None
    account_email: str | None = None
    account_name: str | None = None


class CreateCalendarEventRequest(BaseModel):
    title: str = Field(min_length=1)
    starts_at: datetime
    is_all_day: bool = False
    ends_at: datetime
    linked_account_id: str | None = None
    location: str | None = None
    description: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Event title must not be empty.")
        return normalized

    @field_validator("ends_at")
    @classmethod
    def validate_end_after_start(cls, value: datetime, info) -> datetime:
        starts_at = info.data.get("starts_at")
        is_all_day = bool(info.data.get("is_all_day"))
        if starts_at is not None and value <= starts_at and not is_all_day:
            raise ValueError("Event end time must be after the start time.")
        if starts_at is not None and is_all_day and value.date() < starts_at.date():
            raise ValueError("All-day event end date must be on or after the start.")
        return value
