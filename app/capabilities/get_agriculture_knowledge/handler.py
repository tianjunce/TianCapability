from __future__ import annotations

import asyncio
from typing import Any

import requests

from app.capabilities.get_agriculture_knowledge.knowledge_client import (
    KnowledgeClientError,
    extract_answer,
    normalize_references,
    query_knowledge,
    validate_upstream_result,
)
from app.schemas.common import CapabilityExecutionError
from app.services.progress_writer import ProgressWriter


NORMALIZE_INPUT_STEP_ID = "normalize_agriculture_input"
FETCH_KNOWLEDGE_STEP_ID = "fetch_agriculture_knowledge"
FORMAT_RESULT_STEP_ID = "format_agriculture_result"

NORMALIZE_INPUT_LABEL = "规范化农业知识查询参数"
FETCH_KNOWLEDGE_LABEL = "查询农业知识库"
FORMAT_RESULT_LABEL = "整理农业知识查询结果"

VALID_KB_TYPES = {"rice", "morel", "dzjym"}


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    writer.running(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
    kb_type = str(input.get("kb_type") or "").strip().lower()
    item_name = str(input.get("item_name") or "").strip() or None
    query = str(input.get("query") or "").strip()

    if kb_type not in VALID_KB_TYPES:
        writer.error(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
        raise CapabilityExecutionError(
            code="invalid_input",
            message="field 'kb_type' must be one of: rice, morel, dzjym",
        )
    if not query:
        writer.error(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
        raise CapabilityExecutionError(
            code="invalid_input",
            message="field 'query' is required",
        )
    writer.success(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)

    writer.running(FETCH_KNOWLEDGE_STEP_ID, FETCH_KNOWLEDGE_LABEL)
    try:
        raw_data = await asyncio.to_thread(
            query_knowledge,
            message=query,
            project=kb_type,
            item_name=item_name,
        )
        validate_upstream_result(raw_data)
    except requests.HTTPError as exc:
        writer.error(FETCH_KNOWLEDGE_STEP_ID, FETCH_KNOWLEDGE_LABEL)
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise CapabilityExecutionError(
            code="knowledge_query_failed",
            message=f"knowledge service http error: {status_code}",
        ) from exc
    except requests.RequestException as exc:
        writer.error(FETCH_KNOWLEDGE_STEP_ID, FETCH_KNOWLEDGE_LABEL)
        raise CapabilityExecutionError(
            code="knowledge_query_failed",
            message=str(exc),
        ) from exc
    except KnowledgeClientError as exc:
        writer.error(FETCH_KNOWLEDGE_STEP_ID, FETCH_KNOWLEDGE_LABEL)
        raise CapabilityExecutionError(
            code="knowledge_auth_failed",
            message=str(exc),
        ) from exc
    writer.success(FETCH_KNOWLEDGE_STEP_ID, FETCH_KNOWLEDGE_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    references = normalize_references(raw_data)
    answer = extract_answer(raw_data)
    result = f"{kb_type} 知识库查询成功"
    if item_name:
        result = f"{kb_type} 知识库中关于{item_name}的查询成功"
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)

    return {
        "result": result,
        "kb_type": kb_type,
        "item_name": item_name,
        "answer": answer,
        "reference_list": references,
        "raw": raw_data,
    }
