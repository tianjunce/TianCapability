from __future__ import annotations

import re
from urllib.parse import quote

import requests

from .base import BaseNewsParser, DEFAULT_HEADERS, NewsSearchResult, ParserError
from .utils import strip_html_tags


IFANR_ARTICLE_RE = re.compile(r"^https?://(?:www\.)?ifanr\.com/\d{5,}(?:[/?#].*)?$")
ALGOLIA_ENDPOINT = "https://7TN0U2FL3Q-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": "7TN0U2FL3Q",
    "X-Algolia-API-Key": "97d5967e87b92827fa8b040bcc4c8581",
    "Content-Type": "application/json",
}
ALGOLIA_INDEX_NAME = "prod_ifanrcom"


class IfanrParser(BaseNewsParser):
    site_name = "爱范儿"
    base_url = "https://www.ifanr.com/"
    strategy_name = "search_api_then_detail"
    detail_summary_selectors = (
        "article p",
        ".article-content p",
        ".content p",
    )
    detail_content_selectors = (
        "article p",
        ".article-content p",
        ".content p",
    )

    def build_search_urls(self, query: str) -> list[str]:
        return [f"https://www.ifanr.com/search?query={quote(query)}"]

    def is_article_url(self, url: str) -> bool:
        return bool(IFANR_ARTICLE_RE.match(url))

    def parse_page(self, *, html_text: str, page_url: str, query: str) -> list[NewsSearchResult]:
        return []

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
        try:
            response = session.get(page_url, headers=DEFAULT_HEADERS, timeout=timeout)
            response.raise_for_status()
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "success",
                    "candidate_count": 0,
                    "interface": "search_page",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "success",
                    "candidate_count": 0,
                    "interface": "search_page",
                    "response_preview": self._preview_text(response.text),
                },
            )
        except requests.RequestException as exc:
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

        api_payload = {
            "requests": [
                {
                    "indexName": ALGOLIA_INDEX_NAME,
                    "params": f"query={quote(query)}&hitsPerPage={max(top_k * 2, 8)}&page=0",
                }
            ]
        }

        try:
            response = session.post(
                ALGOLIA_ENDPOINT,
                headers={**DEFAULT_HEADERS, **ALGOLIA_HEADERS},
                json=api_payload,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            hits = ((payload.get("results") or [{}])[0].get("hits") or [])
            for hit in hits:
                url = f"https://www.ifanr.com/{hit.get('ID')}" if hit.get("ID") else ""
                if not self.is_article_url(url):
                    continue
                raw_results.append(
                    self._build_result(
                        {
                            "title": hit.get("title"),
                            "url": url,
                            "source": self.site_name,
                            "publish_time": hit.get("pubDate"),
                            "summary": strip_html_tags(hit.get("content"))[:180],
                            "content": "",
                        }
                    )
                )
            self.debug_info["page_fetches"].append(
                {
                    "method": "POST",
                    "url": ALGOLIA_ENDPOINT,
                    "status": "success",
                    "candidate_count": len(raw_results),
                    "interface": "algolia_api",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "POST",
                    "url": ALGOLIA_ENDPOINT,
                    "status": "success",
                    "candidate_count": len(raw_results),
                    "interface": "algolia_api",
                    "request_preview": self._preview_json(api_payload),
                    "response_preview": self._preview_json(payload),
                    "result_preview": self._preview_results(raw_results),
                },
            )
        except (requests.RequestException, ValueError) as exc:
            self.debug_info["page_fetches"].append(
                {
                    "method": "POST",
                    "url": ALGOLIA_ENDPOINT,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "algolia_api",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "POST",
                    "url": ALGOLIA_ENDPOINT,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "algolia_api",
                    "request_preview": self._preview_json(api_payload),
                },
            )
            raise ParserError(str(exc)) from exc

        return self.finalize_results(
            raw_results=raw_results,
            query=query,
            top_k=top_k,
            session=session,
            timeout=timeout,
        )
