from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.progress import ProgressContext


class CapabilityExecutionError(Exception):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CapabilityContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    progress_context: ProgressContext | None = None


class CapabilityExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any]
    context: CapabilityContext


class CapabilityError(BaseModel):
    code: str
    message: str


class CapabilityMeta(BaseModel):
    capability: str
    duration_ms: int = Field(ge=0)


class CapabilityResponse(BaseModel):
    status: Literal["success", "error"]
    data: dict[str, Any] | None
    error: CapabilityError | None
    meta: CapabilityMeta


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    kind: str = "tool"
    description: str
    method: Literal["POST"] = "POST"
    path: str | None = None
    timeout_seconds: int = Field(default=10, ge=1, le=300)
    supports_progress: bool = False
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def set_default_path(self) -> "CapabilityManifest":
        expected_path = f"/capabilities/{self.name}"
        if not self.path:
            self.path = expected_path
        elif not self.path.startswith("/"):
            self.path = f"/{self.path}"

        if self.path != expected_path:
            raise ValueError(f"path must be fixed to {expected_path}")
        return self
