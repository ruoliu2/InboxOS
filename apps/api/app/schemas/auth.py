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
