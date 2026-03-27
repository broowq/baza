from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models import PlanType


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    plan: PlanType
    leads_used_current_month: int
    leads_limit_per_month: int
    projects_limit: int
    users_limit: int
    can_invite_members: bool
    created_at: datetime

    class Config:
        from_attributes = True


class PlanUpdateRequest(BaseModel):
    plan: PlanType


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="member", max_length=32)


class InviteAcceptRequest(BaseModel):
    token: str


class MemberRoleUpdateRequest(BaseModel):
    role: str = Field(max_length=32)


class InviteOut(BaseModel):
    id: UUID
    email: EmailStr
    role: str
    accepted: bool
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class MemberOut(BaseModel):
    user_id: UUID
    email: EmailStr
    full_name: str
    role: str


class CurrentMembershipOut(BaseModel):
    user_id: UUID
    organization_id: UUID
    role: str


class ActionLogOut(BaseModel):
    id: UUID
    user_id: UUID
    organization_id: UUID
    action: str
    meta: dict
    created_at: datetime

    class Config:
        from_attributes = True
