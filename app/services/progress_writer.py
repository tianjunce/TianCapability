from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.progress import ProgressContext, ProgressEvent


class ProgressWriter:
    def __init__(self, progress_context: ProgressContext | None = None) -> None:
        self.progress_context = progress_context

    @classmethod
    def from_context(cls, context: dict[str, Any] | None) -> "ProgressWriter":
        if not isinstance(context, dict):
            return cls()
        raw_progress = context.get("progress_context")
        if not isinstance(raw_progress, dict):
            return cls()
        try:
            return cls(progress_context=ProgressContext.model_validate(raw_progress))
        except ValidationError:
            return cls()

    def running(self, step_id: str, label: str) -> None:
        self.upsert(step_id=step_id, label=label, status="running")

    def success(self, step_id: str, label: str) -> None:
        self.upsert(step_id=step_id, label=label, status="success")

    def error(self, step_id: str, label: str) -> None:
        self.upsert(step_id=step_id, label=label, status="error")

    def upsert(self, *, step_id: str, label: str, status: str) -> None:
        if not self._is_enabled():
            return

        event = ProgressEvent(step_id=step_id, label=label, status=status)
        path = Path(self.progress_context.path or "")
        try:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json())
                stream.write("\n")
                stream.flush()
        except Exception:
            return

    def _is_enabled(self) -> bool:
        return bool(
            self.progress_context
            and self.progress_context.enabled
            and self.progress_context.protocol == "jsonl_file"
            and self.progress_context.path
        )

