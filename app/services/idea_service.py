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
            "action": "create",
            "idea_id": idea_id,
            "title": normalized_title,
            "content": normalized_content,
            "tags": normalized_tags,
            "status": "active",
            "summary": summary,
        }

    def list_ideas(
        self,
        *,
        user_id: str,
        status: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_status = _normalize_idea_status_filter(status)
        normalized_tag = str(tag or "").strip() or None

        if not normalized_user_id:
            raise IdeaValidationError(code="invalid_request", message="context.user_id is required")

        ideas = self.idea_repository.list_by_user(normalized_user_id)
        if normalized_status is not None:
            ideas = [item for item in ideas if str(item.get("status") or "").strip() == normalized_status]
        else:
            ideas = [item for item in ideas if str(item.get("status") or "").strip() != "deleted"]
        if normalized_tag is not None:
            ideas = [
                item
                for item in ideas
                if normalized_tag in [str(tag_item).strip() for tag_item in (item.get("tags") or [])]
            ]

        ideas = sorted(
            ideas,
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )

        return {
            "action": "list",
            "ideas": ideas,
            "total": len(ideas),
            "summary": _build_idea_list_summary(total=len(ideas), status=normalized_status, tag=normalized_tag),
        }

    def delete_idea(
        self,
        *,
        user_id: str,
        idea_id: str | None = None,
        title: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_idea_id = str(idea_id or "").strip() or None
        normalized_title = str(title or "").strip() or None
        normalized_content = str(content or "").strip() or None

        if not normalized_user_id:
            raise IdeaValidationError(code="invalid_request", message="context.user_id is required")
        if normalized_idea_id is None and normalized_title is None and normalized_content is None:
            raise IdeaValidationError(code="invalid_input", message="delete requires idea_id, title, or content")

        idea_record = _resolve_idea_for_delete(
            repository=self.idea_repository,
            user_id=normalized_user_id,
            idea_id=normalized_idea_id,
            title=normalized_title,
            content=normalized_content,
        )
        if idea_record is None:
            raise IdeaValidationError(code="idea_not_found", message="未找到要删除的灵感记录")
        if str(idea_record.get("status") or "").strip() == "deleted":
            raise IdeaValidationError(code="idea_not_deletable", message="该灵感记录已经删除")

        resolved_idea_id = str(idea_record.get("id") or "")

        deleted_at = _now().isoformat(timespec="seconds")
        updated_record = self.idea_repository.update_fields(
            user_id=normalized_user_id,
            idea_id=resolved_idea_id,
            fields={
                "status": "deleted",
                "updated_at": deleted_at,
                "deleted_at": deleted_at,
            },
        )
        if updated_record is None:
            raise IdeaValidationError(code="idea_not_found", message="未找到要删除的灵感记录")

        summary_label = str(updated_record.get("title") or "").strip() or _build_excerpt(
            str(updated_record.get("content") or "").strip()
        )
        return {
            "action": "delete",
            "idea_id": resolved_idea_id,
            "status": "deleted",
            "summary": f"已删除灵感：{summary_label}。",
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


def _normalize_idea_status_filter(value: str | None) -> str | None:
    normalized_value = str(value or "").strip().lower() or None
    if normalized_value is None:
        return None
    if normalized_value in {"active", "deleted"}:
        return normalized_value
    raise IdeaValidationError(code="invalid_status", message="status must be active or deleted")


def _build_idea_list_summary(*, total: int, status: str | None, tag: str | None) -> str:
    if total == 0:
        if tag is not None:
            return f"当前没有标签为 {tag} 的灵感记录。"
        if status is None:
            return "当前没有灵感记录。"
        return f"当前没有状态为 {status} 的灵感记录。"
    if tag is not None:
        return f"共找到 {total} 条标签为 {tag} 的灵感记录。"
    if status is None:
        return f"共找到 {total} 条灵感记录。"
    return f"共找到 {total} 条状态为 {status} 的灵感记录。"


def _resolve_idea_for_delete(
    *,
    repository: IdeaRepository,
    user_id: str,
    idea_id: str | None,
    title: str | None,
    content: str | None,
) -> dict[str, Any]:
    if idea_id is not None:
        idea_record = repository.get_by_id(user_id=user_id, idea_id=idea_id)
        if idea_record is None:
            raise IdeaValidationError(code="idea_not_found", message="未找到要删除的灵感记录")
        return idea_record

    if title is not None:
        matched_items = repository.find_by_title(
            user_id=user_id,
            title=title,
            statuses={"active"},
        )
        if not matched_items:
            deleted_items = repository.find_by_title(
                user_id=user_id,
                title=title,
                statuses={"deleted"},
            )
            if len(deleted_items) == 1:
                return deleted_items[0]
            raise IdeaValidationError(code="idea_not_found", message="未找到要删除的灵感记录")
        if len(matched_items) > 1:
            raise IdeaValidationError(
                code="ambiguous_idea",
                message="找到了多条同名灵感，请提供 idea_id 或更具体内容",
            )
        return matched_items[0]

    matched_items = repository.find_by_content(
        user_id=user_id,
        content=content or "",
        statuses={"active"},
    )
    if not matched_items:
        deleted_items = repository.find_by_content(
            user_id=user_id,
            content=content or "",
            statuses={"deleted"},
        )
        if len(deleted_items) == 1:
            return deleted_items[0]
        raise IdeaValidationError(code="idea_not_found", message="未找到要删除的灵感记录")
    if len(matched_items) > 1:
        raise IdeaValidationError(
            code="ambiguous_idea",
            message="找到了多条内容相同的灵感，请提供 idea_id 或标题",
        )
    return matched_items[0]
