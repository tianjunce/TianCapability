from __future__ import annotations

import asyncio
from typing import Any

from app.capabilities.search_news.search_client import search_news
from app.schemas.common import CapabilityExecutionError
from app.services.progress_writer import ProgressWriter


NORMALIZE_INPUT_STEP_ID = "normalize_search_news_input"
FETCH_SEARCH_STEP_ID = "fetch_site_search_results"
FORMAT_RESULT_STEP_ID = "format_site_search_results"

NORMALIZE_INPUT_LABEL = "规范化站点搜索参数"
FETCH_SEARCH_LABEL = "抓取并解析站点搜索结果"
FORMAT_RESULT_LABEL = "整理结构化搜索结果"


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    writer.running(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
    query = str(input.get("query") or "").strip()
    category = str(input.get("category") or "").strip().lower()
    top_k = input.get("top_k", 5)

    if not query:
        writer.error(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
        raise CapabilityExecutionError(code="invalid_input", message="field 'query' is required")
    if category not in {"news", "tech", "entertainment", "other"}:
        writer.error(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
        raise CapabilityExecutionError(
            code="invalid_input",
            message="field 'category' must be one of: news, tech, entertainment, other",
        )
    writer.success(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)

    writer.running(FETCH_SEARCH_STEP_ID, FETCH_SEARCH_LABEL)
    try:
        payload = await asyncio.to_thread(
            search_news,
            query,
            category,
            top_k,
        )
    except ValueError as exc:
        writer.error(FETCH_SEARCH_STEP_ID, FETCH_SEARCH_LABEL)
        raise CapabilityExecutionError(code="invalid_input", message=str(exc)) from exc
    writer.success(FETCH_SEARCH_STEP_ID, FETCH_SEARCH_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return payload
