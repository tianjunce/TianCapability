from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.batch_execution import execute_batch
from app.services.progress_writer import ProgressWriter
from app.services.reminder_service import ReminderService, ReminderValidationError


VALIDATE_USER_STEP_ID = "validate_user_scope"
EXECUTE_ACTION_STEP_ID = "execute_reminder_action"
FORMAT_RESULT_STEP_ID = "format_reminder_result"

VALIDATE_USER_LABEL = "校验用户上下文"
FORMAT_RESULT_LABEL = "整理提醒结果"

_ACTION_LABELS = {
    "create": "保存提醒记录",
    "list": "查询提醒记录",
    "update": "修改提醒记录",
    "cancel": "取消提醒记录",
}


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    action = str(input.get("action") or "create").strip().lower() or "create"
    content = str(input.get("content") or "").strip()
    remind_at = str(input.get("remind_at") or "").strip()
    note = str(input.get("note") or "").strip() or None
    reminder_id = str(input.get("reminder_id") or "").strip() or None
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
            message="action must be create, list, update, or cancel",
        )
    writer.success(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)

    writer.running(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])
    service = ReminderService()
    try:
        if items is not None:
            result = await execute_batch(
                action=action,
                items=items,
                validation_error_cls=ReminderValidationError,
                summary_label="提醒操作",
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
                    "content": content,
                    "remind_at": remind_at,
                    "note": note,
                    "reminder_id": reminder_id,
                    "status": status,
                },
            )
    except ReminderValidationError as exc:
        writer.error(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result


async def _execute_single(
    *,
    service: ReminderService,
    action: str,
    user_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    content = str(item.get("content") or "").strip()
    remind_at = str(item.get("remind_at") or "").strip()
    note = str(item.get("note") or "").strip() or None
    reminder_id = str(item.get("reminder_id") or "").strip() or None
    status = str(item.get("status") or "").strip() or None

    if action == "create":
        return await asyncio.to_thread(
            service.create_reminder,
            user_id=user_id,
            content=content,
            remind_at=remind_at,
            note=note,
        )
    if action == "list":
        return await asyncio.to_thread(
            service.list_reminders,
            user_id=user_id,
            status=status,
        )
    if action == "update":
        return await asyncio.to_thread(
            service.update_reminder,
            user_id=user_id,
            reminder_id=reminder_id,
            content=content or None,
            remind_at=remind_at or None,
            note=note,
        )
    return await asyncio.to_thread(
        service.cancel_reminder,
        user_id=user_id,
        reminder_id=reminder_id,
        content=content,
        remind_at=remind_at,
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
