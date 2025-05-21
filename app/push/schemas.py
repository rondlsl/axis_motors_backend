from pydantic import BaseModel


class PushPayload(BaseModel):
    token: str
    title: str
    body: str
