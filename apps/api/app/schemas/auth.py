from pydantic import BaseModel


class AuthStartResponse(BaseModel):
    provider: str
    authorization_url: str
    state: str


class AuthCallbackResponse(BaseModel):
    provider: str
    connected: bool
    account_email: str
    message: str


class AuthSessionResponse(BaseModel):
    authenticated: bool
    provider: str | None = None
    account_email: str | None = None
    account_name: str | None = None
    account_picture: str | None = None
