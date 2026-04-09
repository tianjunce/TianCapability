from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from .utils import (
    absolutize_url,
    clean_text,
    clean_multiline_text,
    compute_relevance,
    extract_detail_content,
    extract_detail_summary,
    extract_meta_content,
    parse_publish_time,
)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class ParserError(Exception):
    pass


@dataclass
class NewsSearchResult:
    title: str
    url: str
    source: str
    publish_time: str
    summary: str
    content: str = ""
    published_at: datetime | None = None
    relevance_score: float = field(default=0.0)

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "publish_time": self.publish_time,
            "summary": self.summary,
            "content": self.content,
        }


class BaseNewsParser:
    site_name = ""
    base_url = ""
    detail_summary_selectors: tuple[str, ...] = ()
    detail_content_selectors: tuple[str, ...] = ()
    strategy_name = "page_scrape_then_detail"

    def __init__(self) -> None:
        self.debug_info: dict[str, Any] = {}

    def build_search_urls(self, query: str) -> list[str]:
        return []

    def build_list_urls(self, query: str) -> list[str]:
        return []

    def is_article_url(self, url: str) -> bool:
        return True

    def parse_page(self, *, html_text: str, page_url: str, query: str) -> list[NewsSearchResult]:
        raise NotImplementedError

    def search(
        self,
        *,
        query: str,
        session: requests.Session,
        top_k: int,
        timeout: int,
    ) -> list[NewsSearchResult]:
        search_urls = self.build_search_urls(query)
        list_urls = self.build_list_urls(query)
        page_urls = search_urls
        raw_results: list[NewsSearchResult] = []
        last_error: Exception | None = None
        self.debug_info = self._build_debug_info(
            query=query,
            search_urls=search_urls,
            list_urls=list_urls,
        )

        for page_url in page_urls:
            try:
                response = session.get(page_url, headers=DEFAULT_HEADERS, timeout=timeout)
                response.raise_for_status()
                response.encoding = response.encoding or response.apparent_encoding or "utf-8"
                parsed_items = self.parse_page(html_text=response.text, page_url=page_url, query=query)
                raw_results.extend(parsed_items)
                self.debug_info["page_fetches"].append(
                    {
                        "method": "GET",
                        "interface": "search_page",
                        "url": page_url,
                        "status": "success",
                        "candidate_count": len(parsed_items),
                    }
                )
                self._log_console_event(
                    "page_fetch",
                    {
                        "method": "GET",
                        "interface": "search_page",
                        "url": page_url,
                        "status": "success",
                        "candidate_count": len(parsed_items),
                        "response_preview": self._preview_text(response.text),
                        "result_preview": self._preview_results(parsed_items),
                    },
                )
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                self.debug_info["page_fetches"].append(
                    {
                        "method": "GET",
                        "interface": "search_page",
                        "url": page_url,
                        "status": "error",
                        "error": str(exc),
                        "candidate_count": 0,
                    }
                )
                self._log_console_event(
                    "page_fetch",
                    {
                        "method": "GET",
                        "interface": "search_page",
                        "url": page_url,
                        "status": "error",
                        "error": str(exc),
                        "candidate_count": 0,
                    },
                )
                continue

        if not raw_results and last_error is not None:
            raise ParserError(str(last_error)) from last_error

        return self.finalize_results(
            raw_results=raw_results,
            query=query,
            top_k=top_k,
            session=session,
            timeout=timeout,
        )

    def _build_debug_info(
        self,
        *,
        query: str,
        search_urls: list[str],
        list_urls: list[str],
    ) -> dict[str, Any]:
        return {
            "parser": type(self).__name__,
            "site": self.site_name,
            "strategy": self.strategy_name,
            "query": query,
            "search_urls": search_urls,
            "list_urls": list_urls,
            "page_fetches": [],
            "detail_fetches": [],
            "raw_count": 0,
            "deduped_count": 0,
            "returned_count": 0,
            "ranked_preview": [],
        }

    def _preview_text(self, value: Any, max_chars: int = 400) -> str:
        text = clean_multiline_text(value)
        if not text:
            return ""
        return text[:max_chars]

    def _preview_json(self, value: Any, max_chars: int = 600) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
        return self._preview_text(text, max_chars=max_chars)

    def _preview_results(self, results: list[NewsSearchResult], limit: int = 3) -> list[dict[str, str]]:
        preview: list[dict[str, str]] = []
        for item in results[:limit]:
            preview.append(
                {
                    "title": item.title,
                    "url": item.url,
                    "publish_time": item.publish_time,
                    "summary": self._preview_text(item.summary, max_chars=120),
                }
            )
        return preview

    def _log_console_event(self, event: str, payload: dict[str, Any]) -> None:
        pass
        # message = {
        #     "event": event,
        #     "parser": type(self).__name__,
        #     "site": self.site_name,
        #     **payload,
        # }
        # print(f"[search_news] {json.dumps(message, ensure_ascii=False)}", flush=True)

    def finalize_results(
        self,
        *,
        raw_results: list[NewsSearchResult],
        query: str,
        top_k: int,
        session: requests.Session,
        timeout: int,
    ) -> list[NewsSearchResult]:
        if not raw_results:
            return []

        self.debug_info["raw_count"] = len(raw_results)
        candidates = self._dedupe(raw_results)
        self.debug_info["deduped_count"] = len(candidates)
        ranked = self._rank(results=candidates, query=query)
        candidates_to_enrich = ranked[: max(top_k * 2, 8)]
        self._enrich(candidates=candidates_to_enrich, session=session, timeout=timeout)
        reranked = self._rank(results=candidates_to_enrich, query=query)
        self.debug_info["returned_count"] = min(len(reranked), top_k)
        self.debug_info["ranked_preview"] = [
            {
                "title": item.title,
                "url": item.url,
                "publish_time": item.publish_time,
                "relevance_score": round(item.relevance_score, 3),
            }
            for item in reranked[: min(len(reranked), 5)]
        ]
        return reranked[:top_k]

    def _enrich(self, *, candidates: list[NewsSearchResult], session: requests.Session, timeout: int) -> None:
        for candidate in candidates:
            if candidate.content and candidate.summary and candidate.publish_time:
                continue

            try:
                response = session.get(candidate.url, headers=DEFAULT_HEADERS, timeout=timeout)
                response.raise_for_status()
                response.encoding = response.encoding or response.apparent_encoding or "utf-8"
            except requests.RequestException:
                self.debug_info.setdefault("detail_fetches", []).append(
                    {
                        "title": candidate.title,
                        "url": candidate.url,
                        "status": "error",
                    }
                )
                self._log_console_event(
                    "detail_fetch",
                    {
                        "title": candidate.title,
                        "url": candidate.url,
                        "status": "error",
                    },
                )
                continue

            content, summary, publish_time, source = self.parse_detail_page(html_text=response.text)
            self.debug_info.setdefault("detail_fetches", []).append(
                {
                    "title": candidate.title,
                    "url": candidate.url,
                    "status": "success",
                    "publish_time": publish_time,
                    "content_length": len(content or ""),
                    "summary_length": len(summary or ""),
                }
            )
            self._log_console_event(
                "detail_fetch",
                {
                    "title": candidate.title,
                    "url": candidate.url,
                    "status": "success",
                    "publish_time": publish_time,
                    "content_length": len(content or ""),
                    "summary_length": len(summary or ""),
                    "summary": summary,
                    "content": content,
                },
            )
            if content and len(content) > len(candidate.content):
                candidate.content = content
            if summary and len(summary) > len(candidate.summary):
                candidate.summary = summary
            if publish_time and not candidate.publish_time:
                candidate.publish_time = publish_time
                candidate.published_at = parse_publish_time(publish_time)
            if source and not candidate.source:
                candidate.source = source

    def parse_detail_page(self, *, html_text: str) -> tuple[str, str, str, str]:
        soup = BeautifulSoup(html_text, "html.parser")
        selectors = self.detail_content_selectors or self.detail_summary_selectors
        content = extract_detail_content(soup, selectors)

        summary = extract_meta_content(soup, ("description", "og:description"))
        if not summary:
            summary = extract_detail_summary(soup, self.detail_summary_selectors or selectors)
        if not summary and content:
            summary = clean_text(content[:180])

        publish_time = extract_meta_content(
            soup,
            ("article:published_time", "publishdate", "pubdate", "og:release_date", "date"),
        )
        if not publish_time:
            time_tag = soup.find("time")
            if time_tag is not None:
                publish_time = clean_text(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))

        source = extract_meta_content(soup, ("source", "og:site_name")) or self.site_name
        return content, summary, publish_time, source

    def _dedupe(self, results: list[NewsSearchResult]) -> list[NewsSearchResult]:
        deduped: list[NewsSearchResult] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        for result in results:
            result.title = clean_text(result.title)
            result.url = absolutize_url(result.url, self.base_url)
            result.summary = clean_text(result.summary)
            result.content = clean_multiline_text(result.content)
            result.source = clean_text(result.source) or self.site_name
            result.publish_time = clean_text(result.publish_time)
            result.published_at = parse_publish_time(result.publish_time)

            if not result.title or not result.url:
                continue

            normalized_title = result.title.lower()
            if result.url in seen_urls or normalized_title in seen_titles:
                continue

            seen_urls.add(result.url)
            seen_titles.add(normalized_title)
            deduped.append(result)

        return deduped

    def _rank(self, *, results: list[NewsSearchResult], query: str) -> list[NewsSearchResult]:
        for result in results:
            result.relevance_score = compute_relevance(
                query=query,
                title=result.title,
                summary=f"{result.summary} {result.content}",
            )

        positive_results = [result for result in results if result.relevance_score > 0]
        sortable = positive_results or results

        return sorted(
            sortable,
            key=lambda item: (
                item.relevance_score,
                item.published_at or datetime.min,
                item.title,
            ),
            reverse=True,
        )

    def _build_result(self, payload: dict[str, Any]) -> NewsSearchResult:
        publish_time = clean_text(payload.get("publish_time"))
        return NewsSearchResult(
            title=clean_text(payload.get("title")),
            url=clean_text(payload.get("url")),
            source=clean_text(payload.get("source")) or self.site_name,
            publish_time=publish_time,
            summary=clean_text(payload.get("summary")),
            content=clean_multiline_text(payload.get("content")),
            published_at=parse_publish_time(publish_time),
        )
