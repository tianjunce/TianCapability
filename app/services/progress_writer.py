from __future__ import annotations

import redis
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.progress import ProgressContext, ProgressEvent
from app.services.env_config import get_config_value


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
        if self.progress_context.protocol == "redis":
            self._write_to_redis(event)
            return

        path = Path(self.progress_context.path or "")
        try:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json())
                stream.write("\n")
                stream.flush()
        except Exception:
            return

    def _write_to_redis(self, event: ProgressEvent) -> None:
        key = str(self.progress_context.key or "").strip()
        if not key:
            return

        try:
            client = redis.Redis(
                host=get_config_value("REDIS_HOST", "localhost"),
                port=int(get_config_value("REDIS_PORT", "6379")),
                db=int(get_config_value("REDIS_DB", "0")),
                password=get_config_value("REDIS_PASSWORD", "") or None,
                decode_responses=False,
            )
            client.rpush(key, event.model_dump_json())
            client.expire(key, 600)
        except Exception:
            return

    def _is_enabled(self) -> bool:
        if not self.progress_context or not self.progress_context.enabled:
            return False

        if self.progress_context.protocol == "jsonl_file":
            return bool(self.progress_context.path)

        if self.progress_context.protocol == "redis":
            return bool(self.progress_context.key)

        return False

