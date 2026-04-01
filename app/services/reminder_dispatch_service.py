from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import requests

from app.services.env_config import get_config_value
from app.services.repositories import (
    ReminderDeliveryRepository,
    ReminderOccurrenceRepository,
    ReminderRepository,
)


class ReminderDispatchError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ReminderNotificationClient:
    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_token: str | None = None,
        timeout_seconds: int = 10,
        session: requests.Session | None = None,
    ) -> None:
        self.api_url = (api_url or get_config_value("REMINDER_NOTIFICATION_API_URL")).strip()
        self.api_token = (api_token or get_config_value("REMINDER_NOTIFICATION_API_TOKEN")).strip()
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def send_occurrence(self, occurrence: dict[str, Any]) -> dict[str, Any]:
        if not self.api_url:
            raise ReminderDispatchError(
                code="notification_api_not_configured",
                message="REMINDER_NOTIFICATION_API_URL is not configured",
            )

        reminder_source = _build_reminder_source(occurrence)
        payload = {
            "source": "reminder_worker",
            "user_id": occurrence["user_id"],
            "title": occurrence["title"],
            "content": occurrence["content"],
            "reminder_source": reminder_source,
            "metadata": {
                "occurrence_id": occurrence["id"],
                "source_type": occurrence["source_type"],
                "source_label": reminder_source["label"],
                "source_id": occurrence["source_id"],
                "remind_at": occurrence["remind_at"],
                "dedupe_key": occurrence["dedupe_key"],
                "payload": occurrence.get("payload_json") or {},
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        try:
            response = self.session.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ReminderDispatchError(code="notification_send_failed", message=str(exc)) from exc

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"raw_text": response.text}

        return {
            "request_payload": payload,
            "response_payload": response_payload,
        }


class ReminderDispatchService:
    def __init__(
        self,
        *,
        occurrence_repository: ReminderOccurrenceRepository | None = None,
        delivery_repository: ReminderDeliveryRepository | None = None,
        reminder_repository: ReminderRepository | None = None,
        notification_client: ReminderNotificationClient | None = None,
    ) -> None:
        self.occurrence_repository = occurrence_repository or ReminderOccurrenceRepository()
        self.delivery_repository = delivery_repository or ReminderDeliveryRepository()
        self.reminder_repository = reminder_repository or ReminderRepository()
        self.notification_client = notification_client or ReminderNotificationClient()

    def dispatch_due_occurrences(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        scan_started_at = (now or datetime.now()).replace(microsecond=0)
        due_occurrences = self.occurrence_repository.list_due(as_of=scan_started_at, limit=limit)

        processed = 0
        delivered = 0
        failed = 0
        delivery_ids: list[str] = []

        for occurrence in due_occurrences:
            processed += 1
            dispatched_at = datetime.now().replace(microsecond=0).isoformat()
            delivery_id = uuid4().hex

            try:
                notification_result = self.notification_client.send_occurrence(occurrence)
            except ReminderDispatchError as exc:
                self.delivery_repository.create(
                    {
                        "id": delivery_id,
                        "occurrence_id": occurrence["id"],
                        "user_id": occurrence["user_id"],
                        "channel": "assistant_api",
                        "status": "failed",
                        "error_code": exc.code,
                        "error_message": exc.message,
                        "request_payload": None,
                        "response_payload": None,
                        "created_at": dispatched_at,
                    }
                )
                self.occurrence_repository.update_delivery_result(
                    occurrence_id=occurrence["id"],
                    status="failed",
                    updated_at=dispatched_at,
                    delivery_id=delivery_id,
                    error_message=exc.message,
                )
                self._sync_source_record_status(
                    occurrence=occurrence,
                    status="failed",
                    updated_at=dispatched_at,
                    error_message=exc.message,
                )
                failed += 1
                delivery_ids.append(delivery_id)
                continue

            self.delivery_repository.create(
                {
                    "id": delivery_id,
                    "occurrence_id": occurrence["id"],
                    "user_id": occurrence["user_id"],
                    "channel": "assistant_api",
                    "status": "delivered",
                    "error_code": None,
                    "error_message": None,
                    "request_payload": notification_result["request_payload"],
                    "response_payload": notification_result["response_payload"],
                    "created_at": dispatched_at,
                }
            )
            self.occurrence_repository.update_delivery_result(
                occurrence_id=occurrence["id"],
                status="delivered",
                updated_at=dispatched_at,
                delivery_id=delivery_id,
            )
            self._sync_source_record_status(
                occurrence=occurrence,
                status="delivered",
                updated_at=dispatched_at,
                error_message=None,
            )
            delivered += 1
            delivery_ids.append(delivery_id)

        return {
            "scanned_at": scan_started_at.isoformat(),
            "processed": processed,
            "delivered": delivered,
            "failed": failed,
            "delivery_ids": delivery_ids,
        }

    def _sync_source_record_status(
        self,
        *,
        occurrence: dict[str, Any],
        status: str,
        updated_at: str,
        error_message: str | None,
    ) -> None:
        if str(occurrence.get("source_type") or "").strip() != "set_reminder":
            return

        fields: dict[str, Any] = {
            "status": status,
            "updated_at": updated_at,
        }
        if status == "delivered":
            fields["delivered_at"] = updated_at
            fields["last_error"] = None
        elif error_message:
            fields["last_error"] = error_message

        self.reminder_repository.update_fields(
            user_id=str(occurrence.get("user_id") or ""),
            reminder_id=str(occurrence.get("source_id") or ""),
            fields=fields,
        )


def _build_reminder_source(occurrence: dict[str, Any]) -> dict[str, str]:
    source_type = str(occurrence.get("source_type") or "").strip() or "unknown"
    source_label = str(occurrence.get("source_label") or "").strip() or _default_source_label(source_type)
    return {
        "type": source_type,
        "label": source_label,
    }


def _default_source_label(source_type: str) -> str:
    source_labels = {
        "set_reminder": "自定义提醒",
        "todo": "待办事项提醒",
        "birthday": "生日提醒",
        "idea": "灵感提醒",
    }
    return source_labels.get(source_type, "提醒")
