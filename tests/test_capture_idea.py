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
        self.assertTrue(result["summary"].startswith("已记录灵感：做一个给家长用的作业提醒工具"))

    def test_create_idea_rejects_empty_content(self) -> None:
        with self.assertRaises(IdeaValidationError) as context:
            IdeaService().create_idea(
                user_id="user-1",
                content="",
            )

        self.assertEqual(context.exception.code, "invalid_input")


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

        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["tags"], ["产品"])
        self.assertEqual(len(ideas), 1)


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
