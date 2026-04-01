from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.progress_writer import ProgressWriter
from app.services.todo_service import TodoService, TodoValidationError


VALIDATE_USER_STEP_ID = "validate_user_scope"
CREATE_TODO_STEP_ID = "persist_todo"
FORMAT_RESULT_STEP_ID = "format_todo_result"

VALIDATE_USER_LABEL = "校验用户上下文"
CREATE_TODO_LABEL = "保存待办记录"
FORMAT_RESULT_LABEL = "整理待办结果"


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    title = str(input.get("title") or "").strip()
    notes = str(input.get("notes") or "").strip() or None
    deadline = str(input.get("deadline") or "").strip() or None
    progress_percent = input.get("progress_percent")
    difficulty = str(input.get("difficulty") or "").strip() or None

    writer.running(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
    if not user_id:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(code="invalid_request", message="context.user_id is required")
    writer.success(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)

    writer.running(CREATE_TODO_STEP_ID, CREATE_TODO_LABEL)
    service = TodoService()
    try:
        result = await asyncio.to_thread(
            service.create_todo,
            user_id=user_id,
            title=title,
            notes=notes,
            deadline=deadline,
            progress_percent=progress_percent,
            difficulty=difficulty,
        )
    except TodoValidationError as exc:
        writer.error(CREATE_TODO_STEP_ID, CREATE_TODO_LABEL)
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(CREATE_TODO_STEP_ID, CREATE_TODO_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result
