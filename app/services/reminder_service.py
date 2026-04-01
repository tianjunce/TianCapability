from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from app.services.repositories import ReminderOccurrenceRepository, ReminderRepository


_REMIND_AT_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


class ReminderValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ReminderService:
    def __init__(
        self,
        *,
        reminder_repository: ReminderRepository | None = None,
        occurrence_repository: ReminderOccurrenceRepository | None = None,
    ) -> None:
        self.reminder_repository = reminder_repository or ReminderRepository()
        self.occurrence_repository = occurrence_repository or ReminderOccurrenceRepository()

    def create_reminder(
        self,
        *,
        user_id: str,
        content: str,
        remind_at: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_content = str(content or "").strip()
        normalized_remind_at = str(remind_at or "").strip()
        normalized_note = str(note or "").strip() or None

        if not normalized_user_id:
            raise ReminderValidationError(code="invalid_request", message="context.user_id is required")
        if not normalized_content:
            raise ReminderValidationError(code="invalid_input", message="field 'content' is required")
        if not normalized_remind_at:
            raise ReminderValidationError(code="invalid_input", message="field 'remind_at' is required")

        remind_at_value = _parse_remind_at(normalized_remind_at)
        now = datetime.now().replace(microsecond=0)
        if remind_at_value <= now:
            raise ReminderValidationError(code="reminder_in_past", message="提醒时间必须晚于当前时间")

        created_at = datetime.now().replace(microsecond=0).isoformat()
        remind_at_iso = remind_at_value.isoformat(timespec="seconds")
        reminder_id = uuid4().hex
        occurrence_id = uuid4().hex

        reminder_record = {
            "id": reminder_id,
            "user_id": normalized_user_id,
            "content": normalized_content,
            "note": normalized_note,
            "remind_at": remind_at_iso,
            "status": "active",
            "created_at": created_at,
            "updated_at": created_at,
        }
        occurrence_record = {
            "id": occurrence_id,
            "user_id": normalized_user_id,
            "source_type": "set_reminder",
            "source_label": "自定义提醒",
            "source_id": reminder_id,
            "remind_at": remind_at_iso,
            "title": normalized_content,
            "content": normalized_note or normalized_content,
            "payload_json": {
                "content": normalized_content,
                "note": normalized_note,
            },
            "dedupe_key": f"set_reminder:{reminder_id}:{remind_at_iso}",
            "status": "pending",
            "created_at": created_at,
            "updated_at": created_at,
        }

        self.reminder_repository.create(reminder_record)
        self.occurrence_repository.create(occurrence_record)

        summary = f"已创建提醒：{remind_at_value.strftime('%Y-%m-%d %H:%M')} 提醒你 {normalized_content}。"
        if normalized_note:
            summary = (
                f"已创建提醒：{remind_at_value.strftime('%Y-%m-%d %H:%M')} 提醒你 {normalized_content}。"
                f"备注：{normalized_note}"
            )

        return {
            "action": "create",
            "reminder_id": reminder_id,
            "occurrence_id": occurrence_id,
            "content": normalized_content,
            "note": normalized_note,
            "remind_at": remind_at_iso,
            "status": "active",
            "summary": summary,
        }

    def list_reminders(
        self,
        *,
        user_id: str,
        status: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_status = _normalize_reminder_status_filter(status)

        if not normalized_user_id:
            raise ReminderValidationError(code="invalid_request", message="context.user_id is required")

        reminders = self.reminder_repository.list_by_user(normalized_user_id)
        if normalized_status is not None:
            reminders = [
                item for item in reminders if str(item.get("status") or "").strip() == normalized_status
            ]

        reminders = sorted(
            reminders,
            key=lambda item: (
                str(item.get("remind_at") or ""),
                str(item.get("created_at") or ""),
            ),
        )

        return {
            "action": "list",
            "reminders": reminders,
            "total": len(reminders),
            "summary": _build_reminder_list_summary(total=len(reminders), status=normalized_status),
        }

    def update_reminder(
        self,
        *,
        user_id: str,
        reminder_id: str | None = None,
        content: str | None = None,
        remind_at: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_reminder_id = str(reminder_id or "").strip() or None
        normalized_content = str(content or "").strip() or None
        normalized_remind_at = str(remind_at or "").strip() or None
        normalized_note = str(note or "").strip() or None

        if not normalized_user_id:
            raise ReminderValidationError(code="invalid_request", message="context.user_id is required")
        if normalized_reminder_id is None and normalized_content is None:
            raise ReminderValidationError(code="invalid_input", message="update requires reminder_id or current content")
        if normalized_content is None and normalized_remind_at is None and normalized_note is None:
            raise ReminderValidationError(code="invalid_input", message="update requires at least one changed field")

        reminder_record = _resolve_reminder_for_update(
            repository=self.reminder_repository,
            user_id=normalized_user_id,
            reminder_id=normalized_reminder_id,
            content=normalized_content,
        )
        if reminder_record is None:
            raise ReminderValidationError(code="reminder_not_found", message="未找到要修改的提醒")

        reminder_status = str(reminder_record.get("status") or "").strip()
        if reminder_status not in {"active", "failed"}:
            raise ReminderValidationError(
                code="reminder_not_editable",
                message="该提醒当前状态不可修改",
            )

        resolved_reminder_id = str(reminder_record.get("id") or "")
        next_content = normalized_content or str(reminder_record.get("content") or "").strip()
        next_note = normalized_note if normalized_note is not None else (reminder_record.get("note") or None)
        next_remind_at_iso = str(reminder_record.get("remind_at") or "").strip()

        if normalized_content is not None and not next_content:
            raise ReminderValidationError(code="invalid_input", message="field 'content' cannot be empty")

        if normalized_remind_at is not None:
            remind_at_value = _parse_remind_at(normalized_remind_at)
            now = datetime.now().replace(microsecond=0)
            if remind_at_value <= now:
                raise ReminderValidationError(code="reminder_in_past", message="提醒时间必须晚于当前时间")
            next_remind_at_iso = remind_at_value.isoformat(timespec="seconds")

        updated_at = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
        updated_record = self.reminder_repository.update_fields(
            user_id=normalized_user_id,
            reminder_id=resolved_reminder_id,
            fields={
                "content": next_content,
                "note": next_note,
                "remind_at": next_remind_at_iso,
                "status": "active",
                "updated_at": updated_at,
                "last_error": None,
            },
        )
        if updated_record is None:
            raise ReminderValidationError(code="reminder_not_found", message="未找到要修改的提醒")

        cancelled_occurrences = self.occurrence_repository.update_status_by_source(
            user_id=normalized_user_id,
            source_type="set_reminder",
            source_id=resolved_reminder_id,
            status="cancelled",
            updated_at=updated_at,
            from_statuses={"pending", "failed"},
        )

        occurrence_id = uuid4().hex
        self.occurrence_repository.create(
            {
                "id": occurrence_id,
                "user_id": normalized_user_id,
                "source_type": "set_reminder",
                "source_label": "自定义提醒",
                "source_id": resolved_reminder_id,
                "remind_at": next_remind_at_iso,
                "title": next_content,
                "content": next_note or next_content,
                "payload_json": {
                    "content": next_content,
                    "note": next_note,
                },
                "dedupe_key": f"set_reminder:{resolved_reminder_id}:{next_remind_at_iso}",
                "status": "pending",
                "created_at": updated_at,
                "updated_at": updated_at,
            }
        )

        return {
            "action": "update",
            "reminder_id": resolved_reminder_id,
            "occurrence_id": occurrence_id,
            "content": next_content,
            "note": next_note,
            "remind_at": next_remind_at_iso,
            "status": "active",
            "cancelled_occurrence_ids": [
                str(item.get("id") or "")
                for item in cancelled_occurrences
                if str(item.get("id") or "").strip()
            ],
            "summary": f"已更新提醒：{next_remind_at_iso} 提醒你 {next_content}。",
        }

    def cancel_reminder(
        self,
        *,
        user_id: str,
        reminder_id: str | None = None,
        content: str | None = None,
        remind_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_reminder_id = str(reminder_id or "").strip() or None
        normalized_content = str(content or "").strip() or None
        normalized_remind_at = str(remind_at or "").strip() or None

        if not normalized_user_id:
            raise ReminderValidationError(code="invalid_request", message="context.user_id is required")
        if normalized_reminder_id is None and normalized_content is None:
            raise ReminderValidationError(
                code="invalid_input",
                message="cancel requires reminder_id or content",
            )

        reminder_record = _resolve_reminder_for_cancel(
            repository=self.reminder_repository,
            user_id=normalized_user_id,
            reminder_id=normalized_reminder_id,
            content=normalized_content,
            remind_at=normalized_remind_at,
        )
        reminder_status = str(reminder_record.get("status") or "").strip()
        if reminder_status not in {"active", "failed"}:
            raise ReminderValidationError(
                code="reminder_not_cancellable",
                message="该提醒当前状态不可取消",
            )

        cancelled_at = datetime.now().replace(microsecond=0).isoformat(timespec="seconds")
        updated_record = self.reminder_repository.update_fields(
            user_id=normalized_user_id,
            reminder_id=str(reminder_record["id"]),
            fields={
                "status": "cancelled",
                "updated_at": cancelled_at,
                "cancelled_at": cancelled_at,
                "last_error": None,
            },
        )
        if updated_record is None:
            raise ReminderValidationError(code="reminder_not_found", message="未找到要取消的提醒")

        updated_occurrences = self.occurrence_repository.update_status_by_source(
            user_id=normalized_user_id,
            source_type="set_reminder",
            source_id=str(reminder_record["id"]),
            status="cancelled",
            updated_at=cancelled_at,
            from_statuses={"pending", "failed"},
        )

        return {
            "action": "cancel",
            "reminder_id": str(updated_record["id"]),
            "content": str(updated_record.get("content") or ""),
            "note": updated_record.get("note"),
            "remind_at": str(updated_record.get("remind_at") or ""),
            "status": "cancelled",
            "cancelled_occurrence_ids": [
                str(item.get("id") or "")
                for item in updated_occurrences
                if str(item.get("id") or "").strip()
            ],
            "summary": (
                f"已取消提醒：{str(updated_record.get('content') or '')}，"
                f"原提醒时间 {str(updated_record.get('remind_at') or '')}。"
            ),
        }


def _parse_remind_at(value: str) -> datetime:
    for fmt in _REMIND_AT_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ReminderValidationError(
        code="invalid_datetime",
        message="不支持的提醒时间格式，请使用 YYYY-MM-DD HH:MM",
    )


def _normalize_reminder_status_filter(value: str | None) -> str | None:
    normalized_value = str(value or "").strip().lower() or None
    if normalized_value is None:
        return None
    if normalized_value in {"active", "failed", "delivered", "cancelled"}:
        return normalized_value
    raise ReminderValidationError(
        code="invalid_status",
        message="status must be active, failed, delivered, or cancelled",
    )


def _resolve_reminder_for_cancel(
    *,
    repository: ReminderRepository,
    user_id: str,
    reminder_id: str | None,
    content: str | None,
    remind_at: str | None,
) -> dict[str, Any]:
    if reminder_id is not None:
        reminder_record = repository.get_by_id(user_id=user_id, reminder_id=reminder_id)
        if reminder_record is None:
            raise ReminderValidationError(code="reminder_not_found", message="未找到要取消的提醒")
        return reminder_record

    matched_items = repository.find_by_content(
        user_id=user_id,
        content=content or "",
        remind_at=remind_at,
        statuses={"active", "failed"},
    )
    if not matched_items:
        raise ReminderValidationError(code="reminder_not_found", message="未找到要取消的提醒")
    if len(matched_items) > 1:
        raise ReminderValidationError(
            code="ambiguous_reminder",
            message="找到了多条同名提醒，请提供更具体的提醒时间或 reminder_id",
        )
    return matched_items[0]


def _resolve_reminder_for_update(
    *,
    repository: ReminderRepository,
    user_id: str,
    reminder_id: str | None,
    content: str | None,
) -> dict[str, Any]:
    if reminder_id is not None:
        reminder_record = repository.get_by_id(user_id=user_id, reminder_id=reminder_id)
        if reminder_record is None:
            raise ReminderValidationError(code="reminder_not_found", message="未找到要修改的提醒")
        return reminder_record

    matched_items = repository.find_by_content(
        user_id=user_id,
        content=content or "",
        statuses={"active", "failed"},
    )
    if not matched_items:
        raise ReminderValidationError(code="reminder_not_found", message="未找到要修改的提醒")
    if len(matched_items) > 1:
        raise ReminderValidationError(
            code="ambiguous_reminder",
            message="找到了多条同内容提醒，请提供 reminder_id",
        )
    return matched_items[0]


def _build_reminder_list_summary(*, total: int, status: str | None) -> str:
    if total == 0:
        if status is None:
            return "当前没有提醒记录。"
        return f"当前没有状态为 {status} 的提醒记录。"
    if status is None:
        return f"共找到 {total} 条提醒记录。"
    return f"共找到 {total} 条状态为 {status} 的提醒记录。"
