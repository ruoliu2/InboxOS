from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.routers import auth, calendar, gmail, health, tasks

configure_logging()
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="InboxOS MVP API for action-centric email workflows",
)

origins = [
    origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(gmail.router, prefix="/gmail", tags=["gmail"])
app.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
