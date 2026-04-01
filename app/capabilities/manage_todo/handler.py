from __future__ import annotations

import asyncio
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


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    action = str(input.get("action") or "create").strip().lower() or "create"
    title = str(input.get("title") or "").strip()
    notes = str(input.get("notes") or "").strip() or None
    deadline = str(input.get("deadline") or "").strip() or None
    progress_percent = input.get("progress_percent")
    difficulty = str(input.get("difficulty") or "").strip() or None
    todo_id = str(input.get("todo_id") or "").strip() or None
    status = str(input.get("status") or "").strip() or None
    raw_items = input.get("items")
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
