"""Request bodies for the JSON API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field


def _no_control_chars(value: str) -> str:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("control characters are not allowed")
    return value


Name = Annotated[str, Field(min_length=1, max_length=256), AfterValidator(_no_control_chars)]
Text = Annotated[str, Field(max_length=512), AfterValidator(_no_control_chars)]
Topic = Annotated[str, Field(min_length=1, max_length=1024), AfterValidator(_no_control_chars)]
Secret = Annotated[str, Field(min_length=1, max_length=256)]

AclType = Literal[
    "publishClientSend",
    "publishClientReceive",
    "subscribeLiteral",
    "subscribePattern",
    "unsubscribeLiteral",
    "unsubscribePattern",
]
Preset = Literal["readwrite", "read", "write"]


class Login(BaseModel):
    password: str = Field(max_length=256)


class ClientCreate(BaseModel):
    username: Name
    password: Secret
    textname: Text = ""
    textdescription: Text = ""
    clientid: Name | None = None
    roles: list[Name] = []
    groups: list[Name] = []


class ClientUpdate(BaseModel):
    username: Name
    textname: Text | None = None
    textdescription: Text | None = None
    clientid: Text | None = None  # empty string removes the client id binding


class ClientPassword(BaseModel):
    username: Name
    password: Secret


class ClientEnable(BaseModel):
    username: Name
    enabled: bool


class ClientRef(BaseModel):
    username: Name


class ClientRole(BaseModel):
    username: Name
    rolename: Name
    priority: int = Field(default=0, ge=-1000, le=1000)


class ClientGroup(BaseModel):
    username: Name
    groupname: Name
    priority: int = Field(default=0, ge=-1000, le=1000)


class RoleCreate(BaseModel):
    rolename: Name
    textname: Text = ""
    textdescription: Text = ""


class RoleRef(BaseModel):
    rolename: Name


class RoleAcl(BaseModel):
    rolename: Name
    topic: Topic
    allow: bool = True
    priority: int = Field(default=0, ge=-1000, le=1000)
    acltype: AclType | None = None
    preset: Preset | None = None


class RoleAclRemove(BaseModel):
    rolename: Name
    acltype: AclType
    topic: Topic


class GroupCreate(BaseModel):
    groupname: Name
    textname: Text = ""
    textdescription: Text = ""


class GroupRef(BaseModel):
    groupname: Name


class GroupRole(BaseModel):
    groupname: Name
    rolename: Name
    priority: int = Field(default=0, ge=-1000, le=1000)


class GroupClient(BaseModel):
    groupname: Name
    username: Name
    priority: int = Field(default=0, ge=-1000, le=1000)


DefaultAclType = Literal["publishClientSend", "publishClientReceive", "subscribe", "unsubscribe"]


class DefaultAcl(BaseModel):
    acls: dict[DefaultAclType, bool]


class TestLogin(BaseModel):
    username: Name
    password: str = Field(max_length=256)
    clientid: Name | None = None
