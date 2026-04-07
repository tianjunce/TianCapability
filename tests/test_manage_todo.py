from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.capabilities.manage_todo.handler import handle
from app.main import create_app
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
        self.assertEqual(result["action"], "create")
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
        self.assertEqual(result["action"], "create")
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

    def test_list_todos_returns_sorted_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            service = TodoService()
            service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )
            service.create_todo(
                user_id="user-1",
                title="交作业",
                deadline="2099-04-05 09:00",
            )

            result = service.list_todos(user_id="user-1")

        self.assertEqual(result["action"], "list")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["todos"][0]["title"], "交作业")
        self.assertEqual(result["todos"][1]["title"], "写周报")

    def test_list_todos_supports_time_range_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 9, 0, 0),
            ],
        ):
            service = TodoService()
            service.create_todo(
                user_id="user-1",
                title="本周交付",
                deadline="2099-04-05 18:00",
            )
            service.create_todo(
                user_id="user-1",
                title="月底复盘",
                deadline="2099-04-20 18:00",
            )

            result = service.list_todos(
                user_id="user-1",
                time_range="最近一个星期",
            )

        self.assertEqual(result["action"], "list")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["todos"][0]["title"], "本周交付")
        self.assertEqual(result["summary"], "共找到 1 条最近一个星期内的待办记录。")

    def test_list_todos_ignores_unknown_time_range_and_returns_all(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 9, 0, 0),
            ],
        ):
            service = TodoService()
            service.create_todo(
                user_id="user-1",
                title="本周交付",
                deadline="2099-04-05 18:00",
            )
            service.create_todo(
                user_id="user-1",
                title="月底复盘",
                deadline="2099-04-20 18:00",
            )

            result = service.list_todos(
                user_id="user-1",
                time_range="乱写一个范围",
            )

        self.assertEqual(result["action"], "list")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["summary"], "共找到 2 条待办记录。")

    def test_list_todos_supports_unfinished_status_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            return_value=datetime(2099, 4, 1, 9, 0, 0),
        ):
            service = TodoService()
            service.create_todo(user_id="user-1", title="写周报")
            created = service.create_todo(user_id="user-1", title="交作业")
            service.complete_todo(user_id="user-1", todo_id=created["todo_id"])

            result_pending = service.list_todos(user_id="user-1", status="pending")
            result_unfinished = service.list_todos(user_id="user-1", status="未完成")

        self.assertEqual(result_pending["action"], "list")
        self.assertEqual(result_pending["total"], 1)
        self.assertEqual(result_pending["todos"][0]["title"], "写周报")
        self.assertEqual(result_unfinished["total"], 1)
        self.assertEqual(result_unfinished["todos"][0]["title"], "写周报")

    def test_complete_todo_updates_status_and_cancels_pending_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            return_value=datetime(2099, 4, 1, 9, 0, 0),
        ):
            service = TodoService()
            created = service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            result = service.complete_todo(
                user_id="user-1",
                todo_id=created["todo_id"],
            )

            todos_path = Path(temp_dir) / "manage_todo" / "todos.json"
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            todos = json.loads(todos_path.read_text(encoding="utf-8"))
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(result["action"], "complete")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(todos[0]["status"], "completed")
        self.assertTrue(all(item["status"] == "cancelled" for item in occurrences))

    def test_update_todo_rebuilds_future_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 2, 9, 0, 0),
                datetime(2099, 4, 2, 9, 0, 0),
            ],
        ):
            service = TodoService()
            created = service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            result = service.update_todo(
                user_id="user-1",
                todo_id=created["todo_id"],
                deadline="2099-04-10 09:00",
                notes="更新版",
            )

            todos_path = Path(temp_dir) / "manage_todo" / "todos.json"
            occurrences_path = Path(temp_dir) / "reminders" / "occurrences.json"
            todos = json.loads(todos_path.read_text(encoding="utf-8"))
            occurrences = json.loads(occurrences_path.read_text(encoding="utf-8"))

        self.assertEqual(result["action"], "update")
        self.assertEqual(result["deadline"], "2099-04-10T09:00:00")
        self.assertEqual(todos[0]["deadline"], "2099-04-10T09:00:00")
        self.assertEqual(len(occurrences), 8)
        self.assertEqual(sum(1 for item in occurrences if item["status"] == "cancelled"), 4)
        self.assertEqual(sum(1 for item in occurrences if item["status"] == "pending"), 4)

    def test_update_todo_supports_unique_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 2, 9, 0, 0),
                datetime(2099, 4, 2, 9, 0, 0),
            ],
        ):
            service = TodoService()
            service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            result = service.update_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-10 09:00",
                notes="更新版",
            )

        self.assertEqual(result["action"], "update")
        self.assertEqual(result["deadline"], "2099-04-10T09:00:00")
        self.assertEqual(result["title"], "写周报")

    def test_update_todo_rejects_ambiguous_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            return_value=datetime(2099, 4, 1, 9, 0, 0),
        ):
            service = TodoService()
            service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )
            service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-10 09:00",
            )

            with self.assertRaises(TodoValidationError) as context:
                service.update_todo(
                    user_id="user-1",
                    title="写周报",
                    notes="更新版",
                )

        self.assertEqual(context.exception.code, "ambiguous_todo")

    def test_delete_todo_marks_deleted_and_hides_from_default_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 10, 0, 0),
            ],
        ):
            service = TodoService()
            created = service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            result = service.delete_todo(
                user_id="user-1",
                todo_id=created["todo_id"],
            )
            listed = service.list_todos(user_id="user-1")
            deleted_only = service.list_todos(user_id="user-1", status="deleted")

        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(listed["total"], 0)
        self.assertEqual(deleted_only["total"], 1)

    def test_delete_todo_supports_unique_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 10, 0, 0),
            ],
        ):
            service = TodoService()
            service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            result = service.delete_todo(
                user_id="user-1",
                title="写周报",
            )

        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["title"], "写周报")

    def test_delete_todo_rejects_ambiguous_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            return_value=datetime(2099, 4, 1, 9, 0, 0),
        ):
            service = TodoService()
            service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )
            service.create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-10 09:00",
            )

            with self.assertRaises(TodoValidationError) as context:
                service.delete_todo(
                    user_id="user-1",
                    title="写周报",
                )

        self.assertEqual(context.exception.code, "ambiguous_todo")


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

        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["status"], "open")
        self.assertEqual(payload["title"], "写周报")
        self.assertEqual(len(payload["occurrence_ids"]), 4)
        self.assertEqual(len(todos), 1)

    def test_handle_lists_todos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            TodoService().create_todo(
                user_id="user-1",
                title="写周报",
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
        self.assertEqual(payload["todos"][0]["title"], "写周报")

    def test_handle_defaults_empty_input_to_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            TodoService().create_todo(
                user_id="user-1",
                title="写周报",
            )

            payload = asyncio.run(
                handle(
                    {},
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "list")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["todos"][0]["title"], "写周报")

    def test_endpoint_accepts_wrapped_prepared_payload_for_time_range_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 9, 0, 0),
            ],
        ):
            TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-05 18:00",
            )

            client = TestClient(create_app())
            response = client.post(
                "/capabilities/manage_todo",
                json={
                    "input": {
                        "constraints": {},
                        "context": {
                            "source": "ingress_fresh",
                            "source_user_message": "最近一个星期有我需要完成的待办事项吗",
                        },
                        "slots": {
                            "time_range": "最近一个星期",
                        },
                    },
                    "context": {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["action"], "list")
        self.assertEqual(body["data"]["total"], 1)
        self.assertEqual(body["data"]["todos"][0]["title"], "写周报")

    def test_endpoint_accepts_pending_status_alias_for_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            return_value=datetime(2099, 4, 1, 9, 0, 0),
        ):
            service = TodoService()
            service.create_todo(user_id="user-1", title="写周报")
            created = service.create_todo(user_id="user-1", title="交作业")
            service.complete_todo(user_id="user-1", todo_id=created["todo_id"])

            client = TestClient(create_app())
            response = client.post(
                "/capabilities/manage_todo",
                json={
                    "input": {
                        "action": "list",
                        "status": "pending",
                    },
                    "context": {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["action"], "list")
        self.assertEqual(body["data"]["total"], 1)
        self.assertEqual(body["data"]["todos"][0]["title"], "写周报")

    def test_endpoint_accepts_wrapped_prepared_payload_for_update_with_title_like_todo_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ):
            TodoService().create_todo(
                user_id="user-1",
                title="开发 excalidraw/revezone 相关 SKILL",
            )

            client = TestClient(create_app())
            response = client.post(
                "/capabilities/manage_todo",
                json={
                    "input": {
                        "constraints": {},
                        "context": {
                            "action": "update",
                            "todo_id": "开发 excalidraw/revezone 相关 SKILL",
                        },
                        "slots": {
                            "progress_percent": 10,
                        },
                    },
                    "context": {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["action"], "update")
        self.assertEqual(body["data"]["title"], "开发 excalidraw/revezone 相关 SKILL")
        self.assertEqual(body["data"]["progress_percent"], 10)

    def test_endpoint_accepts_wrapped_prepared_payload_for_update_with_latest_todo_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 9, 0, 1),
                datetime(2099, 4, 1, 9, 0, 2),
                datetime(2099, 4, 1, 9, 0, 3),
            ],
        ):
            TodoService().create_todo(user_id="user-1", title="skill更新", notes="旧的")
            TodoService().create_todo(user_id="user-1", title="skill更新", notes="最新的")

            client = TestClient(create_app())
            response = client.post(
                "/capabilities/manage_todo",
                json={
                    "input": {
                        "constraints": {},
                        "context": {
                            "action": "update",
                            "title": "skill更新",
                        },
                        "slots": {
                            "deadline": "2099-04-07 17:59",
                            "todo_id": "latest",
                        },
                    },
                    "context": {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                },
            )

            listed = TodoService().list_todos(user_id="user-1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["action"], "update")
        self.assertEqual(body["data"]["title"], "skill更新")
        self.assertEqual(body["data"]["deadline"], "2099-04-07T17:59:00")
        skill_updates = [item for item in listed["todos"] if item["title"] == "skill更新"]
        self.assertEqual(len(skill_updates), 2)
        self.assertEqual(sum(1 for item in skill_updates if item["deadline"] == "2099-04-07T17:59:00"), 1)
        self.assertEqual(sum(1 for item in skill_updates if item.get("notes") == "最新的"), 1)

    def test_handle_updates_todo_by_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 2, 9, 0, 0),
                datetime(2099, 4, 2, 9, 0, 0),
            ],
        ):
            TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "update",
                        "title": "写周报",
                        "deadline": "2099-04-10 09:00",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "update")
        self.assertEqual(payload["deadline"], "2099-04-10T09:00:00")

    def test_handle_deletes_todo_by_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 10, 0, 0),
            ],
        ):
            TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "delete",
                        "title": "写周报",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["status"], "deleted")
        self.assertEqual(payload["title"], "写周报")

    def test_handle_completes_todo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            return_value=datetime(2099, 4, 1, 9, 0, 0),
        ):
            created = TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "complete",
                        "todo_id": created["todo_id"],
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "complete")
        self.assertEqual(payload["status"], "completed")

    def test_handle_updates_todo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 2, 9, 0, 0),
            ],
        ):
            created = TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "update",
                        "todo_id": created["todo_id"],
                        "difficulty": "high",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "update")
        self.assertEqual(payload["difficulty"], "high")

    def test_handle_deletes_todo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"CAPABILITY_DATA_DIR": temp_dir},
            clear=False,
        ), patch(
            "app.services.todo_service._now",
            side_effect=[
                datetime(2099, 4, 1, 9, 0, 0),
                datetime(2099, 4, 1, 10, 0, 0),
            ],
        ):
            created = TodoService().create_todo(
                user_id="user-1",
                title="写周报",
                deadline="2099-04-09 09:00",
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "delete",
                        "todo_id": created["todo_id"],
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["status"], "deleted")

    def test_handle_batch_creates_todos(self) -> None:
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
                                "title": "写周报",
                            },
                            {
                                "title": "交作业",
                                "difficulty": "high",
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
