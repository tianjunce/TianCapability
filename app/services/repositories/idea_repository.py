from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.services.repositories.json_store import JsonStore, get_runtime_data_dir
from app.services.repositories.mysql_backend import (
    CapabilityIdeaRecord,
    dump_json,
    ensure_schema,
    get_session_factory,
    load_json,
    mysql_backend_enabled,
)


class IdeaRepository:
    def __init__(self, store: JsonStore | None = None) -> None:
        self._use_mysql = store is None and mysql_backend_enabled()
        self.store = None if self._use_mysql else (store or JsonStore(self._default_path()))
        if self._use_mysql:
            ensure_schema()

    def create(self, idea: dict[str, Any]) -> dict[str, Any]:
        if not self._use_mysql:
            assert self.store is not None

            def update_fn(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                next_items = list(items)
                next_items.append(idea)
                return next_items, idea

            return self.store.update(default_factory=list, update_fn=update_fn)

        row = CapabilityIdeaRecord(
            id=str(idea.get("id") or ""),
            user_id=str(idea.get("user_id") or ""),
            title=idea.get("title"),
            content=str(idea.get("content") or ""),
            tags_json=dump_json(idea.get("tags") or []),
            status=str(idea.get("status") or ""),
            created_at=idea.get("created_at"),
            updated_at=idea.get("updated_at"),
            deleted_at=idea.get("deleted_at"),
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
                select(CapabilityIdeaRecord)
                .where(CapabilityIdeaRecord.user_id == user_id)
                .order_by(CapabilityIdeaRecord.created_at.asc(), CapabilityIdeaRecord.id.asc())
            ).all()
            return [self._row_to_dict(row) for row in rows]

    def get_by_id(self, *, user_id: str, idea_id: str) -> dict[str, Any] | None:
        if not self._use_mysql:
            for item in self.list_by_user(user_id):
                if str(item.get("id") or "") == idea_id:
                    return item
            return None

        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.scalar(
                select(CapabilityIdeaRecord).where(
                    CapabilityIdeaRecord.user_id == user_id,
                    CapabilityIdeaRecord.id == idea_id,
                )
            )
            return self._row_to_dict(row) if row is not None else None

    def find_by_title(
        self,
        *,
        user_id: str,
        title: str,
        statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_title = str(title or "").strip()
        normalized_statuses = {str(item).strip() for item in (statuses or set()) if str(item).strip()}

        if not self._use_mysql:
            matches: list[dict[str, Any]] = []
            for item in self.list_by_user(user_id):
                if str(item.get("title") or "").strip() != normalized_title:
                    continue
                if normalized_statuses and str(item.get("status") or "").strip() not in normalized_statuses:
                    continue
                matches.append(item)
            return matches

        stmt = select(CapabilityIdeaRecord).where(
            CapabilityIdeaRecord.user_id == user_id,
            CapabilityIdeaRecord.title == normalized_title,
        )
        if normalized_statuses:
            stmt = stmt.where(CapabilityIdeaRecord.status.in_(sorted(normalized_statuses)))
        stmt = stmt.order_by(CapabilityIdeaRecord.created_at.asc(), CapabilityIdeaRecord.id.asc())

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(stmt).all()
            return [self._row_to_dict(row) for row in rows]

    def find_by_content(
        self,
        *,
        user_id: str,
        content: str,
        statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_content = str(content or "").strip()
        normalized_statuses = {str(item).strip() for item in (statuses or set()) if str(item).strip()}

        if not self._use_mysql:
            matches: list[dict[str, Any]] = []
            for item in self.list_by_user(user_id):
                if str(item.get("content") or "").strip() != normalized_content:
                    continue
                if normalized_statuses and str(item.get("status") or "").strip() not in normalized_statuses:
                    continue
                matches.append(item)
            return matches

        stmt = select(CapabilityIdeaRecord).where(
            CapabilityIdeaRecord.user_id == user_id,
            CapabilityIdeaRecord.content == normalized_content,
        )
        if normalized_statuses:
            stmt = stmt.where(CapabilityIdeaRecord.status.in_(sorted(normalized_statuses)))
        stmt = stmt.order_by(CapabilityIdeaRecord.created_at.asc(), CapabilityIdeaRecord.id.asc())

        session_factory = get_session_factory()
        with session_factory() as db:
            rows = db.scalars(stmt).all()
            return [self._row_to_dict(row) for row in rows]

    def update_fields(
        self,
        *,
        user_id: str,
        idea_id: str,
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
                    if str(item.get("user_id") or "") != user_id or str(item.get("id") or "") != idea_id:
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
                select(CapabilityIdeaRecord).where(
                    CapabilityIdeaRecord.user_id == user_id,
                    CapabilityIdeaRecord.id == idea_id,
                )
            )
            if row is None:
                return None
            for key, value in fields.items():
                if key == "tags":
                    row.tags_json = dump_json(value or [])
                    continue
                if hasattr(row, key):
                    setattr(row, key, value)
            db.commit()
            return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row: CapabilityIdeaRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "user_id": row.user_id,
            "title": row.title,
            "content": row.content,
            "tags": load_json(row.tags_json, []),
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }

    @staticmethod
    def _default_path() -> Path:
        return get_runtime_data_dir() / "capture_idea" / "ideas.json"
