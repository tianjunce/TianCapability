from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.services.repositories.json_store import JsonStore, get_runtime_data_dir
from app.services.repositories.mysql_backend import (
    CapabilityReminderOccurrenceRecord,
    dump_json,
    ensure_schema,
    get_session_factory,
    load_json,
    mysql_backend_enabled,
)


class ReminderOccurrenceRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._use_mysql = store is None and mysql_backend_enabled()
        self.store = None if self._use_mysql else (store or JsonStore(self._default_path()))
        if self._use_mysql:
            ensure_schema()

    def create(self, occurrence: dict[str, Any]) -> dict[str, Any]:
        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                next_items = list(items)
                next_items.append(occurrence)
                return next_items, occurrence

            return self.store.update(default_factory=list, update_fn=update_fn)

        row = CapabilityReminderOccurrenceRecord(
            id=str(occurrence.get("id") or ""),
            user_id=str(occurrence.get("user_id") or ""),
            source_type=str(occurrence.get("source_type") or ""),
            source_label=str(occurrence.get("source_label") or ""),
            source_id=str(occurrence.get("source_id") or ""),
            remind_at=str(occurrence.get("remind_at") or ""),
            title=str(occurrence.get("title") or ""),
            content=str(occurrence.get("content") or ""),
            payload_json=dump_json(occurrence.get("payload_json") or {}),
            dedupe_key=str(occurrence.get("dedupe_key") or ""),
            status=str(occurrence.get("status") or ""),
            created_at=occurrence.get("created_at"),
            updated_at=occurrence.get("updated_at"),
            delivered_at=occurrence.get("delivered_at"),
            last_error=occurrence.get("last_error"),
            last_delivery_id=occurrence.get("last_delivery_id"),
        )
        session_factory = get_session_factory()
        with session_factory() as db:
            db.add(row)
            db.commit()
            return self._row_to_dict(row)

    def list_due(self, *, as_of: datetime, limit: int = 100) -> list[dict[str, Any]]:
        if not self._use_mysql:
            assert self.store is not None
            items = self.store.read(default_factory=list)
            if not isinstance(items, list):
                return []

            due_items: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "") != "pending":
                    continue
                remind_at = str(item.get("remind_at") or "").strip()
                if not remind_at:
                    continue
                try:
                    remind_at_value = datetime.fromisoformat(remind_at)
                except ValueError:
                    continue
                if remind_at_value > as_of:
                    continue
                due_items.append(item)
                if len(due_items) >= limit:
                    break
            return due_items

        as_of_iso = as_of.replace(microsecond=0).isoformat(timespec="seconds")
        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(
                select(CapabilityReminderOccurrenceRecord)
                .where(
                    CapabilityReminderOccurrenceRecord.status == "pending",
                    CapabilityReminderOccurrenceRecord.remind_at <= as_of_iso,
                )
                .order_by(
                    CapabilityReminderOccurrenceRecord.remind_at.asc(),
                    CapabilityReminderOccurrenceRecord.created_at.asc(),
                    CapabilityReminderOccurrenceRecord.id.asc(),
                )
                .limit(limit)
            ).all()
            return [self._row_to_dict(row) for row in rows]

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
                select(CapabilityReminderOccurrenceRecord)
                .where(CapabilityReminderOccurrenceRecord.user_id == user_id)
                .order_by(CapabilityReminderOccurrenceRecord.created_at.asc(), CapabilityReminderOccurrenceRecord.id.asc())
            ).all()
            return [self._row_to_dict(row) for row in rows]

    def list_by_source(
        self,
        *,
        user_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._use_mysql:
            assert self.store is not None
            items = self.store.read(default_factory=list)
            if not isinstance(items, list):
                return []

            matched_items: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if user_id is not None and str(item.get("user_id") or "") != user_id:
                    continue
                if source_type is not None and str(item.get("source_type") or "") != source_type:
                    continue
                if source_id is not None and str(item.get("source_id") or "") != source_id:
                    continue
                matched_items.append(item)
            return matched_items

        stmt = select(CapabilityReminderOccurrenceRecord)
        if user_id is not None:
            stmt = stmt.where(CapabilityReminderOccurrenceRecord.user_id == user_id)
        if source_type is not None:
            stmt = stmt.where(CapabilityReminderOccurrenceRecord.source_type == source_type)
        if source_id is not None:
            stmt = stmt.where(CapabilityReminderOccurrenceRecord.source_id == source_id)
        stmt = stmt.order_by(CapabilityReminderOccurrenceRecord.created_at.asc(), CapabilityReminderOccurrenceRecord.id.asc())

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(stmt).all()
            return [self._row_to_dict(row) for row in rows]

    def update_delivery_result(
        self,
        *,
        occurrence_id: str,
        status: str,
        updated_at: str,
        delivery_id: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
                next_items: list[dict[str, Any]] = []
                updated_occurrence: dict[str, Any] | None = None

                for item in items:
                    if not isinstance(item, dict):
                        next_items.append(item)
                        continue

                    if str(item.get("id") or "") != occurrence_id:
                        next_items.append(item)
                        continue

                    updated_occurrence = dict(item)
                    updated_occurrence["status"] = status
                    updated_occurrence["updated_at"] = updated_at
                    if status == "delivered":
                        updated_occurrence["delivered_at"] = updated_at
                        updated_occurrence.pop("last_error", None)
                    elif error_message:
                        updated_occurrence["last_error"] = error_message
                    if delivery_id:
                        updated_occurrence["last_delivery_id"] = delivery_id
                    next_items.append(updated_occurrence)

                return next_items, updated_occurrence

            return self.store.update(default_factory=list, update_fn=update_fn)

        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.scalar(select(CapabilityReminderOccurrenceRecord).where(CapabilityReminderOccurrenceRecord.id == occurrence_id))
            if row is None:
                return None
            row.status = status
            row.updated_at = updated_at
            if status == "delivered":
                row.delivered_at = updated_at
                row.last_error = None
            elif error_message:
                row.last_error = error_message
            if delivery_id:
                row.last_delivery_id = delivery_id
            db.commit()
            return self._row_to_dict(row)

    def update_status_by_source(
        self,
        *,
        user_id: str,
        source_type: str,
        source_id: str,
        status: str,
        updated_at: str,
        from_statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_from_statuses = {
            str(item).strip()
            for item in (from_statuses or set())
            if str(item).strip()
        }

        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
                next_items: list[dict[str, Any]] = []
                updated_items: list[dict[str, Any]] = []

                for item in items:
                    if not isinstance(item, dict):
                        next_items.append(item)
                        continue
                    if str(item.get("user_id") or "") != user_id:
                        next_items.append(item)
                        continue
                    if str(item.get("source_type") or "") != source_type:
                        next_items.append(item)
                        continue
                    if str(item.get("source_id") or "") != source_id:
                        next_items.append(item)
                        continue
                    if normalized_from_statuses and str(item.get("status") or "") not in normalized_from_statuses:
                        next_items.append(item)
                        continue

                    updated_item = dict(item)
                    updated_item["status"] = status
                    updated_item["updated_at"] = updated_at
                    if status != "failed":
                        updated_item.pop("last_error", None)
                    next_items.append(updated_item)
                    updated_items.append(updated_item)

                return next_items, updated_items

            return self.store.update(default_factory=list, update_fn=update_fn)

        stmt = select(CapabilityReminderOccurrenceRecord).where(
            CapabilityReminderOccurrenceRecord.user_id == user_id,
            CapabilityReminderOccurrenceRecord.source_type == source_type,
            CapabilityReminderOccurrenceRecord.source_id == source_id,
        )
        if normalized_from_statuses:
            stmt = stmt.where(CapabilityReminderOccurrenceRecord.status.in_(sorted(normalized_from_statuses)))

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(stmt.order_by(CapabilityReminderOccurrenceRecord.created_at.asc(), CapabilityReminderOccurrenceRecord.id.asc())).all()
            updated_items: list[dict[str, Any]] = []
            for row in rows:
                row.status = status
                row.updated_at = updated_at
                if status != "failed":
                    row.last_error = None
                updated_items.append(self._row_to_dict(row))
            db.commit()
            return updated_items

    @staticmethod
    def _row_to_dict(row: CapabilityReminderOccurrenceRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "source_type": row.source_type,
            "source_label": row.source_label,
            "source_id": row.source_id,
            "remind_at": row.remind_at,
            "title": row.title,
            "content": row.content,
            "payload_json": load_json(row.payload_json, {}),
            "dedupe_key": row.dedupe_key,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "delivered_at": row.delivered_at,
            "last_error": row.last_error,
            "last_delivery_id": row.last_delivery_id,
        }

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "reminders" / "occurrences.json"
