from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.batch_execution import execute_batch
from app.services.birthday_service import BirthdayService, BirthdayValidationError
from app.services.progress_writer import ProgressWriter


VALIDATE_USER_STEP_ID = "validate_user_scope"
EXECUTE_ACTION_STEP_ID = "execute_birthday_action"
FORMAT_RESULT_STEP_ID = "format_birthday_result"

VALIDATE_USER_LABEL = "校验用户上下文"
FORMAT_RESULT_LABEL = "整理生日结果"

_ACTION_LABELS = {
    "create": "保存生日记录",
    "list": "查询生日记录",
    "delete": "删除生日记录",
}


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    action = str(input.get("action") or "create").strip().lower() or "create"
    name = str(input.get("name") or "").strip()
    birthday = str(input.get("birthday") or "").strip()
    calendar_type = str(input.get("calendar_type") or "").strip() or None
    birth_year = input.get("birth_year")
    is_leap_month = input.get("is_leap_month")
    notes = str(input.get("notes") or "").strip() or None
    status = str(input.get("status") or "").strip() or None
    birthday_id = str(input.get("birthday_id") or "").strip() or None
    raw_items = input.get("items")
    items = _normalize_items(raw_items)

    writer.running(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
    if not user_id:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(code="invalid_request", message="context.user_id is required")
    if action not in _ACTION_LABELS:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(code="invalid_action", message="action must be create, list, or delete")
    writer.success(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)

    writer.running(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])
    service = BirthdayService()
    try:
        if items is not None:
            result = await execute_batch(
                action=action,
                items=items,
                validation_error_cls=BirthdayValidationError,
                summary_label="生日操作",
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
                    "birthday_id": birthday_id,
                    "name": name,
                    "birthday": birthday,
                    "calendar_type": calendar_type,
                    "birth_year": birth_year,
                    "is_leap_month": is_leap_month,
                    "notes": notes,
                    "status": status,
                },
            )
    except BirthdayValidationError as exc:
        writer.error(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result


async def _execute_single(
    *,
    service: BirthdayService,
    action: str,
    user_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    birthday = str(item.get("birthday") or "").strip()
    calendar_type = str(item.get("calendar_type") or "").strip() or None
    birth_year = item.get("birth_year")
    is_leap_month = item.get("is_leap_month")
    notes = str(item.get("notes") or "").strip() or None
    status = str(item.get("status") or "").strip() or None
    birthday_id = str(item.get("birthday_id") or "").strip() or None

    if action == "create":
        return await asyncio.to_thread(
            service.create_birthday,
            user_id=user_id,
            name=name,
            birthday=birthday,
            calendar_type=calendar_type,
            birth_year=birth_year,
            is_leap_month=is_leap_month,
            notes=notes,
        )
    if action == "list":
        return await asyncio.to_thread(
            service.list_birthdays,
            user_id=user_id,
            name=name or None,
            status=status,
        )
    return await asyncio.to_thread(
        service.delete_birthday,
        user_id=user_id,
        birthday_id=birthday_id,
        name=name,
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
