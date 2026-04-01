from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.birthday_service import BirthdayService, BirthdayValidationError
from app.services.progress_writer import ProgressWriter


VALIDATE_USER_STEP_ID = "validate_user_scope"
CREATE_BIRTHDAY_STEP_ID = "persist_birthday"
FORMAT_RESULT_STEP_ID = "format_birthday_result"

VALIDATE_USER_LABEL = "校验用户上下文"
CREATE_BIRTHDAY_LABEL = "保存生日记录"
FORMAT_RESULT_LABEL = "整理生日结果"


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    name = str(input.get("name") or "").strip()
    birthday = str(input.get("birthday") or "").strip()
    calendar_type = str(input.get("calendar_type") or "").strip() or None
    birth_year = input.get("birth_year")
    is_leap_month = input.get("is_leap_month")
    notes = str(input.get("notes") or "").strip() or None

    writer.running(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
    if not user_id:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(code="invalid_request", message="context.user_id is required")
    writer.success(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)

    writer.running(CREATE_BIRTHDAY_STEP_ID, CREATE_BIRTHDAY_LABEL)
    service = BirthdayService()
    try:
        result = await asyncio.to_thread(
            service.create_birthday,
            user_id=user_id,
            name=name,
            birthday=birthday,
            calendar_type=calendar_type,
            birth_year=birth_year,
            is_leap_month=is_leap_month,
            notes=notes,
        )
    except BirthdayValidationError as exc:
        writer.error(CREATE_BIRTHDAY_STEP_ID, CREATE_BIRTHDAY_LABEL)
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(CREATE_BIRTHDAY_STEP_ID, CREATE_BIRTHDAY_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result
