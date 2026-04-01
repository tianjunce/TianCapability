from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.common import CapabilityExecutionError
from app.services.batch_execution import execute_batch
from app.services.idea_service import IdeaService, IdeaValidationError
from app.services.progress_writer import ProgressWriter


VALIDATE_USER_STEP_ID = "validate_user_scope"
EXECUTE_ACTION_STEP_ID = "execute_idea_action"
FORMAT_RESULT_STEP_ID = "format_idea_result"

VALIDATE_USER_LABEL = "校验用户上下文"
FORMAT_RESULT_LABEL = "整理灵感结果"

_ACTION_LABELS = {
    "create": "保存灵感记录",
    "list": "查询灵感记录",
    "delete": "删除灵感记录",
}


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    user_id = str(context.get("user_id") or "").strip()
    action = str(input.get("action") or "create").strip().lower() or "create"
    content = str(input.get("content") or "").strip()
    title = str(input.get("title") or "").strip() or None
    tags = input.get("tags")
    status = str(input.get("status") or "").strip() or None
    tag = str(input.get("tag") or "").strip() or None
    idea_id = str(input.get("idea_id") or "").strip() or None
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
    service = IdeaService()
    try:
        if items is not None:
            result = await execute_batch(
                action=action,
                items=items,
                validation_error_cls=IdeaValidationError,
                summary_label="灵感操作",
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
                    "idea_id": idea_id,
                    "content": content,
                    "title": title,
                    "tags": tags,
                    "status": status,
                    "tag": tag,
                },
            )
    except IdeaValidationError as exc:
        writer.error(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(EXECUTE_ACTION_STEP_ID, _ACTION_LABELS[action])

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return result


async def _execute_single(
    *,
    service: IdeaService,
    action: str,
    user_id: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    content = str(item.get("content") or "").strip()
    title = str(item.get("title") or "").strip() or None
    tags = item.get("tags")
    status = str(item.get("status") or "").strip() or None
    tag = str(item.get("tag") or "").strip() or None
    idea_id = str(item.get("idea_id") or "").strip() or None

    if action == "create":
        return await asyncio.to_thread(
            service.create_idea,
            user_id=user_id,
            content=content,
            title=title,
            tags=tags,
        )
    if action == "list":
        return await asyncio.to_thread(
            service.list_ideas,
            user_id=user_id,
            status=status,
            tag=tag,
        )
    return await asyncio.to_thread(
        service.delete_idea,
        user_id=user_id,
        idea_id=idea_id,
        title=title,
        content=content,
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
