from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ProgressContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    protocol: str = "jsonl_file"
    path: str | None = None
    scope: str | None = None

    @model_validator(mode="after")
    def validate_supported_protocol(self) -> "ProgressContext":
        if self.enabled and self.protocol == "jsonl_file" and not self.path:
            raise ValueError("path is required when progress protocol is jsonl_file")
        return self


class ProgressEvent(BaseModel):
    op: Literal["upsert"] = "upsert"
    step_id: str
    label: str
    status: Literal["running", "success", "error"]

