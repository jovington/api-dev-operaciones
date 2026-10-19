from pydantic import BaseModel, Field


class UserSummary(BaseModel):
    id: str = Field(serialization_alias='id')
    username: str
    display_name: str = Field(alias='displayName', serialization_alias='displayName')
    role: str
    active: bool