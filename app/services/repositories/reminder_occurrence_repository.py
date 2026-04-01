from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.repositories.json_store import JsonStore, get_runtime_data_dir


class ReminderOccurrenceRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self.store = store or JsonStore(self._default_path())

    def create(self, occurrence: dict[str, Any]) -> dict[str, Any]:
        def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            next_items = list(items)
            next_items.append(occurrence)
            return next_items, occurrence

        return self.store.update(default_factory=list, update_fn=update_fn)

    def list_due(self, *, as_of: datetime, limit: int = 100) -> list[dict[str, Any]]:
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

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        items = self.store.read(default_factory=list)
        if not isinstance(items, list):
            return []
        return [
            item
            for item in items
            if isinstance(item, dict) and str(item.get("user_id") or "") == user_id
        ]

    def update_delivery_result(
        self,
        *,
        occurrence_id: str,
        status: str,
        updated_at: str,
        delivery_id: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any] | None:
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

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "reminders" / "occurrences.json"
