from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ProgressContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    protocol: str = "jsonl_file"
    path: str | None = None
    key: str | None = None
    scope: str | None = None

    @model_validator(mode="after")
    def validate_supported_protocol(self) -> "ProgressContext":
        if not self.enabled:
            return self
        if self.protocol == "jsonl_file" and not self.path:
            raise ValueError("path is required when progress protocol is jsonl_file")
        if self.protocol == "redis" and not self.key:
            raise ValueError("key is required when progress protocol is redis")
        return self


class ProgressEvent(BaseModel):
    op: Literal["upsert"] = "upsert"
    step_id: str
    label: str
    status: Literal["running", "success", "error"]

