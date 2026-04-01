from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.services.repositories import ReminderOccurrenceRepository, TodoRepository


_TODO_DEADLINE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)
_TODO_DATE_ONLY_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
)


class TodoValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TodoService:
    def __init__(
        self,
        *,
        todo_repository: TodoRepository | None = None,
        occurrence_repository: ReminderOccurrenceRepository | None = None,
    ) -> None:
        self.todo_repository = todo_repository or TodoRepository()
        self.occurrence_repository = occurrence_repository or ReminderOccurrenceRepository()

    def create_todo(
        self,
        *,
        user_id: str,
        title: str,
        notes: str | None = None,
        deadline: str | None = None,
        progress_percent: Any = None,
        difficulty: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_title = str(title or "").strip()
        normalized_notes = str(notes or "").strip() or None
        normalized_deadline = str(deadline or "").strip() or None
        normalized_difficulty = str(difficulty or "").strip() or None

        if not normalized_user_id:
            raise TodoValidationError(code="invalid_request", message="context.user_id is required")
        if not normalized_title:
            raise TodoValidationError(code="invalid_input", message="field 'title' is required")

        normalized_progress = _normalize_progress_percent(progress_percent)
        created_at_value = _now()
        created_at = created_at_value.isoformat(timespec="seconds")

        deadline_value: datetime | None = None
        deadline_iso: str | None = None
        reminder_plan: list[dict[str, str]] = []
        occurrence_ids: list[str] = []

        if normalized_deadline is not None:
            deadline_value = _parse_todo_deadline(normalized_deadline)
            if deadline_value <= created_at_value:
                raise TodoValidationError(code="deadline_in_past", message="截止时间必须晚于当前时间")
            deadline_iso = deadline_value.isoformat(timespec="seconds")
            reminder_plan = _build_todo_reminder_plan(
                created_at=created_at_value,
                deadline=deadline_value,
            )

        todo_id = uuid4().hex
        todo_record = {
            "id": todo_id,
            "user_id": normalized_user_id,
            "title": normalized_title,
            "notes": normalized_notes,
            "deadline": deadline_iso,
            "progress_percent": normalized_progress,
            "difficulty": normalized_difficulty,
            "status": "open",
            "occurrence_ids": [],
            "reminder_plan": reminder_plan,
            "created_at": created_at,
            "updated_at": created_at,
        }

        if deadline_value is not None:
            for plan_item in reminder_plan:
                occurrence_id = uuid4().hex
                occurrence_ids.append(occurrence_id)
                self.occurrence_repository.create(
                    {
                        "id": occurrence_id,
                        "user_id": normalized_user_id,
                        "source_type": "todo",
                        "source_label": "待办事项提醒",
                        "source_id": todo_id,
                        "remind_at": plan_item["remind_at"],
                        "title": normalized_title,
                        "content": _build_todo_occurrence_content(
                            title=normalized_title,
                            stage_label=plan_item["label"],
                            deadline=deadline_value,
                            notes=normalized_notes,
                        ),
                        "payload_json": {
                            "title": normalized_title,
                            "notes": normalized_notes,
                            "deadline": deadline_iso,
                            "progress_percent": normalized_progress,
                            "difficulty": normalized_difficulty,
                            "stage": plan_item["stage"],
                            "stage_label": plan_item["label"],
                        },
                        "dedupe_key": f"todo:{todo_id}:{plan_item['stage']}:{plan_item['remind_at']}",
                        "status": "pending",
                        "created_at": created_at,
                        "updated_at": created_at,
                    }
                )
            todo_record["occurrence_ids"] = occurrence_ids

        self.todo_repository.create(todo_record)

        summary = f"已记录待办：{normalized_title}。"
        if deadline_value is not None:
            summary = (
                f"已记录待办：{normalized_title}，截止时间 {deadline_value.strftime('%Y-%m-%d %H:%M')}，"
                f"并生成 {len(occurrence_ids)} 条提醒。"
            )

        return {
            "todo_id": todo_id,
            "title": normalized_title,
            "notes": normalized_notes,
            "deadline": deadline_iso,
            "progress_percent": normalized_progress,
            "difficulty": normalized_difficulty,
            "status": "open",
            "occurrence_ids": occurrence_ids,
            "reminder_plan": reminder_plan,
            "summary": summary,
        }


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _normalize_progress_percent(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        normalized_value = int(value)
    except (TypeError, ValueError) as exc:
        raise TodoValidationError(
            code="invalid_progress_percent",
            message="progress_percent must be an integer between 0 and 100",
        ) from exc
    if normalized_value < 0 or normalized_value > 100:
        raise TodoValidationError(
            code="invalid_progress_percent",
            message="progress_percent must be an integer between 0 and 100",
        )
    return normalized_value


def _parse_todo_deadline(value: str) -> datetime:
    for fmt in _TODO_DEADLINE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    for fmt in _TODO_DATE_ONLY_FORMATS:
        try:
            parsed_date = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return parsed_date.replace(hour=23, minute=59, second=0)

    raise TodoValidationError(
        code="invalid_datetime",
        message="不支持的截止时间格式，请使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM",
    )


def _build_todo_reminder_plan(
    *,
    created_at: datetime,
    deadline: datetime,
) -> list[dict[str, str]]:
    total_seconds = (deadline - created_at).total_seconds()
    if total_seconds <= 0:
        return []

    candidates = [
        (
            "deadline_minus_1_day",
            "截止前1天提醒",
            deadline - timedelta(days=1),
        ),
        (
            "remaining_10_percent",
            "工期剩余10%提醒",
            created_at + timedelta(seconds=total_seconds * 0.9),
        ),
        (
            "remaining_25_percent",
            "工期剩余25%提醒",
            created_at + timedelta(seconds=total_seconds * 0.75),
        ),
        (
            "remaining_50_percent",
            "工期剩余50%提醒",
            created_at + timedelta(seconds=total_seconds * 0.5),
        ),
    ]

    unique_plan: dict[str, dict[str, str]] = {}
    for stage, label, remind_at_value in candidates:
        remind_at_value = remind_at_value.replace(microsecond=0)
        if remind_at_value <= created_at:
            continue
        remind_at_iso = remind_at_value.isoformat(timespec="seconds")
        unique_plan.setdefault(
            remind_at_iso,
            {
                "stage": stage,
                "label": label,
                "remind_at": remind_at_iso,
            },
        )

    return sorted(unique_plan.values(), key=lambda item: item["remind_at"])


def _build_todo_occurrence_content(
    *,
    title: str,
    stage_label: str,
    deadline: datetime,
    notes: str | None,
) -> str:
    content = (
        f"待办「{title}」{stage_label}，截止时间 {deadline.strftime('%Y-%m-%d %H:%M')}。"
    )
    if notes:
        content += f" 备注：{notes}"
    return content
