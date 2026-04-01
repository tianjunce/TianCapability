from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.services.repositories.json_store import JsonStore, get_runtime_data_dir
from app.services.repositories.mysql_backend import (
    CapabilityReminderRecord,
    ensure_schema,
    get_session_factory,
    mysql_backend_enabled,
)


class ReminderRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._use_mysql = store is None and mysql_backend_enabled()
        self.store = None if self._use_mysql else (store or JsonStore(self._default_path()))
        if self._use_mysql:
            ensure_schema()

    def create(self, reminder: dict[str, Any]) -> dict[str, Any]:
        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                next_items = list(items)
                next_items.append(reminder)
                return next_items, reminder

            return self.store.update(default_factory=list, update_fn=update_fn)

        row = CapabilityReminderRecord(
            id=str(reminder.get("id") or ""),
            user_id=str(reminder.get("user_id") or ""),
            content=str(reminder.get("content") or ""),
            note=reminder.get("note"),
            remind_at=str(reminder.get("remind_at") or ""),
            status=str(reminder.get("status") or ""),
            created_at=reminder.get("created_at"),
            updated_at=reminder.get("updated_at"),
            cancelled_at=reminder.get("cancelled_at"),
            delivered_at=reminder.get("delivered_at"),
            last_error=reminder.get("last_error"),
        )
        session_factory = get_session_factory()
        with session_factory() as db:
            db.add(row)
            db.commit()
            return self._row_to_dict(row)

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        if not self._use_mysql:
            assert self.store is not None
            items = self.store.read(default_factory=list)
            if not isinstance(items, list):
                return []
            return [
                item
                for item in items
                if isinstance(item, dict) and str(item.get("user_id") or "") == user_id
            ]

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(
                select(CapabilityReminderRecord)
                .where(CapabilityReminderRecord.user_id == user_id)
                .order_by(CapabilityReminderRecord.remind_at.asc(), CapabilityReminderRecord.id.asc())
            ).all()
            return [self._row_to_dict(row) for row in rows]

    def get_by_id(self, *, user_id: str, reminder_id: str) -> dict[str, Any] | None:
        if not self._use_mysql:
            for item in self.list_by_user(user_id):
                if str(item.get("id") or "") == reminder_id:
                    return item
            return None

        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.scalar(
                select(CapabilityReminderRecord).where(
                    CapabilityReminderRecord.user_id == user_id,
                    CapabilityReminderRecord.id == reminder_id,
                )
            )
            return self._row_to_dict(row) if row is not None else None

    def find_by_content(
        self,
        *,
        user_id: str,
        content: str,
        remind_at: str | None = None,
        statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_content = str(content or "").strip()
        normalized_remind_at = str(remind_at or "").strip() or None
        normalized_statuses = {str(item).strip() for item in (statuses or set()) if str(item).strip()}

        if not self._use_mysql:
            matches: list[dict[str, Any]] = []
            for item in self.list_by_user(user_id):
                if str(item.get("content") or "").strip() != normalized_content:
                    continue
                if normalized_remind_at is not None and str(item.get("remind_at") or "").strip() != normalized_remind_at:
                    continue
                if normalized_statuses and str(item.get("status") or "").strip() not in normalized_statuses:
                    continue
                matches.append(item)
            return matches

        stmt = select(CapabilityReminderRecord).where(
            CapabilityReminderRecord.user_id == user_id,
            CapabilityReminderRecord.content == normalized_content,
        )
        if normalized_remind_at is not None:
            stmt = stmt.where(CapabilityReminderRecord.remind_at == normalized_remind_at)
        if normalized_statuses:
            stmt = stmt.where(CapabilityReminderRecord.status.in_(sorted(normalized_statuses)))
        stmt = stmt.order_by(CapabilityReminderRecord.remind_at.asc(), CapabilityReminderRecord.id.asc())

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(stmt).all()
            return [self._row_to_dict(row) for row in rows]

    def update_fields(
        self,
        *,
        user_id: str,
        reminder_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
                next_items: list[dict[str, Any]] = []
                updated_item: dict[str, Any] | None = None

                for item in items:
                    if not isinstance(item, dict):
                        next_items.append(item)
                        continue
                    if str(item.get("user_id") or "") != user_id or str(item.get("id") or "") != reminder_id:
                        next_items.append(item)
                        continue
                    updated_item = dict(item)
                    updated_item.update(fields)
                    next_items.append(updated_item)

                return next_items, updated_item

            return self.store.update(default_factory=list, update_fn=update_fn)

        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.scalar(
                select(CapabilityReminderRecord).where(
                    CapabilityReminderRecord.user_id == user_id,
                    CapabilityReminderRecord.id == reminder_id,
                )
            )
            if row is None:
                return None
            for key, value in fields.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            db.commit()
            return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row: CapabilityReminderRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "content": row.content,
            "note": row.note,
            "remind_at": row.remind_at,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "cancelled_at": row.cancelled_at,
            "delivered_at": row.delivered_at,
            "last_error": row.last_error,
        }

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "set_reminder" / "reminders.json"
