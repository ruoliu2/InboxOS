from datetime import datetime

from pydantic import BaseModel


class CalendarEvent(BaseModel):
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str | None = None
    description: str | None = None
    is_all_day: bool = False
    html_link: str | None = None
