from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.capabilities.capture_idea.handler import handle
from app.services.idea_service import IdeaService, IdeaValidationError


class IdeaServiceTests(unittest.TestCase):
    def test_create_idea_persists_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            result = IdeaService().create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="做一个给家长用的作业提醒工具，重点是晚间统一提醒和周报汇总。",
                tags=["产品", "教育", "产品"],
            )

            ideas_path = Path(temp_dir) / "capture_idea" / "ideas.json"
            ideas = json.loads(ideas_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["action"], "create")
        self.assertEqual(result["title"], "家长作业提醒工具")
        self.assertEqual(result["tags"], ["产品", "教育"])
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0]["content"], "做一个给家长用的作业提醒工具，重点是晚间统一提醒和周报汇总。")

    def test_create_idea_without_title_uses_content_excerpt_in_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            result = IdeaService().create_idea(
                user_id="user-1",
                content="做一个给家长用的作业提醒工具，重点是晚间统一提醒和周报汇总。",
            )

        self.assertIsNone(result["title"])
        self.assertEqual(result["action"], "create")
        self.assertTrue(result["summary"].startswith("已记录灵感：做一个给家长用的作业提醒工具"))

    def test_create_idea_rejects_empty_content(self) -> None:
        with self.assertRaises(IdeaValidationError) as context:
            IdeaService().create_idea(
                user_id="user-1",
                content="",
            )

        self.assertEqual(context.exception.code, "invalid_input")

    def test_list_ideas_supports_tag_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            service = IdeaService()
            service.create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="做一个给家长用的作业提醒工具",
                tags=["产品", "教育"],
            )
            service.create_idea(
                user_id="user-1",
                title="晨检流程",
                content="做一个晨检流程优化看板",
                tags=["流程"],
            )

            result = service.list_ideas(user_id="user-1", tag="产品")

        self.assertEqual(result["action"], "list")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["ideas"][0]["title"], "家长作业提醒工具")

    def test_delete_idea_marks_deleted_and_hides_from_default_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            service = IdeaService()
            created = service.create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="做一个给家长用的作业提醒工具",
                tags=["产品"],
            )

            result = service.delete_idea(
                user_id="user-1",
                idea_id=created["idea_id"],
            )
            listed = service.list_ideas(user_id="user-1")
            deleted_only = service.list_ideas(user_id="user-1", status="deleted")

        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(listed["total"], 0)
        self.assertEqual(deleted_only["total"], 1)

    def test_delete_idea_supports_unique_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            service = IdeaService()
            service.create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="做一个给家长用的作业提醒工具",
                tags=["产品"],
            )

            result = service.delete_idea(
                user_id="user-1",
                title="家长作业提醒工具",
            )

        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["status"], "deleted")

    def test_delete_idea_supports_unique_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            service = IdeaService()
            service.create_idea(
                user_id="user-1",
                content="做一个给家长用的作业提醒工具",
            )

            result = service.delete_idea(
                user_id="user-1",
                content="做一个给家长用的作业提醒工具",
            )

        self.assertEqual(result["action"], "delete")
        self.assertEqual(result["status"], "deleted")

    def test_delete_idea_rejects_ambiguous_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            service = IdeaService()
            service.create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="方案一",
            )
            service.create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="方案二",
            )

            with self.assertRaises(IdeaValidationError) as context:
                service.delete_idea(
                    user_id="user-1",
                    title="家长作业提醒工具",
                )

        self.assertEqual(context.exception.code, "ambiguous_idea")


class CaptureIdeaHandlerTests(unittest.TestCase):
    def test_handle_requires_user_id(self) -> None:
        with self.assertRaisesRegex(Exception, "context.user_id is required"):
            asyncio.run(
                handle(
                    {
                        "content": "做一个给家长用的作业提醒工具",
                    },
                    {"request_id": "task-1"},
                )
            )

    def test_handle_creates_idea(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            payload = asyncio.run(
                handle(
                    {
                        "title": "家长作业提醒工具",
                        "content": "做一个给家长用的作业提醒工具",
                        "tags": ["产品"],
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

            ideas_path = Path(temp_dir) / "capture_idea" / "ideas.json"
            ideas = json.loads(ideas_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["action"], "create")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["tags"], ["产品"])
        self.assertEqual(len(ideas), 1)

    def test_handle_lists_ideas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            IdeaService().create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="做一个给家长用的作业提醒工具",
                tags=["产品"],
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "list",
                        "tag": "产品",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "list")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["ideas"][0]["title"], "家长作业提醒工具")

    def test_handle_deletes_idea(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            created = IdeaService().create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="做一个给家长用的作业提醒工具",
                tags=["产品"],
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "delete",
                        "idea_id": created["idea_id"],
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["status"], "deleted")

    def test_handle_deletes_idea_by_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            IdeaService().create_idea(
                user_id="user-1",
                title="家长作业提醒工具",
                content="做一个给家长用的作业提醒工具",
                tags=["产品"],
            )

            payload = asyncio.run(
                handle(
                    {
                        "action": "delete",
                        "title": "家长作业提醒工具",
                    },
                    {
                        "request_id": "task-1",
                        "user_id": "user-1",
                    },
                )
            )

        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["status"], "deleted")

    def test_handle_batch_creates_ideas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch_env(temp_dir):
            payload = asyncio.run(
                handle(
                    {
                        "action": "create",
                        "items": [
                            {
                                "title": "家长作业提醒工具",
                                "content": "做一个给家长用的作业提醒工具",
                            },
                            {
                                "title": "晨检流程",
                                "content": "做一个晨检流程优化看板",
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


class patch_env:
    def __init__(self, temp_dir: str) -> None:
        self.temp_dir = temp_dir
        self.original = None

    def __enter__(self) -> None:
        self.original = os.environ.get("CAPABILITY_DATA_DIR")
        os.environ["CAPABILITY_DATA_DIR"] = self.temp_dir
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.original is None:
            os.environ.pop("CAPABILITY_DATA_DIR", None)
        else:
            os.environ["CAPABILITY_DATA_DIR"] = self.original
