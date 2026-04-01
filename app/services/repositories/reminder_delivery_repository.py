from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.services.repositories.json_store import JsonStore, get_runtime_data_dir
from app.services.repositories.mysql_backend import (
    CapabilityReminderDeliveryRecord,
    dump_json,
    ensure_schema,
    get_session_factory,
    load_json,
    mysql_backend_enabled,
)


class ReminderDeliveryRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._use_mysql = store is None and mysql_backend_enabled()
        self.store = None if self._use_mysql else (store or JsonStore(self._default_path()))
        if self._use_mysql:
            ensure_schema()

    def create(self, delivery: dict[str, Any]) -> dict[str, Any]:
        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                next_items = list(items)
                next_items.append(delivery)
                return next_items, delivery

            return self.store.update(default_factory=list, update_fn=update_fn)

        row = CapabilityReminderDeliveryRecord(
            id=str(delivery.get("id") or ""),
            occurrence_id=str(delivery.get("occurrence_id") or ""),
            user_id=str(delivery.get("user_id") or ""),
            channel=str(delivery.get("channel") or ""),
            status=str(delivery.get("status") or ""),
            error_code=delivery.get("error_code"),
            error_message=delivery.get("error_message"),
            request_payload_json=None
            if delivery.get("request_payload") is None
            else dump_json(delivery.get("request_payload")),
            response_payload_json=None
            if delivery.get("response_payload") is None
            else dump_json(delivery.get("response_payload")),
            created_at=delivery.get("created_at"),
        )
        session_factory = get_session_factory()
        with session_factory() as db:
            db.add(row)
            db.commit()
            return self._row_to_dict(row)

    def list_by_occurrence(self, occurrence_id: str) -> list[dict[str, Any]]:
        if not self._use_mysql:
            assert self.store is not None
            items = self.store.read(default_factory=list)
            if not isinstance(items, list):
                return []
            return [
                item
                for item in items
                if isinstance(item, dict) and str(item.get("occurrence_id") or "") == occurrence_id
            ]

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(
                select(CapabilityReminderDeliveryRecord)
                .where(CapabilityReminderDeliveryRecord.occurrence_id == occurrence_id)
                .order_by(CapabilityReminderDeliveryRecord.created_at.asc(), CapabilityReminderDeliveryRecord.id.asc())
            ).all()
            return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: CapabilityReminderDeliveryRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "occurrence_id": row.occurrence_id,
            "user_id": row.user_id,
            "channel": row.channel,
            "status": row.status,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "request_payload": load_json(row.request_payload_json, None),
            "response_payload": load_json(row.response_payload_json, None),
            "created_at": row.created_at,
        }

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "reminders" / "deliveries.json"
