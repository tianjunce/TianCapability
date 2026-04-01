from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.repositories.json_store import get_runtime_data_dir
from app.services.repositories.mysql_backend import (
    CapabilityBirthdayRecord,
    CapabilityIdeaRecord,
    CapabilityReminderDeliveryRecord,
    CapabilityReminderOccurrenceRecord,
    CapabilityReminderRecord,
    CapabilityTodoRecord,
    dump_json,
    ensure_schema,
    get_session_factory,
    mysql_backend_enabled,
)


def _read_records(path: Path) -> list[dict[str, Any]]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _upsert(db, model_cls: type[Any], record_id: str, fields: dict[str, Any]) -> None:
    row = db.get(model_cls, record_id)
    if row is None:
        row = model_cls(id=record_id, **fields)
        db.add(row)
        return
    for key, value in fields.items():
        setattr(row, key, value)


def _todo_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(record.get("user_id") or ""),
        "title": str(record.get("title") or ""),
        "notes": record.get("notes"),
        "deadline": record.get("deadline"),
        "progress_percent": record.get("progress_percent"),
        "difficulty": record.get("difficulty"),
        "status": str(record.get("status") or ""),
        "occurrence_ids_json": dump_json(record.get("occurrence_ids") or []),
        "reminder_plan_json": dump_json(record.get("reminder_plan") or []),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "completed_at": record.get("completed_at"),
        "deleted_at": record.get("deleted_at"),
    }


def _reminder_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(record.get("user_id") or ""),
        "content": str(record.get("content") or ""),
        "note": record.get("note"),
        "remind_at": str(record.get("remind_at") or ""),
        "status": str(record.get("status") or ""),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "cancelled_at": record.get("cancelled_at"),
        "delivered_at": record.get("delivered_at"),
        "last_error": record.get("last_error"),
    }


def _occurrence_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(record.get("user_id") or ""),
        "source_type": str(record.get("source_type") or ""),
        "source_label": str(record.get("source_label") or ""),
        "source_id": str(record.get("source_id") or ""),
        "remind_at": str(record.get("remind_at") or ""),
        "title": str(record.get("title") or ""),
        "content": str(record.get("content") or ""),
        "payload_json": dump_json(record.get("payload_json") or {}),
        "dedupe_key": str(record.get("dedupe_key") or ""),
        "status": str(record.get("status") or ""),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "delivered_at": record.get("delivered_at"),
        "last_error": record.get("last_error"),
        "last_delivery_id": record.get("last_delivery_id"),
    }


def _delivery_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "occurrence_id": str(record.get("occurrence_id") or ""),
        "user_id": str(record.get("user_id") or ""),
        "channel": str(record.get("channel") or ""),
        "status": str(record.get("status") or ""),
        "error_code": record.get("error_code"),
        "error_message": record.get("error_message"),
        "request_payload_json": None
        if record.get("request_payload") is None
        else dump_json(record.get("request_payload")),
        "response_payload_json": None
        if record.get("response_payload") is None
        else dump_json(record.get("response_payload")),
        "created_at": record.get("created_at"),
    }


def _idea_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(record.get("user_id") or ""),
        "title": record.get("title"),
        "content": str(record.get("content") or ""),
        "tags_json": dump_json(record.get("tags") or []),
        "status": str(record.get("status") or ""),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "deleted_at": record.get("deleted_at"),
    }


def _birthday_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(record.get("user_id") or ""),
        "name": str(record.get("name") or ""),
        "birthday": str(record.get("birthday") or ""),
        "calendar_type": str(record.get("calendar_type") or ""),
        "birth_year": record.get("birth_year"),
        "is_leap_month": bool(record.get("is_leap_month") or False),
        "notes": record.get("notes"),
        "status": str(record.get("status") or ""),
        "next_birthday": str(record.get("next_birthday") or ""),
        "occurrence_ids_json": dump_json(record.get("occurrence_ids") or []),
        "reminder_plan_json": dump_json(record.get("reminder_plan") or []),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "deleted_at": record.get("deleted_at"),
    }


def main() -> None:
    if not mysql_backend_enabled():
        raise SystemExit("MySQL backend is not configured. Set DB_LOGIN_USER / DB_LOGIN_PASSWORD / DB_HOST first.")

    ensure_schema()
    runtime_data_dir = get_runtime_data_dir()
    session_factory = get_session_factory()

    todo_records = _read_records(runtime_data_dir / "manage_todo" / "todos.json")
    reminder_records = _read_records(runtime_data_dir / "set_reminder" / "reminders.json")
    occurrence_records = _read_records(runtime_data_dir / "reminders" / "occurrences.json")
    delivery_records = _read_records(runtime_data_dir / "reminders" / "deliveries.json")
    idea_records = _read_records(runtime_data_dir / "capture_idea" / "ideas.json")
    birthday_records = _read_records(runtime_data_dir / "manage_birthday" / "birthdays.json")

    with session_factory() as db:
        for record in todo_records:
            record_id = str(record.get("id") or "").strip()
            if record_id:
                _upsert(db, CapabilityTodoRecord, record_id, _todo_fields(record))

        for record in reminder_records:
            record_id = str(record.get("id") or "").strip()
            if record_id:
                _upsert(db, CapabilityReminderRecord, record_id, _reminder_fields(record))

        for record in occurrence_records:
            record_id = str(record.get("id") or "").strip()
            if record_id:
                _upsert(db, CapabilityReminderOccurrenceRecord, record_id, _occurrence_fields(record))

        for record in delivery_records:
            record_id = str(record.get("id") or "").strip()
            if record_id:
                _upsert(db, CapabilityReminderDeliveryRecord, record_id, _delivery_fields(record))

        for record in idea_records:
            record_id = str(record.get("id") or "").strip()
            if record_id:
                _upsert(db, CapabilityIdeaRecord, record_id, _idea_fields(record))

        for record in birthday_records:
            record_id = str(record.get("id") or "").strip()
            if record_id:
                _upsert(db, CapabilityBirthdayRecord, record_id, _birthday_fields(record))

        db.commit()

    print(
        json.dumps(
            {
                "todo_records": len(todo_records),
                "reminder_records": len(reminder_records),
                "occurrence_records": len(occurrence_records),
                "delivery_records": len(delivery_records),
                "idea_records": len(idea_records),
                "birthday_records": len(birthday_records),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
