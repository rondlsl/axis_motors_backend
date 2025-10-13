from pydantic import BaseModel
from typing import List, Optional
import uuid
from app.schemas.base import SidMixin


class SupportUserSchema(SidMixin):
    id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    digital_signature: Optional[str] = None


class SupportActionItemSchema(SidMixin):
    id: str
    user: SupportUserSchema
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    created_at: str


class SupportActionsListResponse(BaseModel):
    items: List[SupportActionItemSchema]
    page: int
    page_size: int
    total: int


