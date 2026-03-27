from pydantic import BaseModel, Field


class SearchPreviewRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    geography: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=100)


class SearchCompaniesRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    geography: str = Field(default="", max_length=200)
    project_id: str
    limit: int = Field(default=20, ge=1, le=100)


class SearchResultItem(BaseModel):
    name: str
    domain: str
    url: str
    source: str
    city: str
    address: str
