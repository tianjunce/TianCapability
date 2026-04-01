from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.idea_service import IdeaService, IdeaValidationError
from app.services.progress_writer import ProgressWriter


VALIDATE_USER_STEP_ID = "validate_user_scope"
CREATE_IDEA_STEP_ID = "persist_idea"
FORMAT_RESULT_STEP_ID = "format_idea_result"

VALIDATE_USER_LABEL = "校验用户上下文"
CREATE_IDEA_LABEL = "保存灵感记录"
FORMAT_RESULT_LABEL = "整理灵感结果"


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    content = str(input.get("content") or "").strip()
    title = str(input.get("title") or "").strip() or None
    tags = input.get("tags")

    writer.running(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
    if not user_id:
        writer.error(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)
        raise CapabilityExecutionError(code="invalid_request", message="context.user_id is required")
    writer.success(VALIDATE_USER_STEP_ID, VALIDATE_USER_LABEL)

    writer.running(CREATE_IDEA_STEP_ID, CREATE_IDEA_LABEL)
    service = IdeaService()
    try:
        result = await asyncio.to_thread(
            service.create_idea,
            user_id=user_id,
            content=content,
            title=title,
            tags=tags,
        )
    except IdeaValidationError as exc:
        writer.error(CREATE_IDEA_STEP_ID, CREATE_IDEA_LABEL)
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(CREATE_IDEA_STEP_ID, CREATE_IDEA_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result
