from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.services.repositories.json_store import JsonStore, get_runtime_data_dir
from app.services.repositories.mysql_backend import (
    CapabilityBirthdayRecord,
    dump_json,
    ensure_schema,
    get_session_factory,
    load_json,
    mysql_backend_enabled,
)


class BirthdayRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._use_mysql = store is None and mysql_backend_enabled()
        self.store = None if self._use_mysql else (store or JsonStore(self._default_path()))
        if self._use_mysql:
            ensure_schema()

    def create(self, birthday: dict[str, Any]) -> dict[str, Any]:
        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                next_items = list(items)
                next_items.append(birthday)
                return next_items, birthday

            return self.store.update(default_factory=list, update_fn=update_fn)

        row = CapabilityBirthdayRecord(
            id=str(birthday.get("id") or ""),
            user_id=str(birthday.get("user_id") or ""),
            name=str(birthday.get("name") or ""),
            birthday=str(birthday.get("birthday") or ""),
            calendar_type=str(birthday.get("calendar_type") or ""),
            birth_year=birthday.get("birth_year"),
            is_leap_month=bool(birthday.get("is_leap_month") or False),
            notes=birthday.get("notes"),
            status=str(birthday.get("status") or ""),
            next_birthday=str(birthday.get("next_birthday") or ""),
            occurrence_ids_json=dump_json(birthday.get("occurrence_ids") or []),
            reminder_plan_json=dump_json(birthday.get("reminder_plan") or []),
            created_at=birthday.get("created_at"),
            updated_at=birthday.get("updated_at"),
            deleted_at=birthday.get("deleted_at"),
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
                select(CapabilityBirthdayRecord)
                .where(CapabilityBirthdayRecord.user_id == user_id)
                .order_by(CapabilityBirthdayRecord.created_at.asc(), CapabilityBirthdayRecord.id.asc())
            ).all()
            return [self._row_to_dict(row) for row in rows]

    def get_by_id(self, *, user_id: str, birthday_id: str) -> dict[str, Any] | None:
        if not self._use_mysql:
            for item in self.list_by_user(user_id):
                if str(item.get("id") or "") == birthday_id:
                    return item
            return None

        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.scalar(
                select(CapabilityBirthdayRecord).where(
                    CapabilityBirthdayRecord.user_id == user_id,
                    CapabilityBirthdayRecord.id == birthday_id,
                )
            )
            return self._row_to_dict(row) if row is not None else None

    def find_by_name(
        self,
        *,
        user_id: str,
        name: str,
        statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_name = str(name or "").strip()
        normalized_statuses = {str(item).strip() for item in (statuses or set()) if str(item).strip()}

        if not self._use_mysql:
            matches: list[dict[str, Any]] = []
            for item in self.list_by_user(user_id):
                if str(item.get("name") or "").strip() != normalized_name:
                    continue
                if normalized_statuses and str(item.get("status") or "").strip() not in normalized_statuses:
                    continue
                matches.append(item)
            return matches

        stmt = select(CapabilityBirthdayRecord).where(
            CapabilityBirthdayRecord.user_id == user_id,
            CapabilityBirthdayRecord.name == normalized_name,
        )
        if normalized_statuses:
            stmt = stmt.where(CapabilityBirthdayRecord.status.in_(sorted(normalized_statuses)))
        stmt = stmt.order_by(CapabilityBirthdayRecord.created_at.asc(), CapabilityBirthdayRecord.id.asc())

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(stmt).all()
            return [self._row_to_dict(row) for row in rows]

    def update_fields(
        self,
        *,
        user_id: str,
        birthday_id: str,
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
                    if str(item.get("user_id") or "") != user_id or str(item.get("id") or "") != birthday_id:
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
                select(CapabilityBirthdayRecord).where(
                    CapabilityBirthdayRecord.user_id == user_id,
                    CapabilityBirthdayRecord.id == birthday_id,
                )
            )
            if row is None:
                return None
            for key, value in fields.items():
                if key == "occurrence_ids":
                    row.occurrence_ids_json = dump_json(value or [])
                    continue
                if key == "reminder_plan":
                    row.reminder_plan_json = dump_json(value or [])
                    continue
                if hasattr(row, key):
                    setattr(row, key, value)
            db.commit()
            return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row: CapabilityBirthdayRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "name": row.name,
            "birthday": row.birthday,
            "calendar_type": row.calendar_type,
            "birth_year": row.birth_year,
            "is_leap_month": row.is_leap_month,
            "notes": row.notes,
            "status": row.status,
            "next_birthday": row.next_birthday,
            "occurrence_ids": load_json(row.occurrence_ids_json, []),
            "reminder_plan": load_json(row.reminder_plan_json, []),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "manage_birthday" / "birthdays.json"
