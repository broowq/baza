from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    prompt: str | None = Field(default=None, max_length=2000)
    niche: str = Field(min_length=2, max_length=120)
    geography: str = Field(min_length=2, max_length=120)
    segments: list[str] = Field(default_factory=list)
    cron_schedule: str = Field(default="0 9 * * 1", max_length=120)
    auto_collection_enabled: bool = False

    @field_validator('segments')
    @classmethod
    def validate_segments(cls, v):
        return [s[:100] for s in (v or [])[:20]]


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=140)
    prompt: str | None = Field(default=None, max_length=2000)
    niche: str | None = Field(default=None, min_length=2, max_length=120)
    geography: str | None = Field(default=None, min_length=2, max_length=120)
    segments: list[str] | None = None
    cron_schedule: str | None = Field(default=None, max_length=120)
    auto_collection_enabled: bool | None = None

    @field_validator('segments')
    @classmethod
    def validate_segments(cls, v):
        if v is None:
            return v
        return [s[:100] for s in (v or [])[:20]]


class ProjectOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    prompt: str | None = None
    niche: str
    geography: str
    segments: list[str]
    cron_schedule: str
    auto_collection_enabled: bool
    created_at: datetime
    deleted_at: datetime | None = None

    class Config:
        from_attributes = True


class PromptEnhanceRequest(BaseModel):
    prompt: str = Field(min_length=5, max_length=2000)


class PromptEnhanceResponse(BaseModel):
    enhanced_prompt: str
    project_name: str
    niche: str
    geography: str
    segments: list[str]
    target_customer_types: list[str] = Field(default_factory=list)
    search_queries_niche: str = ""
    explanation: str = ""
