from __future__ import annotations

from typing import Any

import requests

from .parsers import ChinaNewsParser, IfanrParser, ParserError, QQNewsParser, SohuEntertainmentParser


DEFAULT_TOP_K = 5
MAX_TOP_K = 10
REQUEST_TIMEOUT_SECONDS = 8


CATEGORY_TO_PARSER = {
    "news": ChinaNewsParser,
    "tech": IfanrParser,
    "entertainment": SohuEntertainmentParser,
    "other": QQNewsParser,
}


def normalize_top_k(value: Any, default: int = DEFAULT_TOP_K) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, MAX_TOP_K))


def normalize_category(value: Any) -> str:
    category = str(value or "").strip().lower()
    if category not in CATEGORY_TO_PARSER:
        raise ValueError("field 'category' must be one of: news, tech, entertainment, other")
    return category


def _run_parser(
    *,
    parser: Any,
    query: str,
    top_k: int,
    session: requests.Session,
) -> tuple[list[dict[str, str]], str | None, dict[str, Any]]:
    try:
        results = parser.search(
            query=query,
            session=session,
            top_k=top_k,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return [item.to_dict() for item in results], None, dict(getattr(parser, "debug_info", {}) or {})
    except (ParserError, requests.RequestException) as exc:
        debug_info = dict(getattr(parser, "debug_info", {}) or {})
        debug_info.setdefault("error", str(exc))
        return [], str(exc), debug_info


def search_news(
    query: str,
    category: str,
    top_k: int = DEFAULT_TOP_K,
    *,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("field 'query' is required")

    normalized_category = normalize_category(category)
    normalized_top_k = normalize_top_k(top_k)
    should_close_session = session is None
    session = session or requests.Session()

    try:
        primary_parser = CATEGORY_TO_PARSER[normalized_category]()
        results, primary_error, primary_debug = _run_parser(
            parser=primary_parser,
            query=normalized_query,
            top_k=normalized_top_k,
            session=session,
        )

        if results or normalized_category == "other":
            result_text = _build_result_text(
                query=normalized_query,
                site=primary_parser.site_name,
                results=results[:normalized_top_k],
                fallback_used=False,
            )
            return {
                "query": normalized_query,
                "category": normalized_category,
                "site": primary_parser.site_name,
                "result": result_text,
                "results": results[:normalized_top_k],
                "fallback_used": False,
                "error": None if results else primary_error,
                "debug": {
                    "primary": primary_debug,
                    "fallback": None,
                },
            }

        fallback_parser = QQNewsParser()
        fallback_results, fallback_error, fallback_debug = _run_parser(
            parser=fallback_parser,
            query=normalized_query,
            top_k=normalized_top_k,
            session=session,
        )

        result_text = _build_result_text(
            query=normalized_query,
            site=fallback_parser.site_name,
            results=fallback_results[:normalized_top_k],
            fallback_used=True,
        )
        return {
            "query": normalized_query,
            "category": normalized_category,
            "site": fallback_parser.site_name,
            "result": result_text,
            "results": fallback_results[:normalized_top_k],
            "fallback_used": True,
            "error": None if fallback_results else (fallback_error or primary_error or "no results"),
            "debug": {
                "primary": primary_debug,
                "fallback": fallback_debug,
            },
        }
    finally:
        if should_close_session:
            session.close()


def _build_result_text(
    *,
    query: str,
    site: str,
    results: list[dict[str, str]],
    fallback_used: bool,
) -> str:
    if not results:
        if fallback_used:
            return f"已完成“{query}”搜索，但主站与腾讯新闻兜底都没有返回有效结果。"
        return f"已完成“{query}”搜索，但没有找到有效结果。"

    preview = "；".join(item["title"] for item in results[:2] if str(item.get("title") or "").strip())
    fallback_suffix = "，已自动回退到腾讯新闻" if fallback_used else ""
    if preview:
        return f"已在{site}完成“{query}”搜索{fallback_suffix}，共整理 {len(results)} 条结果。前几条：{preview}。"
    return f"已在{site}完成“{query}”搜索{fallback_suffix}，共整理 {len(results)} 条结果。"
