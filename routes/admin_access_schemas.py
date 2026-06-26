from __future__ import annotations

from pydantic import BaseModel, Field


class AccessUserUpsertRequest(BaseModel):
    phone_number: str
    name: str | None = None
    is_active: bool = True
    roles: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    gv_vdes: list[str] = Field(default_factory=list)


class AccessUserBulkUpsertRequest(BaseModel):
    users: list[AccessUserUpsertRequest] = Field(default_factory=list)
    continue_on_error: bool = True


class AccessRoleUpsertRequest(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)
