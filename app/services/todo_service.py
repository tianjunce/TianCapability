from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from app.services.repositories import ReminderOccurrenceRepository, TodoRepository
from app.services.time_utils import beijing_now


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


@dataclass(frozen=True)
class TodoTimeRange:
    label: str
    start: datetime
    end: datetime


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
            "action": "create",
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

    def list_todos(
        self,
        *,
        user_id: str,
        status: str | None = None,
        time_range: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_status = _normalize_todo_status_filter(status)
        normalized_time_range = (
            _normalize_todo_time_range(time_range, now=_now())
            if str(time_range or "").strip()
            else None
        )

        if not normalized_user_id:
            raise TodoValidationError(code="invalid_request", message="context.user_id is required")

        todos = self.todo_repository.list_by_user(normalized_user_id)
        if normalized_status is not None:
            todos = [item for item in todos if str(item.get("status") or "").strip() == normalized_status]
        else:
            todos = [item for item in todos if str(item.get("status") or "").strip() != "deleted"]
        if normalized_time_range is not None:
            todos = [item for item in todos if _todo_matches_time_range(item, normalized_time_range)]

        todos = sorted(todos, key=_todo_sort_key)
        open_total = sum(1 for item in todos if str(item.get("status") or "").strip() == "open")
        completed_total = sum(1 for item in todos if str(item.get("status") or "").strip() == "completed")

        return {
            "action": "list",
            "todos": todos,
            "total": len(todos),
            "open_total": open_total,
            "completed_total": completed_total,
            "summary": _build_todo_list_summary(
                total=len(todos),
                status=normalized_status,
                time_range=normalized_time_range.label if normalized_time_range is not None else None,
            ),
        }

    def update_todo(
        self,
        *,
        user_id: str,
        todo_id: str | None = None,
        title: str | None = None,
        notes: str | None = None,
        deadline: str | None = None,
        progress_percent: Any = None,
        difficulty: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_todo_id = str(todo_id or "").strip() or None
        normalized_title = str(title or "").strip() or None
        normalized_notes = str(notes or "").strip() or None
        normalized_deadline = str(deadline or "").strip() or None
        normalized_difficulty = str(difficulty or "").strip() or None
        has_progress_update = progress_percent not in (None, "")

        if not normalized_user_id:
            raise TodoValidationError(code="invalid_request", message="context.user_id is required")
        if normalized_todo_id is None and normalized_title is None:
            raise TodoValidationError(code="invalid_input", message="update requires todo_id or current title")
        if (
            normalized_title is None
            and normalized_notes is None
            and normalized_deadline is None
            and not has_progress_update
            and normalized_difficulty is None
        ):
            raise TodoValidationError(code="invalid_input", message="update requires at least one changed field")

        todo_record = _resolve_todo_for_update(
            repository=self.todo_repository,
            user_id=normalized_user_id,
            todo_id=normalized_todo_id,
            title=normalized_title,
        )
        if todo_record is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要修改的待办")
        if str(todo_record.get("status") or "").strip() != "open":
            raise TodoValidationError(code="todo_not_editable", message="只有 open 状态的待办可以修改")

        resolved_todo_id = str(todo_record.get("id") or "")
        next_title = normalized_title or str(todo_record.get("title") or "").strip()
        next_notes = normalized_notes if normalized_notes is not None else (todo_record.get("notes") or None)
        next_deadline_iso = todo_record.get("deadline")
        next_difficulty = (
            normalized_difficulty if normalized_difficulty is not None else (todo_record.get("difficulty") or None)
        )
        next_progress = (
            _normalize_progress_percent(progress_percent)
            if has_progress_update
            else todo_record.get("progress_percent")
        )

        if normalized_deadline is not None:
            deadline_value = _parse_todo_deadline(normalized_deadline)
            if deadline_value <= _now():
                raise TodoValidationError(code="deadline_in_past", message="截止时间必须晚于当前时间")
            next_deadline_iso = deadline_value.isoformat(timespec="seconds")

        updated_at_value = _now()
        updated_at = updated_at_value.isoformat(timespec="seconds")
        reminder_plan, occurrence_ids = self._rebuild_todo_occurrences(
            todo_id=resolved_todo_id,
            user_id=normalized_user_id,
            title=next_title,
            notes=next_notes,
            deadline_iso=next_deadline_iso,
            progress_percent=next_progress,
            difficulty=next_difficulty,
            created_at_iso=str(todo_record.get("created_at") or updated_at),
            updated_at=updated_at,
            now=updated_at_value,
        )

        updated_todo = self.todo_repository.update_fields(
            user_id=normalized_user_id,
            todo_id=resolved_todo_id,
            fields={
                "title": next_title,
                "notes": next_notes,
                "deadline": next_deadline_iso,
                "progress_percent": next_progress,
                "difficulty": next_difficulty,
                "occurrence_ids": occurrence_ids,
                "reminder_plan": reminder_plan,
                "updated_at": updated_at,
            },
        )
        if updated_todo is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要修改的待办")

        return {
            "action": "update",
            "todo_id": resolved_todo_id,
            "title": next_title,
            "notes": next_notes,
            "deadline": next_deadline_iso,
            "progress_percent": next_progress,
            "difficulty": next_difficulty,
            "status": "open",
            "occurrence_ids": occurrence_ids,
            "reminder_plan": reminder_plan,
            "summary": f"已更新待办：{next_title}。",
        }

    def complete_todo(
        self,
        *,
        user_id: str,
        todo_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_todo_id = str(todo_id or "").strip() or None
        normalized_title = str(title or "").strip() or None

        if not normalized_user_id:
            raise TodoValidationError(code="invalid_request", message="context.user_id is required")
        if normalized_todo_id is None and normalized_title is None:
            raise TodoValidationError(code="invalid_input", message="complete requires todo_id or title")

        todo_record = _resolve_todo_for_complete(
            repository=self.todo_repository,
            user_id=normalized_user_id,
            todo_id=normalized_todo_id,
            title=normalized_title,
        )
        todo_status = str(todo_record.get("status") or "").strip()
        if todo_status != "open":
            raise TodoValidationError(code="todo_not_open", message="该待办当前不是 open 状态，无法完成")

        completed_at = _now().isoformat(timespec="seconds")
        updated_todo = self.todo_repository.update_fields(
            user_id=normalized_user_id,
            todo_id=str(todo_record["id"]),
            fields={
                "status": "completed",
                "updated_at": completed_at,
                "completed_at": completed_at,
            },
        )
        if updated_todo is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要完成的待办")

        updated_occurrences = self.occurrence_repository.update_status_by_source(
            user_id=normalized_user_id,
            source_type="todo",
            source_id=str(todo_record["id"]),
            status="cancelled",
            updated_at=completed_at,
            from_statuses={"pending", "failed"},
        )

        return {
            "action": "complete",
            "todo_id": str(updated_todo["id"]),
            "title": str(updated_todo.get("title") or ""),
            "notes": updated_todo.get("notes"),
            "deadline": updated_todo.get("deadline"),
            "progress_percent": updated_todo.get("progress_percent"),
            "difficulty": updated_todo.get("difficulty"),
            "status": "completed",
            "completed_at": completed_at,
            "cancelled_occurrence_ids": [
                str(item.get("id") or "")
                for item in updated_occurrences
                if str(item.get("id") or "").strip()
            ],
            "summary": f"已完成待办：{str(updated_todo.get('title') or '')}。",
        }

    def delete_todo(
        self,
        *,
        user_id: str,
        todo_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_todo_id = str(todo_id or "").strip() or None
        normalized_title = str(title or "").strip() or None

        if not normalized_user_id:
            raise TodoValidationError(code="invalid_request", message="context.user_id is required")
        if normalized_todo_id is None and normalized_title is None:
            raise TodoValidationError(code="invalid_input", message="delete requires todo_id or title")

        todo_record = _resolve_todo_for_delete(
            repository=self.todo_repository,
            user_id=normalized_user_id,
            todo_id=normalized_todo_id,
            title=normalized_title,
        )
        if todo_record is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要删除的待办")
        if str(todo_record.get("status") or "").strip() == "deleted":
            raise TodoValidationError(code="todo_not_deletable", message="该待办已经删除")

        resolved_todo_id = str(todo_record.get("id") or "")

        deleted_at = _now().isoformat(timespec="seconds")
        updated_todo = self.todo_repository.update_fields(
            user_id=normalized_user_id,
            todo_id=resolved_todo_id,
            fields={
                "status": "deleted",
                "updated_at": deleted_at,
                "deleted_at": deleted_at,
            },
        )
        if updated_todo is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要删除的待办")

        cancelled_occurrences = self.occurrence_repository.update_status_by_source(
            user_id=normalized_user_id,
            source_type="todo",
            source_id=resolved_todo_id,
            status="cancelled",
            updated_at=deleted_at,
            from_statuses={"pending", "failed"},
        )

        return {
            "action": "delete",
            "todo_id": resolved_todo_id,
            "title": str(updated_todo.get("title") or ""),
            "status": "deleted",
            "cancelled_occurrence_ids": [
                str(item.get("id") or "")
                for item in cancelled_occurrences
                if str(item.get("id") or "").strip()
            ],
            "summary": f"已删除待办：{str(updated_todo.get('title') or '')}。",
        }

    def _rebuild_todo_occurrences(
        self,
        *,
        todo_id: str,
        user_id: str,
        title: str,
        notes: str | None,
        deadline_iso: str | None,
        progress_percent: Any,
        difficulty: str | None,
        created_at_iso: str,
        updated_at: str,
        now: datetime,
    ) -> tuple[list[dict[str, str]], list[str]]:
        self.occurrence_repository.update_status_by_source(
            user_id=user_id,
            source_type="todo",
            source_id=todo_id,
            status="cancelled",
            updated_at=updated_at,
            from_statuses={"pending", "failed"},
        )

        if deadline_iso is None:
            return [], []

        created_at_value = _parse_existing_iso_datetime(created_at_iso)
        deadline_value = datetime.fromisoformat(deadline_iso)
        full_plan = _build_todo_reminder_plan(created_at=created_at_value, deadline=deadline_value)
        reminder_plan = [item for item in full_plan if datetime.fromisoformat(item["remind_at"]) > now]

        occurrence_ids: list[str] = []
        for plan_item in reminder_plan:
            occurrence_id = uuid4().hex
            occurrence_ids.append(occurrence_id)
            self.occurrence_repository.create(
                {
                    "id": occurrence_id,
                    "user_id": user_id,
                    "source_type": "todo",
                    "source_label": "待办事项提醒",
                    "source_id": todo_id,
                    "remind_at": plan_item["remind_at"],
                    "title": title,
                    "content": _build_todo_occurrence_content(
                        title=title,
                        stage_label=plan_item["label"],
                        deadline=deadline_value,
                        notes=notes,
                    ),
                    "payload_json": {
                        "title": title,
                        "notes": notes,
                        "deadline": deadline_iso,
                        "progress_percent": progress_percent,
                        "difficulty": difficulty,
                        "stage": plan_item["stage"],
                        "stage_label": plan_item["label"],
                    },
                    "dedupe_key": f"todo:{todo_id}:{plan_item['stage']}:{plan_item['remind_at']}",
                    "status": "pending",
                    "created_at": updated_at,
                    "updated_at": updated_at,
                }
            )
        return reminder_plan, occurrence_ids


def _now() -> datetime:
    return beijing_now()


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


def _normalize_todo_status_filter(value: str | None) -> str | None:
    normalized_value = str(value or "").strip().lower() or None
    if normalized_value is None:
        return None
    if normalized_value in {"open", "pending", "active", "未完成", "待完成", "进行中"}:
        return "open"
    if normalized_value in {"completed", "已完成", "完成"}:
        return "completed"
    if normalized_value in {"deleted", "已删除", "删除"}:
        return "deleted"
    raise TodoValidationError(code="invalid_status", message="status must be open, completed, or deleted")


def _normalize_todo_time_range(value: str | None, *, now: datetime) -> TodoTimeRange | None:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        return None
    if normalized_value in {"全部", "所有", "全部待办", "所有待办"}:
        return None

    now_value = now.replace(microsecond=0)
    today_start = now_value.replace(hour=0, minute=0, second=0)

    if normalized_value in {"今天", "今日"}:
        return TodoTimeRange(
            label=normalized_value,
            start=today_start,
            end=today_start + timedelta(days=1) - timedelta(seconds=1),
        )
    if normalized_value == "明天":
        start = today_start + timedelta(days=1)
        return TodoTimeRange(
            label=normalized_value,
            start=start,
            end=start + timedelta(days=1) - timedelta(seconds=1),
        )
    if normalized_value == "后天":
        start = today_start + timedelta(days=2)
        return TodoTimeRange(
            label=normalized_value,
            start=start,
            end=start + timedelta(days=1) - timedelta(seconds=1),
        )
    if normalized_value in {"最近一个星期", "最近一周", "最近7天", "未来一个星期", "未来一周", "未来7天", "这一周"}:
        return TodoTimeRange(
            label=normalized_value,
            start=now_value,
            end=now_value + timedelta(days=7),
        )
    if normalized_value in {"最近三天", "最近3天", "未来三天", "未来3天"}:
        return TodoTimeRange(
            label=normalized_value,
            start=now_value,
            end=now_value + timedelta(days=3),
        )
    if normalized_value in {"最近一天", "最近1天", "最近24小时", "未来一天", "未来1天", "未来24小时"}:
        return TodoTimeRange(
            label=normalized_value,
            start=now_value,
            end=now_value + timedelta(days=1),
        )
    if normalized_value in {"这周", "本周", "这个星期"}:
        week_end = today_start + timedelta(days=(6 - today_start.weekday()), hours=23, minutes=59, seconds=59)
        return TodoTimeRange(
            label=normalized_value,
            start=now_value,
            end=week_end,
        )
    if normalized_value in {"下周", "下个星期", "下一个星期"}:
        next_week_start = today_start + timedelta(days=(7 - today_start.weekday()))
        return TodoTimeRange(
            label=normalized_value,
            start=next_week_start,
            end=next_week_start + timedelta(days=7) - timedelta(seconds=1),
        )

    if matched_days := re.fullmatch(r"(最近|未来)(\d+|[一二两三四五六七八九十])天", normalized_value):
        day_count = _parse_small_count(matched_days.group(2))
        if day_count is not None and day_count > 0:
            return TodoTimeRange(
                label=normalized_value,
                start=now_value,
                end=now_value + timedelta(days=day_count),
            )

    if matched_weeks := re.fullmatch(r"(最近|未来)(\d+|[一二两三四])个?(?:星期|周)", normalized_value):
        week_count = _parse_small_count(matched_weeks.group(2))
        if week_count is not None and week_count > 0:
            return TodoTimeRange(
                label=normalized_value,
                start=now_value,
                end=now_value + timedelta(days=7 * week_count),
            )

    return None


def _parse_small_count(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    return {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }.get(value)


def _todo_matches_time_range(item: dict[str, Any], time_range: TodoTimeRange) -> bool:
    deadline = str(item.get("deadline") or "").strip()
    if not deadline:
        return False
    try:
        deadline_value = datetime.fromisoformat(deadline)
    except ValueError:
        return False
    return time_range.start <= deadline_value <= time_range.end


def _resolve_todo_for_complete(
    *,
    repository: TodoRepository,
    user_id: str,
    todo_id: str | None,
    title: str | None,
) -> dict[str, Any]:
    if todo_id is not None:
        todo_record = repository.get_by_id(user_id=user_id, todo_id=todo_id)
        if todo_record is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要完成的待办")
        return todo_record

    matched_items = repository.find_by_title(
        user_id=user_id,
        title=title or "",
        statuses={"open"},
    )
    if not matched_items:
        raise TodoValidationError(code="todo_not_found", message="未找到要完成的待办")
    if len(matched_items) > 1:
        raise TodoValidationError(
            code="ambiguous_todo",
            message="找到了多条同名待办，请提供更具体的标题或 todo_id",
        )
    return matched_items[0]


def _resolve_todo_for_update(
    *,
    repository: TodoRepository,
    user_id: str,
    todo_id: str | None,
    title: str | None,
) -> dict[str, Any]:
    if todo_id is not None:
        todo_record = repository.get_by_id(user_id=user_id, todo_id=todo_id)
        if todo_record is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要修改的待办")
        return todo_record

    matched_items = repository.find_by_title(
        user_id=user_id,
        title=title or "",
        statuses={"open"},
    )
    if not matched_items:
        raise TodoValidationError(code="todo_not_found", message="未找到要修改的待办")
    if len(matched_items) > 1:
        raise TodoValidationError(
            code="ambiguous_todo",
            message="找到了多条同名待办，请提供 todo_id",
        )
    return matched_items[0]


def _resolve_todo_for_delete(
    *,
    repository: TodoRepository,
    user_id: str,
    todo_id: str | None,
    title: str | None,
) -> dict[str, Any]:
    if todo_id is not None:
        todo_record = repository.get_by_id(user_id=user_id, todo_id=todo_id)
        if todo_record is None:
            raise TodoValidationError(code="todo_not_found", message="未找到要删除的待办")
        return todo_record

    matched_items = repository.find_by_title(
        user_id=user_id,
        title=title or "",
        statuses={"open", "completed"},
    )
    if not matched_items:
        deleted_items = repository.find_by_title(
            user_id=user_id,
            title=title or "",
            statuses={"deleted"},
        )
        if len(deleted_items) == 1:
            return deleted_items[0]
        raise TodoValidationError(code="todo_not_found", message="未找到要删除的待办")
    if len(matched_items) > 1:
        raise TodoValidationError(
            code="ambiguous_todo",
            message="找到了多条同名待办，请提供更具体的标题或 todo_id",
        )
    return matched_items[0]


def _todo_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    status = str(item.get("status") or "").strip()
    deadline = str(item.get("deadline") or "")
    created_at = str(item.get("created_at") or "")
    status_order = {"open": 0, "completed": 1, "deleted": 2}
    return (status_order.get(status, 9), deadline or "9999-12-31T23:59:59", created_at)


def _build_todo_list_summary(*, total: int, status: str | None, time_range: str | None) -> str:
    scope = _build_todo_list_scope(status=status, time_range=time_range)
    if total == 0:
        if not scope:
            return "当前没有待办记录。"
        return f"当前没有{scope}待办记录。"
    if not scope:
        return f"共找到 {total} 条待办记录。"
    return f"共找到 {total} 条{scope}待办记录。"


def _build_todo_list_scope(*, status: str | None, time_range: str | None) -> str:
    parts: list[str] = []
    if time_range is not None:
        parts.append(f"{time_range}内的")
    if status is not None:
        parts.append(f"状态为 {status} 的")
    return "".join(parts)


def _parse_existing_iso_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise TodoValidationError(code="internal_error", message="stored todo datetime is invalid") from exc
