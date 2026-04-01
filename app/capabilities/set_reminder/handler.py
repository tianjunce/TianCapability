from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.progress_writer import ProgressWriter
from app.services.reminder_service import ReminderService, ReminderValidationError


VALIDATE_USER_STEP_ID = "validate_user_scope"
CREATE_REMINDER_STEP_ID = "persist_reminder"
FORMAT_RESULT_STEP_ID = "format_reminder_result"

VALIDATE_USER_LABEL = "校验用户上下文"
CREATE_REMINDER_LABEL = "保存提醒记录"
FORMAT_RESULT_LABEL = "整理提醒结果"


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    content = str(input.get("content") or "").strip()
    remind_at = str(input.get("remind_at") or "").strip()
    note = str(input.get("note") or "").strip() or None

    writer.running(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
    if not user_id:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(code="invalid_request", message="context.user_id is required")
    writer.success(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)

    writer.running(CREATE_REMINDER_STEP_ID, CREATE_REMINDER_LABEL)
    service = ReminderService()
    try:
        result = await asyncio.to_thread(
            service.create_reminder,
            user_id=user_id,
            content=content,
            remind_at=remind_at,
            note=note,
        )
    except ReminderValidationError as exc:
        writer.error(CREATE_REMINDER_STEP_ID, CREATE_REMINDER_LABEL)
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(CREATE_REMINDER_STEP_ID, CREATE_REMINDER_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result
