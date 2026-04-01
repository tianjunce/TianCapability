from __future__ import annotations

import json
import os
import threading
from typing import Any
from urllib.parse import unquote

from sqlalchemy import Boolean, Index, Integer, String, Text, create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.services.env_config import get_config_value


_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker | None = None
_SCHEMA_READY = False
_SCHEMA_GUARD = threading.Lock()


def mysql_configured() -> bool:
    return bool(get_config_value("DB_LOGIN_USER").strip() and get_config_value("DB_HOST").strip())


def get_storage_backend() -> str:
    explicit = get_config_value("CAPABILITY_STORAGE_BACKEND", "").strip().lower()
    if explicit in {"json", "file"}:
        return "json"
    if explicit in {"mysql", "db"}:
        return "mysql"
    if str(os.getenv("CAPABILITY_DATA_DIR") or "").strip():
        return "json"
    return "mysql" if mysql_configured() else "json"


def mysql_backend_enabled() -> bool:
    return get_storage_backend() == "mysql" and mysql_configured()


def _parse_mysql_host_spec(host_spec: str | None) -> tuple[str | None, int | None, str | None]:
    raw = str(host_spec or "").strip()
    if not raw:
        return None, None, None

    database: str | None = None
    host_port = raw
    if "/" in raw:
        host_port, database = raw.split("/", 1)
        database = database.strip() or None

    host_port = host_port.strip()
    if not host_port:
        return None, None, database

    if ":" not in host_port:
        return host_port, None, database

    host, port_text = host_port.rsplit(":", 1)
    host = host.strip() or None
    try:
        port = int(port_text.strip())
    except (TypeError, ValueError):
        port = None
    return host, port, database


def _build_mysql_url() -> URL:
    host, port, database = _parse_mysql_host_spec(get_config_value("DB_HOST"))
    return URL.create(
        "mysql+mysqlconnector",
        username=get_config_value("DB_LOGIN_USER") or None,
        password=unquote(get_config_value("DB_LOGIN_PASSWORD")) or None,
        host=host,
        port=port,
        database=database,
        query={"charset": "utf8mb4"},
    )


def _db_sql_echo() -> bool:
    return get_config_value("DB_SQL_ECHO", "").strip().lower() in {"1", "true", "yes", "on"}


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(
            _build_mysql_url(),
            echo=_db_sql_echo(),
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _ENGINE


def get_session_factory() -> sessionmaker:
    global _SESSION_FACTORY
    if _SESSION_FACTORY is None:
        _SESSION_FACTORY = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return _SESSION_FACTORY


class Base(DeclarativeBase):
    pass


def _mysql_table_args(*indexes: Index) -> tuple[object, ...]:
    return (
        *indexes,
        {
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_unicode_ci",
        },
    )


class CapabilityTodoRecord(Base):
    __tablename__ = "capability_todo_records"
    __table_args__ = _mysql_table_args(
        Index("ix_capability_todo_records_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    occurrence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reminder_plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deleted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class CapabilityReminderRecord(Base):
    __tablename__ = "capability_reminder_records"
    __table_args__ = _mysql_table_args(
        Index("ix_capability_reminder_records_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    remind_at: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivered_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CapabilityReminderOccurrenceRecord(Base):
    __tablename__ = "capability_reminder_occurrence_records"
    __table_args__ = _mysql_table_args(
        Index("ix_capability_reminder_occurrences_status_remind_at", "status", "remind_at"),
        Index("ix_capability_reminder_occurrences_source", "user_id", "source_type", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_label: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    remind_at: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivered_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_delivery_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CapabilityReminderDeliveryRecord(Base):
    __tablename__ = "capability_reminder_delivery_records"
    __table_args__ = _mysql_table_args(
        Index("ix_capability_reminder_deliveries_occurrence", "occurrence_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    occurrence_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class CapabilityIdeaRecord(Base):
    __tablename__ = "capability_idea_records"
    __table_args__ = _mysql_table_args(
        Index("ix_capability_idea_records_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deleted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class CapabilityBirthdayRecord(Base):
    __tablename__ = "capability_birthday_records"
    __table_args__ = _mysql_table_args(
        Index("ix_capability_birthday_records_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    birthday: Mapped[str] = mapped_column(String(16), nullable=False)
    calendar_type: Mapped[str] = mapped_column(String(16), nullable=False)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_leap_month: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    next_birthday: Mapped[str] = mapped_column(String(16), nullable=False)
    occurrence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reminder_plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deleted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY or not mysql_backend_enabled():
        return
    with _SCHEMA_GUARD:
        if _SCHEMA_READY:
            return
        Base.metadata.create_all(bind=get_engine())
        _SCHEMA_READY = True


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_json(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
