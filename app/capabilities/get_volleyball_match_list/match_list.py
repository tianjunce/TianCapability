from __future__ import annotations

from typing import Any

import requests


MATCH_LIST_URL = "https://tianjunce.top/volleyballbackend/match/list"
MATCH_DATES_URL = "https://tianjunce.top/volleyballbackend/match/dates"
DAY_STAT_URL = "https://tianjunce.top/volleyballbackend/score/stat/day"
DEFAULT_PAGE_NUM = 1
DEFAULT_PAGE_SIZE = 10


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _normalize_match(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "team_a_score": item.get("team_a_score"),
        "team_b_score": item.get("team_b_score"),
        "winner": item.get("winner"),
        "locked": item.get("locked"),
        "scorekeeper_id": item.get("scorekeeper_id"),
        "created_at": item.get("created_at"),
    }


def _normalize_day_stat(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": item.get("player_id"),
        "player_name": item.get("player_name"),
        "match_date": item.get("match_date"),
        "score_count": item.get("score_count"),
        "win_count": item.get("win_count"),
        "lose_count": item.get("lose_count"),
        "scorekeeper_count": item.get("scorekeeper_count"),
        "total_count": item.get("total_count"),
        "discount_count": item.get("discount_count"),
        "result_count": item.get("result_count"),
        "actual_count": item.get("actual_count"),
        "faqiu_count": item.get("faqiu_count"),
        "erchuan_count": item.get("erchuan_count"),
        "kouqiu_count": item.get("kouqiu_count"),
    }


def _parse_api_payload(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("api returned non-object json")
    code = payload.get("code")
    if code not in (0, 200, "0", "200", None):
        raise ValueError(str(payload.get("msg") or f"api returned code={code}"))
    return payload


def fetch_match_dates() -> list[str]:
    payload = _parse_api_payload(requests.get(MATCH_DATES_URL, timeout=15))
    data = payload.get("data") or []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def fetch_match_list(*, page_num: Any = DEFAULT_PAGE_NUM, page_size: Any = DEFAULT_PAGE_SIZE) -> dict[str, Any]:
    normalized_page_num = _coerce_positive_int(page_num, DEFAULT_PAGE_NUM)
    normalized_page_size = _coerce_positive_int(page_size, DEFAULT_PAGE_SIZE)
    payload = _parse_api_payload(
        requests.get(
            MATCH_LIST_URL,
            params={"page_num": normalized_page_num, "page_size": normalized_page_size},
            timeout=15,
        )
    )

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    rows = data.get("rows") or []
    if not isinstance(rows, list):
        rows = []

    matches = [_normalize_match(item) for item in rows if isinstance(item, dict)]
    return {
        "page_num": normalized_page_num,
        "page_size": normalized_page_size,
        "total": data.get("total"),
        "pages": data.get("pages"),
        "matches": matches,
    }


def fetch_day_stat(*, match_date: str) -> dict[str, Any]:
    normalized_date = str(match_date or "").strip()
    if not normalized_date:
        raise ValueError("match_date is required")

    payload = _parse_api_payload(
        requests.get(DAY_STAT_URL, params={"match_date": normalized_date}, timeout=15)
    )
    data = payload.get("data") or []
    if not isinstance(data, list):
        data = []

    stats = [_normalize_day_stat(item) for item in data if isinstance(item, dict)]
    return {
        "match_date": normalized_date,
        "stats": stats,
    }


def volleyball_query_tool(
    *,
    page_num: Any = DEFAULT_PAGE_NUM,
    page_size: Any = DEFAULT_PAGE_SIZE,
    match_date: Any = None,
    query_type: Any = None,
) -> dict[str, Any]:
    try:
        normalized_query_type = str(query_type or "").strip().lower()
        normalized_match_date = str(match_date or "").strip()

        if normalized_match_date:
            data = fetch_day_stat(match_date=normalized_match_date)
            return {
                "ok": True,
                "tool_name": "fetch_day_stat",
                "args": {"match_date": normalized_match_date},
                "data": data,
                "error": None,
            }

        if normalized_query_type in {"dates", "match_dates", "available_dates"}:
            data = {"available_dates": fetch_match_dates()}
            return {
                "ok": True,
                "tool_name": "fetch_match_dates",
                "args": {"query_type": normalized_query_type},
                "data": data,
                "error": None,
            }

        data = fetch_match_list(page_num=page_num, page_size=page_size)
        data["available_dates"] = fetch_match_dates()
        return {
            "ok": True,
            "tool_name": "fetch_match_list",
            "args": {"page_num": page_num, "page_size": page_size},
            "data": data,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "tool_name": "volleyball_query_tool",
            "args": {
                "page_num": page_num,
                "page_size": page_size,
                "match_date": match_date,
                "query_type": query_type,
            },
            "data": None,
            "error": str(exc),
        }
