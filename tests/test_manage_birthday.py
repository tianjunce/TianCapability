from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.capabilities.manage_birthday.handler import handle
from app.services.birthday_service import BirthdayService, BirthdayValidationError


class BirthdayServiceTests(unittest.TestCase):
    def test_create_solar_birthday_generates_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            result = BirthdayService().create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
                notes="提前准备蛋糕",
            )

            birthdays_path = Path(temp_dir) / "manage_birthday" / "birthdays.json"
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            birthdays = json.loads(birthdays_path.read_text(encoding="utf-8"))
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["action"], "create")
        self.assertEqual(result["next_birthday"], "2099-05-12")
        self.assertEqual(len(result["occurrence_ids"]), 2)
        self.assertEqual(result["reminder_plan"][0]["stage"], "birthday_minus_7_days")
        self.assertEqual(result["reminder_plan"][0]["remind_at"], "2099-05-05T09:00:00")
        self.assertEqual(result["reminder_plan"][1]["stage"], "birthday_minus_1_day")
        self.assertEqual(result["reminder_plan"][1]["remind_at"], "2099-05-11T09:00:00")
        self.assertEqual(len(birthdays), 1)
        self.assertEqual(birthdays[0]["name"], "妈妈")
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(occurrences[0]["source_type"], "birthday")
        self.assertEqual(occurrences[0]["source_label"], "生日提醒")

    def test_create_lunar_birthday_generates_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2017, 5, 1, 10, 0, 0),
        ):
            result = BirthdayService().create_birthday(
                user_id="user-1",
                name="外婆",
                birthday="06-01",
                calendar_type="lunar",
            )

        self.assertEqual(result["next_birthday"], "2017-06-24")
        self.assertEqual(result["action"], "create")
        self.assertEqual(result["reminder_plan"][0]["remind_at"], "2017-06-17T09:00:00")
        self.assertEqual(result["reminder_plan"][1]["remind_at"], "2017-06-23T09:00:00")

    def test_create_birthday_rolls_to_next_cycle_when_current_cycle_is_too_late(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            result = BirthdayService().create_birthday(
                user_id="user-1",
                name="老师",
                birthday="04-01",
                calendar_type="solar",
            )

        self.assertEqual(result["next_birthday"], "2100-04-01")
        self.assertEqual(result["reminder_plan"][0]["remind_at"], "2100-03-25T09:00:00")
        self.assertEqual(result["reminder_plan"][1]["remind_at"], "2100-03-31T09:00:00")

    def test_create_birthday_rejects_invalid_calendar_type(self) -> None:
        with self.assertRaises(BirthdayValidationError) as context:
            BirthdayService().create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="unknown",
            )

        self.assertEqual(context.exception.code, "invalid_calendar_type")

    def test_list_birthdays_returns_sorted_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            service = BirthdayService()
            service.create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )
            service.create_birthday(
                user_id="user-1",
                name="老师",
                birthday="04-15",
                calendar_type="solar",
            )

            result = service.list_birthdays(user_id="user-1")

        self.assertEqual(result["action"], "list")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["birthdays"][0]["name"], "老师")
        self.assertEqual(result["birthdays"][1]["name"], "妈妈")

    def test_list_birthdays_supports_filtering_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            service = BirthdayService()
            service.create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )
            service.create_birthday(
                user_id="user-1",
                name="爸爸",
                birthday="06-18",
                calendar_type="solar",
            )

            result = service.list_birthdays(user_id="user-1", name="妈妈")

        self.assertEqual(result["action"], "list")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["birthdays"][0]["name"], "妈妈")
        self.assertEqual(result["summary"], "共找到 1 条名字为 妈妈 的生日记录。")

    def test_delete_birthday_marks_deleted_and_hides_from_default_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            side_effect=[
                datetime(2099, 4, 1, 10, 0, 0),
                datetime(2099, 4, 1, 11, 0, 0),
            ],
        ):
            service = BirthdayService()
            created = service.create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )

            result = service.delete_birthday(
                user_id="user-1",
                birthday_id=created["birthday_id"],
            )
            listed = service.list_birthdays(user_id="user-1")
            deleted_only = service.list_birthdays(user_id="user-1", status="deleted")

        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(listed["total"], 0)
        self.assertEqual(deleted_only["total"], 1)

    def test_delete_birthday_supports_unique_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            side_effect=[
                datetime(2099, 4, 1, 10, 0, 0),
                datetime(2099, 4, 1, 11, 0, 0),
            ],
        ):
            service = BirthdayService()
            service.create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )

            result = service.delete_birthday(
                user_id="user-1",
                name="妈妈",
            )

        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["name"], "妈妈")

    def test_delete_birthday_rejects_ambiguous_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            service = BirthdayService()
            service.create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )
            service.create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="08-03",
                calendar_type="lunar",
            )

            with self.assertRaises(BirthdayValidationError) as context:
                service.delete_birthday(
                    user_id="user-1",
                    name="妈妈",
                )

        self.assertEqual(context.exception.code, "ambiguous_birthday")


class ManageBirthdayHandlerTests(unittest.TestCase):
    def test_handle_requires_user_id(self) -> None:
        with self.assertRaisesRegex(Exception, "context.user_id is required"):
            asyncio.run(
                handle(
                    {
                        "name": "妈妈",
                        "birthday": "05-12",
                    },
                    {"request_id": "task-1"},
                )
            )

    def test_handle_creates_birthday(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            payload = asyncio.run(
                handle(
                    {
                        "name": "妈妈",
                        "birthday": "05-12",
                        "calendar_type": "solar",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

            birthdays_path = Path(temp_dir) / "manage_birthday" / "birthdays.json"
            birthdays = json.loads(birthdays_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["name"], "妈妈")
        self.assertEqual(len(payload["occurrence_ids"]), 2)
        self.assertEqual(len(birthdays), 1)

    def test_handle_lists_birthdays(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            BirthdayService().create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
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
        self.assertEqual(payload["birthdays"][0]["name"], "妈妈")

    def test_handle_lists_birthdays_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            service = BirthdayService()
            service.create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )
            service.create_birthday(
                user_id="user-1",
                name="老师",
                birthday="04-15",
                calendar_type="solar",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "list",
                        "name": "妈妈",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "list")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["birthdays"][0]["name"], "妈妈")

    def test_handle_deletes_birthday(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            side_effect=[
                datetime(2099, 4, 1, 10, 0, 0),
                datetime(2099, 4, 1, 11, 0, 0),
            ],
        ):
            created = BirthdayService().create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "delete",
                        "birthday_id": created["birthday_id"],
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["status"], "deleted")

    def test_handle_deletes_birthday_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            side_effect=[
                datetime(2099, 4, 1, 10, 0, 0),
                datetime(2099, 4, 1, 11, 0, 0),
            ],
        ):
            BirthdayService().create_birthday(
                user_id="user-1",
                name="妈妈",
                birthday="05-12",
                calendar_type="solar",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "delete",
                        "name": "妈妈",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["status"], "deleted")
        self.assertEqual(payload["name"], "妈妈")

    def test_handle_batch_creates_birthdays(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.birthday_service._now",
            return_value=datetime(2099, 4, 1, 10, 0, 0),
        ):
            payload = asyncio.run(
                handle(
                    {
                        "action": "create",
                        "items": [
                            {
                                "name": "妈妈",
                                "birthday": "05-12",
                                "calendar_type": "solar",
                            },
                            {
                                "name": "妈妈",
                                "birthday": "08-03",
                                "calendar_type": "lunar",
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
        self.assertEqual(payload["success_count"], 2)
        self.assertEqual(payload["failure_count"], 0)
