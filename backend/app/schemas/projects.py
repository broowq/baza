from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    niche: str = Field(min_length=2, max_length=120)
    geography: str = Field(min_length=2, max_length=120)
    segments: list[str] = Field(default_factory=list)
    cron_schedule: str = Field(default="0 9 * * 1", max_length=120)
    auto_collection_enabled: bool = False


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=140)
    niche: str | None = Field(default=None, min_length=2, max_length=120)
    geography: str | None = Field(default=None, min_length=2, max_length=120)
    segments: list[str] | None = None
    cron_schedule: str | None = Field(default=None, max_length=120)
    auto_collection_enabled: bool | None = None


class ProjectOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    niche: str
    geography: str
    segments: list[str]
    cron_schedule: str
    auto_collection_enabled: bool
    created_at: datetime
    deleted_at: datetime | None = None

    class Config:
        from_attributes = True
