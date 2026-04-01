from __future__ import annotations

import asyncio
from typing import Any

from app.capabilities.get_volleyball_match_list.match_list import (
    DEFAULT_PAGE_NUM,
    DEFAULT_PAGE_SIZE,
    fetch_day_stat,
    fetch_match_dates,
    fetch_match_list,
)
from app.schemas.common import CapabilityExecutionError
from app.services.progress_writer import ProgressWriter


VALID_QUERY_TYPES = {"list", "dates", "match_dates", "available_dates", "day_stat"}

NORMALIZE_INPUT_STEP_ID = "normalize_query_input"
FETCH_DATA_STEP_ID = "fetch_volleyball_data"
FORMAT_RESULT_STEP_ID = "format_volleyball_result"

NORMALIZE_INPUT_LABEL = "规范化查询参数"
FETCH_DATA_LABEL = "查询排球比赛数据"
FORMAT_RESULT_LABEL = "整理排球查询结果"


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _build_match_list_summary(
    *,
    page_num: int,
    page_size: int,
    total: object,
    matches: list[dict[str, Any]],
    available_dates: list[str],
) -> str:
    if not matches:
        return f"排球比赛列表查询成功，第{page_num}页，每页{page_size}条，当前没有查询到比赛记录。"

    previews: list[str] = []
    for item in matches[:5]:
        name = str(item.get("name") or "未命名比赛").strip()
        score_a = item.get("team_a_score")
        score_b = item.get("team_b_score")
        winner = str(item.get("winner") or "").strip()
        score_text = (
            f"{score_a}:{score_b}"
            if score_a is not None and score_b is not None
            else "比分未知"
        )
        winner_text = f"，胜方 {winner}" if winner else ""
        previews.append(f"{name}（{score_text}{winner_text}）")

    total_text = f"，总数 {total}" if total is not None else ""
    date_hint = ""
    if available_dates:
        date_hint = f" 可查询日期示例：{', '.join(available_dates[:5])}。"
    return (
        f"排球比赛列表查询成功，第{page_num}页，每页{page_size}条{total_text}。"
        f"部分结果：{'；'.join(previews)}。{date_hint}"
    ).strip()


def _build_day_stat_summary(*, match_date: str, stats: list[dict[str, Any]]) -> str:
    if not stats:
        return f"{match_date} 的排球每日统计查询成功，但当天没有统计数据。"

    previews: list[str] = []
    for item in stats[:5]:
        name = str(item.get("player_name") or f"球员{item.get('player_id') or ''}").strip()
        score_count = item.get("score_count")
        win_count = item.get("win_count")
        lose_count = item.get("lose_count")
        actual_count = item.get("actual_count")
        previews.append(
            f"{name}（得分 {score_count}，胜 {win_count}，负 {lose_count}，实记 {actual_count}）"
        )

    return f"{match_date} 的排球每日统计查询成功，共 {len(stats)} 名球员。部分结果：{'；'.join(previews)}。"


def _build_dates_summary(available_dates: list[str]) -> str:
    if not available_dates:
        return "排球比赛日期查询成功，但当前没有可用日期。"
    return f"共有 {len(available_dates)} 个有比赛的日期，部分日期：{', '.join(available_dates[:10])}。"


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    writer.running(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
    query_type = str(input.get("query_type") or "list").strip().lower() or "list"
    if query_type not in VALID_QUERY_TYPES:
        writer.error(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
        raise CapabilityExecutionError(
            code="invalid_query_type",
            message=f"unsupported query_type: {query_type}",
        )

    match_date = str(input.get("match_date") or "").strip()
    page_num = _coerce_positive_int(input.get("page_num"), DEFAULT_PAGE_NUM)
    page_size = _coerce_positive_int(input.get("page_size"), DEFAULT_PAGE_SIZE)

    # Allow explicit daily-stat queries without requiring callers to know internal branching.
    if query_type == "day_stat" and not match_date:
        writer.error(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)
        raise CapabilityExecutionError(
            code="invalid_input",
            message="field 'match_date' is required when query_type is 'day_stat'",
        )
    writer.success(NORMALIZE_INPUT_STEP_ID, NORMALIZE_INPUT_LABEL)

    writer.running(FETCH_DATA_STEP_ID, FETCH_DATA_LABEL)
    try:
        if match_date:
            result_data = await asyncio.to_thread(fetch_day_stat, match_date=match_date)
            mode = "day_stat"
        elif query_type in {"dates", "match_dates", "available_dates"}:
            result_data = {
                "available_dates": await asyncio.to_thread(fetch_match_dates),
            }
            mode = "dates"
        else:
            result_data = await asyncio.to_thread(
                fetch_match_list,
                page_num=page_num,
                page_size=page_size,
            )
            result_data["available_dates"] = await asyncio.to_thread(fetch_match_dates)
            mode = "list"
    except ValueError as exc:
        writer.error(FETCH_DATA_STEP_ID, FETCH_DATA_LABEL)
        raise CapabilityExecutionError(code="invalid_input", message=str(exc)) from exc
    except Exception as exc:
        writer.error(FETCH_DATA_STEP_ID, FETCH_DATA_LABEL)
        raise CapabilityExecutionError(code="volleyball_query_failed", message=str(exc)) from exc
    writer.success(FETCH_DATA_STEP_ID, FETCH_DATA_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    response: dict[str, Any] = {
        "query_type": mode,
    }
    if mode == "day_stat":
        stats = result_data.get("stats") or []
        normalized_match_date = str(result_data.get("match_date") or match_date)
        summary = _build_day_stat_summary(
            match_date=normalized_match_date,
            stats=stats,
        )
        response.update(
            {
                "match_date": normalized_match_date,
                "stats": stats,
                "summary": summary,
                "result": summary,
            }
        )
    elif mode == "dates":
        available_dates = result_data.get("available_dates") or []
        summary = _build_dates_summary(available_dates)
        response.update(
            {
                "available_dates": available_dates,
                "summary": summary,
                "result": summary,
            }
        )
    else:
        matches = result_data.get("matches") or []
        available_dates = result_data.get("available_dates") or []
        summary = _build_match_list_summary(
            page_num=int(result_data.get("page_num") or page_num),
            page_size=int(result_data.get("page_size") or page_size),
            total=result_data.get("total"),
            matches=matches,
            available_dates=available_dates,
        )
        response.update(
            {
                "page_num": int(result_data.get("page_num") or page_num),
                "page_size": int(result_data.get("page_size") or page_size),
                "total": result_data.get("total"),
                "pages": result_data.get("pages"),
                "available_dates": available_dates,
                "matches": matches,
                "summary": summary,
                "result": summary,
            }
        )
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return response
