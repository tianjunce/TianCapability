from __future__ import annotations

from datetime import datetime
from urllib.parse import quote
from uuid import uuid4

import requests

from .base import BaseNewsParser, DEFAULT_HEADERS, NewsSearchResult, ParserError
from .utils import (
    extract_result_candidates_from_anchors,
    extract_result_candidates_from_json,
    parse_publish_time,
    strip_html_tags,
)


SOHU_ODIN_SEARCH_API = "https://odin.sohu.com/odin/api/search/blockdata"


class SohuEntertainmentParser(BaseNewsParser):
    site_name = "搜狐"
    base_url = "https://www.sohu.com/"
    strategy_name = "search_page_and_api_then_detail"
    detail_summary_selectors = (
        ".article p",
        ".article-box p",
        ".text p",
        ".main-article p",
        ".article-content p",
        "article p",
    )
    detail_content_selectors = (
        ".article p",
        ".article-box p",
        ".text p",
        ".main-article p",
        ".article-content p",
        "article p",
    )

    def build_search_urls(self, query: str) -> list[str]:
        encoded_query = quote(query)
        return [
            "https://search.sohu.com/"
            f"?keyword={encoded_query}&type=10002&ie=utf8&queryType=default&spm=smpc.channel_217.search-box.17757178389800ZadonL_1125"
        ]

    def is_article_url(self, url: str) -> bool:
        normalized = str(url or "").strip().lower()
        return (
            normalized.startswith("http")
            and "sohu.com" in normalized
            and "search.sohu.com" not in normalized
            and "/search?" not in normalized
        )

    def parse_page(self, *, html_text: str, page_url: str, query: str) -> list[NewsSearchResult]:
        raw_candidates = extract_result_candidates_from_json(
            html_text=html_text,
            base_url=page_url,
            site_name=self.site_name,
            is_article_url=self.is_article_url,
        )
        raw_candidates.extend(
            extract_result_candidates_from_anchors(
                html_text=html_text,
                base_url=page_url,
                site_name=self.site_name,
                is_article_url=self.is_article_url,
            )
        )
        return [self._build_result(candidate) for candidate in raw_candidates]

    def search(
        self,
        *,
        query: str,
        session: requests.Session,
        top_k: int,
        timeout: int,
    ) -> list[NewsSearchResult]:
        search_urls = self.build_search_urls(query)
        self.debug_info = self._build_debug_info(
            query=query,
            search_urls=search_urls,
            list_urls=[],
        )

        raw_results: list[NewsSearchResult] = []
        page_url = search_urls[0]
        last_error: Exception | None = None

        try:
            response = session.get(page_url, headers=DEFAULT_HEADERS, timeout=timeout)
            response.raise_for_status()
            response.encoding = response.encoding or response.apparent_encoding or "utf-8"
            html_results = self.parse_page(html_text=response.text, page_url=page_url, query=query)
            raw_results.extend(html_results)
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "success",
                    "candidate_count": len(html_results),
                    "interface": "search_page",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "success",
                    "candidate_count": len(html_results),
                    "interface": "search_page",
                    "response_preview": self._preview_text(response.text),
                    "result_preview": self._preview_results(html_results),
                },
            )
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "search_page",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "search_page",
                },
            )

        for query_type in ("outside", "default", "edit"):
            payload = self._build_api_payload(query=query, query_type=query_type, top_k=top_k)
            headers = {
                **DEFAULT_HEADERS,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://search.sohu.com",
                "Referer": page_url,
            }
            try:
                response = session.post(
                    SOHU_ODIN_SEARCH_API,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                api_payload = response.json()
                api_candidates = self._parse_api_payload(api_payload)
                raw_results.extend(api_candidates)
                self.debug_info["page_fetches"].append(
                    {
                        "method": "POST",
                        "url": SOHU_ODIN_SEARCH_API,
                        "status": "success",
                        "candidate_count": len(api_candidates),
                        "interface": "odin_api",
                        "query_type": query_type,
                    }
                )
                self._log_console_event(
                    "page_fetch",
                    {
                        "method": "POST",
                        "url": SOHU_ODIN_SEARCH_API,
                        "status": "success",
                        "candidate_count": len(api_candidates),
                        "interface": "odin_api",
                        "query_type": query_type,
                        "request_preview": self._preview_json(payload),
                        "response_preview": self._preview_json(api_payload),
                        "result_preview": self._preview_results(api_candidates),
                    },
                )
                if api_candidates:
                    break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                self.debug_info["page_fetches"].append(
                    {
                        "method": "POST",
                        "url": SOHU_ODIN_SEARCH_API,
                        "status": "error",
                        "error": str(exc),
                        "candidate_count": 0,
                        "interface": "odin_api",
                        "query_type": query_type,
                    }
                )
                self._log_console_event(
                    "page_fetch",
                    {
                        "method": "POST",
                        "url": SOHU_ODIN_SEARCH_API,
                        "status": "error",
                        "error": str(exc),
                        "candidate_count": 0,
                        "interface": "odin_api",
                        "query_type": query_type,
                        "request_preview": self._preview_json(payload),
                    },
                )

        if not raw_results and last_error is not None:
            raise ParserError(str(last_error)) from last_error

        return self.finalize_results(
            raw_results=raw_results,
            query=query,
            top_k=top_k,
            session=session,
            timeout=timeout,
        )

    def _build_api_payload(self, *, query: str, query_type: str, top_k: int) -> dict[str, object]:
        size = str(max(top_k * 2, 10))
        return {
            "pvId": self._make_request_id(20),
            "pageId": self._make_request_id(16),
            "trans": None,
            "mainContent": {
                "productId": 1163,
                "productType": 13,
                "secureScore": 100,
                "categoryId": 47,
            },
            "resourceList": [
                {
                    "tplCompKey": "news-list",
                    "content": {
                        "productId": "20001",
                        "productType": "107",
                        "page": "1",
                        "size": size,
                        "spm": "search.news-list",
                        "requestId": self._make_request_id(16),
                    },
                    "context": {
                        "keyword": query,
                        "terminalType": "pc",
                        "domain": "sohu",
                        "queryType": query_type,
                    },
                }
            ],
        }

    def _parse_api_payload(self, payload: dict[str, object]) -> list[NewsSearchResult]:
        data = payload.get("data") if isinstance(payload, dict) else {}
        block: dict[str, object] = {}
        if isinstance(data, dict):
            block = data.get("news-list") if isinstance(data.get("news-list"), dict) else {}
            if not block:
                for value in data.values():
                    if isinstance(value, dict) and isinstance(value.get("list"), list):
                        block = value
                        break

        items = block.get("list") if isinstance(block, dict) else []
        results: list[NewsSearchResult] = []
        if not isinstance(items, list):
            return results

        for item in items:
            if not isinstance(item, dict):
                continue
            article_url = str(item.get("url") or "").strip()
            if not self.is_article_url(article_url):
                continue
            title = strip_html_tags(item.get("titleHL") or item.get("title") or item.get("newsTitle"))
            summary = strip_html_tags(item.get("briefAlgHL") or item.get("brief") or item.get("description"))
            source = strip_html_tags(item.get("authorName") or item.get("mediaName") or self.site_name)
            publish_time = self._format_publish_time(item.get("postTime") or item.get("publishTime") or item.get("date"))
            results.append(
                self._build_result(
                    {
                        "title": title,
                        "url": article_url,
                        "source": source,
                        "publish_time": publish_time,
                        "summary": summary,
                    }
                )
            )

        return results

    def _format_publish_time(self, value: object) -> str:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            try:
                return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            except (OverflowError, OSError, ValueError):
                return ""

        text = strip_html_tags(value)
        parsed = parse_publish_time(text)
        if parsed is not None:
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        return text

    def _make_request_id(self, length: int) -> str:
        token = uuid4().hex
        if len(token) >= length:
            return token[:length]
        return (token + uuid4().hex)[:length]
