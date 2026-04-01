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
            "reminder_id": reminder_id,
            "occurrence_id": occurrence_id,
            "content": normalized_content,
            "note": normalized_note,
            "remind_at": remind_at_iso,
            "status": "active",
            "summary": summary,
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
