from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.capabilities.set_reminder.handler import handle
from app.services.reminder_dispatch_service import (
    ReminderDispatchError,
    ReminderDispatchService,
    ReminderNotificationClient,
)
from app.services.reminder_service import ReminderService, ReminderValidationError
from app.workers.reminder_worker import run_once


class _SuccessNotificationClient:
    def send_occurrence(self, occurrence: dict[str, object]) -> dict[str, object]:
        return {
            "request_payload": {
                "source": "reminder_worker",
                "user_id": occurrence["user_id"],
                "title": occurrence["title"],
                "content": occurrence["content"],
                "reminder_source": {
                    "type": occurrence["source_type"],
                    "label": occurrence["source_label"],
                },
                "metadata": {
                    "occurrence_id": occurrence["id"],
                    "source_type": occurrence["source_type"],
                    "source_label": occurrence["source_label"],
                    "source_id": occurrence["source_id"],
                    "remind_at": occurrence["remind_at"],
                    "dedupe_key": occurrence["dedupe_key"],
                    "payload": occurrence["payload_json"],
                },
            },
            "response_payload": {
                "message_id": "msg-1",
            },
        }


class _FailingNotificationClient:
    def send_occurrence(self, occurrence: dict[str, object]) -> dict[str, object]:
        raise ReminderDispatchError(code="notification_send_failed", message="upstream failed")


class ReminderServiceTests(unittest.TestCase):
    def test_create_reminder_persists_reminder_and_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            result = ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
                note="到点先看余额",
            )

            reminders_path = Path(temp_dir) / "set_reminder" / "reminders.json"
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"

            reminders = json.loads(reminders_path.read_text(encoding="utf-8"))
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(result["action"], "create")
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["content"], "交电费")
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]["user_id"], "user-1")
        self.assertEqual(reminders[0]["content"], "交电费")
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["source_type"], "set_reminder")
        self.assertEqual(occurrences[0]["source_label"], "自定义提醒")
        self.assertEqual(occurrences[0]["source_id"], result["reminder_id"])
        self.assertEqual(occurrences[0]["status"], "pending")

    def test_create_reminder_rejects_past_datetime(self) -> None:
        with self.assertRaises(ReminderValidationError) as context:
            ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2000-01-01 09:00",
            )

        self.assertEqual(context.exception.code, "reminder_in_past")

    def test_list_reminders_returns_sorted_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = ReminderService()
            service.create_reminder(
                user_id="user-1",
                content="开会",
                remind_at="2099-04-02 10:00",
            )
            service.create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            result = service.list_reminders(user_id="user-1")

        self.assertEqual(result["action"], "list")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["reminders"][0]["content"], "交电费")
        self.assertEqual(result["reminders"][1]["content"], "开会")

    def test_cancel_reminder_updates_reminder_and_occurrence_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = ReminderService()
            created = service.create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            result = service.cancel_reminder(
                user_id="user-1",
                reminder_id=created["reminder_id"],
            )

            reminders_path = Path(temp_dir) / "set_reminder" / "reminders.json"
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            reminders = json.loads(reminders_path.read_text(encoding="utf-8"))
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(result["action"], "cancel")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(result["cancelled_occurrence_ids"]), 1)
        self.assertEqual(reminders[0]["status"], "cancelled")
        self.assertEqual(occurrences[0]["status"], "cancelled")

    def test_cancel_reminder_supports_content_and_human_readable_remind_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = ReminderService()
            service.create_reminder(
                user_id="user-1",
                content="取快递",
                remind_at="2099-04-10 06:00",
            )
            service.create_reminder(
                user_id="user-1",
                content="取快递",
                remind_at="2099-04-10 07:00",
            )

            result = service.cancel_reminder(
                user_id="user-1",
                content="取快递",
                remind_at="2099-04-10 06:00",
            )
            reminders = service.list_reminders(user_id="user-1")

        self.assertEqual(result["action"], "cancel")
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["remind_at"], "2099-04-10T06:00:00")
        cancelled = [item for item in reminders["reminders"] if item["status"] == "cancelled"]
        active = [item for item in reminders["reminders"] if item["status"] == "active"]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0]["remind_at"], "2099-04-10T06:00:00")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["remind_at"], "2099-04-10T07:00:00")

    def test_update_reminder_rebuilds_pending_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = ReminderService()
            created = service.create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            result = service.update_reminder(
                user_id="user-1",
                reminder_id=created["reminder_id"],
                remind_at="2099-04-02 10:00",
                note="改到十点",
            )

            reminders_path = Path(temp_dir) / "set_reminder" / "reminders.json"
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            reminders = json.loads(reminders_path.read_text(encoding="utf-8"))
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(result["action"], "update")
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["remind_at"], "2099-04-02T10:00:00")
        self.assertEqual(reminders[0]["remind_at"], "2099-04-02T10:00:00")
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(occurrences[0]["status"], "cancelled")
        self.assertEqual(occurrences[1]["status"], "pending")
        self.assertEqual(occurrences[1]["remind_at"], "2099-04-02T10:00:00")

    def test_update_reminder_supports_unique_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = ReminderService()
            service.create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            result = service.update_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 10:00",
            )

        self.assertEqual(result["action"], "update")
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["remind_at"], "2099-04-02T10:00:00")

    def test_update_reminder_rejects_ambiguous_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = ReminderService()
            service.create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )
            service.create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-03 09:00",
            )

            with self.assertRaises(ReminderValidationError) as context:
                service.update_reminder(
                    user_id="user-1",
                    content="交电费",
                    note="改一下",
                )

        self.assertEqual(context.exception.code, "ambiguous_reminder")


class SetReminderHandlerTests(unittest.TestCase):
    def test_handle_requires_user_id(self) -> None:
        with self.assertRaisesRegex(Exception, "context.user_id is required"):
            asyncio.run(
                handle(
                    {
                        "content": "交电费",
                        "remind_at": "2099-04-02 09:00",
                    },
                    {"request_id": "task-1"},
                )
            )

    def test_handle_creates_reminder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            payload = asyncio.run(
                handle(
                    {
                        "content": "交电费",
                        "remind_at": "2099-04-02 09:00",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["content"], "交电费")
        self.assertEqual(payload["remind_at"], "2099-04-02T09:00:00")
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["title"], "交电费")

    def test_handle_lists_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "list",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "list")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["reminders"][0]["content"], "交电费")

    def test_handle_cancels_reminder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            created = ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "cancel",
                        "reminder_id": created["reminder_id"],
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "cancel")
        self.assertEqual(payload["status"], "cancelled")

    def test_handle_cancels_reminder_by_content_and_remind_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = ReminderService()
            service.create_reminder(
                user_id="user-1",
                content="取快递",
                remind_at="2099-04-10 06:00",
            )
            service.create_reminder(
                user_id="user-1",
                content="取快递",
                remind_at="2099-04-10 07:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "cancel",
                        "content": "取快递",
                        "remind_at": "2099-04-10 06:00",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "cancel")
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["remind_at"], "2099-04-10T06:00:00")

    def test_handle_updates_reminder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            created = ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "update",
                        "reminder_id": created["reminder_id"],
                        "remind_at": "2099-04-02 10:00",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "update")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["remind_at"], "2099-04-02T10:00:00")

    def test_handle_updates_reminder_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "update",
                        "content": "交电费",
                        "remind_at": "2099-04-02 10:00",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "update")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["remind_at"], "2099-04-02T10:00:00")

    def test_handle_batch_create_collects_successes_and_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            payload = asyncio.run(
                handle(
                    {
                        "action": "create",
                        "items": [
                            {
                                "content": "交电费",
                                "remind_at": "2099-04-02 09:00",
                            },
                            {
                                "content": "吃饭",
                                "remind_at": "2000-01-01 09:00",
                            },
                        ],
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "create")
        self.assertTrue(payload["batch"])
        self.assertEqual(payload["item_count"], 2)
        self.assertEqual(payload["success_count"], 1)
        self.assertEqual(payload["failure_count"], 1)
        self.assertEqual(payload["results"][0]["status"], "success")
        self.assertEqual(payload["results"][1]["status"], "error")


class ReminderDispatchServiceTests(unittest.TestCase):
    def test_notification_client_reads_api_config_from_dotenv_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_CONFIG_DIR": temp_dir},
            clear=False,
        ):
            Path(temp_dir, ".env.local").write_text(
                "\n".join(
                    [
                        "REMINDER_NOTIFICATION_API_URL=http://127.0.0.1:3030/api/internal/notifications/reminders",
                        "REMINDER_NOTIFICATION_API_TOKEN=test-token",
                    ]
                ),
                encoding="utf-8",
            )

            client = ReminderNotificationClient()

        self.assertEqual(
            client.api_url,
            "http://127.0.0.1:3030/api/internal/notifications/reminders",
        )
        self.assertEqual(client.api_token, "test-token")

    def test_dispatch_due_occurrences_marks_delivered_and_persists_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            create_result = ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            dispatch_result = ReminderDispatchService(
                notification_client=_SuccessNotificationClient(),
            ).dispatch_due_occurrences(
                now=datetime(2099, 4, 2, 9, 0),
            )

            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            deliveries_path = Path(temp_dir) / "reminders" / "deliveries.json"
            reminders_path = Path(temp_dir) / "set_reminder" / "reminders.json"
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))
            deliveries = json.loads(deliveries_path.read_text(encoding="utf-8"))
            reminders = json.loads(reminders_path.read_text(encoding="utf-8"))

        self.assertEqual(dispatch_result["processed"], 1)
        self.assertEqual(dispatch_result["delivered"], 1)
        self.assertEqual(dispatch_result["failed"], 0)
        self.assertEqual(occurrences[0]["id"], create_result["occurrence_id"])
        self.assertEqual(occurrences[0]["status"], "delivered")
        self.assertEqual(reminders[0]["status"], "delivered")
        self.assertEqual(deliveries[0]["status"], "delivered")
        self.assertEqual(deliveries[0]["occurrence_id"], create_result["occurrence_id"])
        self.assertEqual(deliveries[0]["request_payload"]["reminder_source"]["type"], "set_reminder")
        self.assertEqual(deliveries[0]["request_payload"]["reminder_source"]["label"], "自定义提醒")
        self.assertEqual(deliveries[0]["request_payload"]["metadata"]["source_label"], "自定义提醒")

    def test_dispatch_due_occurrences_skips_future_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            dispatch_result = ReminderDispatchService(
                notification_client=_SuccessNotificationClient(),
            ).dispatch_due_occurrences(
                now=datetime(2099, 4, 2, 8, 59),
            )

            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(dispatch_result["processed"], 0)
        self.assertEqual(dispatch_result["delivered"], 0)
        self.assertEqual(occurrences[0]["status"], "pending")

    def test_dispatch_due_occurrences_marks_failed_when_notification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            dispatch_result = ReminderDispatchService(
                notification_client=_FailingNotificationClient(),
            ).dispatch_due_occurrences(
                now=datetime(2099, 4, 2, 9, 1),
            )

            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            deliveries_path = Path(temp_dir) / "reminders" / "deliveries.json"
            reminders_path = Path(temp_dir) / "set_reminder" / "reminders.json"
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))
            deliveries = json.loads(deliveries_path.read_text(encoding="utf-8"))
            reminders = json.loads(reminders_path.read_text(encoding="utf-8"))

        self.assertEqual(dispatch_result["processed"], 1)
        self.assertEqual(dispatch_result["delivered"], 0)
        self.assertEqual(dispatch_result["failed"], 1)
        self.assertEqual(occurrences[0]["status"], "failed")
        self.assertEqual(occurrences[0]["last_error"], "upstream failed")
        self.assertEqual(reminders[0]["status"], "failed")
        self.assertEqual(deliveries[0]["status"], "failed")
        self.assertEqual(deliveries[0]["error_code"], "notification_send_failed")

    def test_worker_run_once_scans_due_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            ReminderService().create_reminder(
                user_id="user-1",
                content="交电费",
                remind_at="2099-04-02 09:00",
            )

            with patch(
                "app.workers.reminder_worker.ReminderDispatchService.dispatch_due_occurrences",
                return_value={"processed": 1, "delivered": 1, "failed": 0, "delivery_ids": []},
            ) as mocked_dispatch:
                result = run_once(limit=50)

        mocked_dispatch.assert_called_once_with(limit=50)
        self.assertEqual(result["processed"], 1)
