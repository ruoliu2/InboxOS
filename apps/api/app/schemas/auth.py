from datetime import datetime

from pydantic import BaseModel, Field


class AuthStartResponse(BaseModel):
    provider: str
    authorization_url: str
    state: str


class AuthUserResponse(BaseModel):
    id: str
    primary_email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


class LinkedAccountResponse(BaseModel):
    id: str
    provider: str
    provider_account_id: str
    provider_account_ref: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    status: str
    capabilities: list[str] = Field(default_factory=list)
    last_synced_at: datetime | None = None


class AuthSessionResponse(BaseModel):
    authenticated: bool
    user: AuthUserResponse | None = None
    active_account_id: str | None = None
    linked_accounts: list[LinkedAccountResponse] = Field(default_factory=list)
    provider: str | None = None
    account_email: str | None = None
    account_name: str | None = None
    account_picture: str | None = None
