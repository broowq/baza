from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class APIMessage(BaseModel):
    message: str


class Timestamped(BaseModel):
    id: UUID
    created_at: datetime
