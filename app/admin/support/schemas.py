from pydantic import BaseModel
from typing import List, Optional


class SupportUserSchema(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None


class SupportActionItemSchema(BaseModel):
    id: int
    user: SupportUserSchema
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    created_at: str


class SupportActionsListResponse(BaseModel):
    items: List[SupportActionItemSchema]
    page: int
    page_size: int
    total: int


