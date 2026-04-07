from __future__ import annotations

import asyncio
import re
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.batch_execution import execute_batch
from app.services.progress_writer import ProgressWriter
from app.services.todo_service import TodoService, TodoValidationError


VALIDATE_USER_STEP_ID = "validate_user_scope"
EXECUTE_ACTION_STEP_ID = "execute_todo_action"
FORMAT_RESULT_STEP_ID = "format_todo_result"

VALIDATE_USER_LABEL = "校验用户上下文"
FORMAT_RESULT_LABEL = "整理待办结果"

_ACTION_LABELS = {
    "create": "保存待办记录",
    "list": "查询待办记录",
    "update": "修改待办记录",
    "complete": "完成待办记录",
    "delete": "删除待办记录",
}

_NORMALIZED_INPUT_KEYS = {
    "action",
    "todo_id",
    "title",
    "notes",
    "deadline",
    "progress_percent",
    "difficulty",
    "status",
    "time_range",
    "items",
}
_TODO_IDENTIFIER_PATTERN = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
_LATEST_TODO_ALIASES = {"latest", "latest_created"}


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    normalized_input = _normalize_input_payload(input)
    user_id = str(context.get("user_id") or "").strip()
    action = _resolve_action(normalized_input)
    title = str(normalized_input.get("title") or "").strip()
    notes = str(normalized_input.get("notes") or "").strip() or None
    deadline = str(normalized_input.get("deadline") or "").strip() or None
    progress_percent = normalized_input.get("progress_percent")
    difficulty = str(normalized_input.get("difficulty") or "").strip() or None
    todo_id = str(normalized_input.get("todo_id") or "").strip() or None
    status = str(normalized_input.get("status") or "").strip() or None
    time_range = str(normalized_input.get("time_range") or "").strip() or None
    raw_items = normalized_input.get("items")
    items = _normalize_items(raw_items)

    writer.running(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
    if not user_id:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(code="invalid_request", message="context.user_id is required")
    if action not in _ACTION_LABELS:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(
            code="invalid_action",
            message="action must be create, list, update, complete, or delete",
        )
    writer.success(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)

    writer.running(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])
    service = TodoService()
    try:
        if items is not None:
            result = await execute_batch(
                action=action,
                items=items,
                validation_error_cls=TodoValidationError,
                summary_label="待办操作",
                execute_item=lambda item: _execute_single(
                    service=service,
                    action=action,
                    user_id=user_id,
                    item=item,
                ),
            )
        else:
            result = await _execute_single(
                service=service,
                action=action,
                user_id=user_id,
                item={
                    "todo_id": todo_id,
                    "title": title,
                    "notes": notes,
                    "deadline": deadline,
                    "progress_percent": progress_percent,
                    "difficulty": difficulty,
                    "status": status,
                    "time_range": time_range,
                },
            )
    except TodoValidationError as exc:
        writer.error(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result


async def _execute_single(
    *,
    service: TodoService,
    action: str,
    user_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    title = str(item.get("title") or "").strip()
    notes = str(item.get("notes") or "").strip() or None
    deadline = str(item.get("deadline") or "").strip() or None
    progress_percent = item.get("progress_percent")
    difficulty = str(item.get("difficulty") or "").strip() or None
    todo_id = str(item.get("todo_id") or "").strip() or None
    status = str(item.get("status") or "").strip() or None
    time_range = str(item.get("time_range") or "").strip() or None

    if action in {"update", "complete", "delete"} and todo_id:
        normalized_todo_id = todo_id.strip().lower()
        if normalized_todo_id in _LATEST_TODO_ALIASES:
            todo_id = _resolve_latest_todo_identifier(
                service=service,
                action=action,
                user_id=user_id,
                title=title or None,
            )
        elif not title and not _looks_like_todo_identifier(todo_id):
            title = todo_id
            todo_id = None

    if action == "create":
        return await asyncio.to_thread(
            service.create_todo,
            user_id=user_id,
            title=title,
            notes=notes,
            deadline=deadline,
            progress_percent=progress_percent,
            difficulty=difficulty,
        )
    if action == "list":
        return await asyncio.to_thread(
            service.list_todos,
            user_id=user_id,
            status=status,
            time_range=time_range,
        )
    if action == "update":
        return await asyncio.to_thread(
            service.update_todo,
            user_id=user_id,
            todo_id=todo_id,
            title=title or None,
            notes=notes,
            deadline=deadline,
            progress_percent=progress_percent,
            difficulty=difficulty,
        )
    if action == "complete":
        return await asyncio.to_thread(
            service.complete_todo,
            user_id=user_id,
            todo_id=todo_id,
            title=title,
        )
    return await asyncio.to_thread(
        service.delete_todo,
        user_id=user_id,
        todo_id=todo_id,
        title=title,
    )


def _normalize_items(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise CapabilityExecutionError(code="invalid_input", message="field 'items' must be a non-empty array")
    normalized_items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise CapabilityExecutionError(code="invalid_input", message="each item in 'items' must be an object")
        normalized_items.append(item)
    return normalized_items


def _normalize_input_payload(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for source in (value.get("slots"), value.get("context")):
        if not isinstance(source, dict):
            continue
        for key in _NORMALIZED_INPUT_KEYS:
            if _has_value(normalized.get(key)):
                continue
            if _has_value(source.get(key)):
                normalized[key] = source.get(key)
    return normalized


def _resolve_action(input: dict[str, Any]) -> str:
    action = str(input.get("action") or "").strip().lower()
    if action:
        return action
    if _has_value(input.get("status")) or _has_value(input.get("time_range")):
        return "list"

    for key in ("todo_id", "title", "notes", "deadline", "progress_percent", "difficulty", "items"):
        if _has_value(input.get(key)):
            return "create"
    return "list"


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def _looks_like_todo_identifier(value: Any) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized and _TODO_IDENTIFIER_PATTERN.fullmatch(normalized))


def _resolve_latest_todo_identifier(
    *,
    service: TodoService,
    action: str,
    user_id: str,
    title: str | None,
) -> str | None:
    allowed_statuses = {"open"} if action in {"update", "complete"} else {"open", "completed", "deleted"}
    normalized_title = str(title or "").strip() or None
    candidates = [
        item
        for item in service.todo_repository.list_by_user(user_id)
        if str(item.get("status") or "").strip() in allowed_statuses
        and (normalized_title is None or str(item.get("title") or "").strip() == normalized_title)
    ]
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("id") or ""),
        )
    )
    return str(candidates[-1].get("id") or "").strip() or None
