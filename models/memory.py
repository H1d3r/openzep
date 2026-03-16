from typing import Any

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str
    role_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddMemoryRequest(BaseModel):
    messages: list[Message]
    return_context: bool = False


class Fact(BaseModel):
    uuid: str
    fact: str
    created_at: str | None = None
    valid_at: str | None = None
    invalid_at: str | None = None
    expired_at: str | None = None
    score: float | None = None


class MemoryContext(BaseModel):
    facts: list[Fact] = Field(default_factory=list)


class MemoryResponse(BaseModel):
    context: str = ""
    user_summary: str = ""
    facts: list[Fact] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)


class AddMemoryResponse(BaseModel):
    ok: bool = True
