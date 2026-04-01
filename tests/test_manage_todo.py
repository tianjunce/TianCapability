from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.capabilities.manage_todo.handler import handle
from app.services.todo_service import TodoService, TodoValidationError


class TodoServiceTests(unittest.TestCase):
    def test_create_todo_without_deadline_persists_todo_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            result = TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                notes="补上本周项目进展",
                progress_percent=20,
                difficulty="high",
            )

            todos_path = Path(temp_dir) / "manage_todo" / "todos.json"
            todos = json.loads(todos_path.read_text(encoding="utf-8"))
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"

        self.assertEqual(result["status"], "open")
        self.assertEqual(result["title"], "写周报")
        self.assertEqual(result["occurrence_ids"], [])
        self.assertEqual(result["reminder_plan"], [])
        self.assertEqual(len(todos), 1)
        self.assertFalse(occurrences_path.exists())

    def test_create_todo_with_deadline_generates_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            return_value=datetime(2099, 4, 1, 9, 0, 0),
        ):
            result = TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                notes="补上本周项目进展",
                deadline="2099-04-09 09:00",
                progress_percent=20,
                difficulty="high",
            )

            todos_path = Path(temp_dir) / "manage_todo" / "todos.json"
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            todos = json.loads(todos_path.read_text(encoding="utf-8"))
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(result["deadline"], "2099-04-09T09:00:00")
        self.assertEqual(len(result["occurrence_ids"]), 4)
        self.assertEqual(len(result["reminder_plan"]), 4)
        self.assertEqual(result["reminder_plan"][0]["stage"], "remaining_50_percent")
        self.assertEqual(result["reminder_plan"][0]["remind_at"], "2099-04-05T09:00:00")
        self.assertEqual(result["reminder_plan"][1]["stage"], "remaining_25_percent")
        self.assertEqual(result["reminder_plan"][1]["remind_at"], "2099-04-07T09:00:00")
        self.assertEqual(result["reminder_plan"][2]["stage"], "deadline_minus_1_day")
        self.assertEqual(result["reminder_plan"][2]["remind_at"], "2099-04-08T09:00:00")
        self.assertEqual(result["reminder_plan"][3]["stage"], "remaining_10_percent")
        self.assertEqual(result["reminder_plan"][3]["remind_at"], "2099-04-08T13:48:00")
        self.assertEqual(todos[0]["occurrence_ids"], result["occurrence_ids"])
        self.assertEqual(len(occurrences), 4)
        self.assertEqual(occurrences[0]["source_type"], "todo")
        self.assertEqual(occurrences[0]["source_label"], "待办事项提醒")

    def test_create_todo_rejects_invalid_progress_percent(self) -> None:
        with self.assertRaises(TodoValidationError) as context:
            TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                progress_percent=101,
            )

        self.assertEqual(context.exception.code, "invalid_progress_percent")


class ManageTodoHandlerTests(unittest.TestCase):
    def test_handle_requires_user_id(self) -> None:
        with self.assertRaisesRegex(Exception, "context.user_id is required"):
            asyncio.run(
                handle(
                    {
                        "title": "写周报",
                    },
                    {"request_id": "task-1"},
                )
            )

    def test_handle_creates_todo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            payload = asyncio.run(
                handle(
                    {
                        "title": "写周报",
                        "deadline": "2099-04-09 09:00",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

            todos_path = Path(temp_dir) / "manage_todo" / "todos.json"
            todos = json.loads(todos_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "open")
        self.assertEqual(payload["title"], "写周报")
        self.assertEqual(len(payload["occurrence_ids"]), 4)
        self.assertEqual(len(todos), 1)
