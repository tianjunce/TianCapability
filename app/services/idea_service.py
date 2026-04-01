from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from app.services.repositories import IdeaRepository


class IdeaValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class IdeaService:
    def __init__(
        self,
        *,
        idea_repository: IdeaRepository | None = None,
    ) -> None:
        self.idea_repository = idea_repository or IdeaRepository()

    def create_idea(
        self,
        *,
        user_id: str,
        content: str,
        title: str | None = None,
        tags: Any = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_content = str(content or "").strip()
        normalized_title = str(title or "").strip() or None
        normalized_tags = _normalize_tags(tags)

        if not normalized_user_id:
            raise IdeaValidationError(code="invalid_request", message="context.user_id is required")
        if not normalized_content:
            raise IdeaValidationError(code="invalid_input", message="field 'content' is required")

        created_at = _now().isoformat(timespec="seconds")
        idea_id = uuid4().hex
        idea_record = {
            "id": idea_id,
            "user_id": normalized_user_id,
            "title": normalized_title,
            "content": normalized_content,
            "tags": normalized_tags,
            "status": "active",
            "created_at": created_at,
            "updated_at": created_at,
        }
        self.idea_repository.create(idea_record)

        summary_label = normalized_title or _build_excerpt(normalized_content)
        summary = f"已记录灵感：{summary_label}。"

        return {
            "idea_id": idea_id,
            "title": normalized_title,
            "content": normalized_content,
            "tags": normalized_tags,
            "status": "active",
            "summary": summary,
        }


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _normalize_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        candidate_items = [segment.strip() for segment in value.split(",")]
    elif isinstance(value, list):
        candidate_items = [str(item).strip() for item in value]
    else:
        raise IdeaValidationError(code="invalid_tags", message="tags must be an array of strings")

    normalized_tags: list[str] = []
    seen: set[str] = set()
    for item in candidate_items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        normalized_tags.append(item)
    return normalized_tags


def _build_excerpt(content: str, max_length: int = 24) -> str:
    if len(content) <= max_length:
        return content
    return f"{content[:max_length].rstrip()}..."
