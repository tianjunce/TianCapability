from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.repositories.json_store import JsonStore, get_runtime_data_dir


class BirthdayRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self.store = store or JsonStore(self._default_path())

    def create(self, birthday: dict[str, Any]) -> dict[str, Any]:
        def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            next_items = list(items)
            next_items.append(birthday)
            return next_items, birthday

        return self.store.update(default_factory=list, update_fn=update_fn)

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        items = self.store.read(default_factory=list)
        if not isinstance(items, list):
            return []
        return [
            item
            for item in items
            if isinstance(item, dict) and str(item.get("user_id") or "") == user_id
        ]

    def get_by_id(self, *, user_id: str, birthday_id: str) -> dict[str, Any] | None:
        for item in self.list_by_user(user_id):
            if str(item.get("id") or "") == birthday_id:
                return item
        return None

    def find_by_name(
        self,
        *,
        user_id: str,
        name: str,
        statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_name = str(name or "").strip()
        normalized_statuses = {str(item).strip() for item in (statuses or set()) if str(item).strip()}

        matches: list[dict[str, Any]] = []
        for item in self.list_by_user(user_id):
            if str(item.get("name") or "").strip() != normalized_name:
                continue
            if normalized_statuses and str(item.get("status") or "").strip() not in normalized_statuses:
                continue
            matches.append(item)
        return matches

    def update_fields(
        self,
        *,
        user_id: str,
        birthday_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any] | None:
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

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "manage_birthday" / "birthdays.json"
