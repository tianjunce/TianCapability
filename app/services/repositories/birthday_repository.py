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

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "manage_birthday" / "birthdays.json"
