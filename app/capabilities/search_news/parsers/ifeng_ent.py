from __future__ import annotations

import re
from urllib.parse import quote

import requests

from .base import BaseNewsParser, DEFAULT_HEADERS, NewsSearchResult, ParserError
from .utils import extract_result_candidates_from_anchors, extract_result_candidates_from_json, parse_jsonp_payload


IFENG_ARTICLE_RE = re.compile(r"^https?://(?:ent|v)\.ifeng\.com/(?:c|a)/")
IFENG_SEARCH_API_TEMPLATE = "https://d.shankapi.ifeng.com/api/getSoFengData/all/{query}/1/getSoFengDataCallback"


class IfengEntertainmentParser(BaseNewsParser):
    site_name = "凤凰娱乐"
    base_url = "https://ent.ifeng.com/"
    strategy_name = "search_page_and_jsonp_then_detail"
    detail_summary_selectors = (
        ".main_content p",
        ".article-content p",
        ".text-3xl p",
        "article p",
    )

    def build_search_urls(self, query: str) -> list[str]:
        return [f"https://so.ifeng.com/?q={quote(query)}&c=1"]

    def is_article_url(self, url: str) -> bool:
        return bool(IFENG_ARTICLE_RE.match(url))

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

        api_url = IFENG_SEARCH_API_TEMPLATE.format(query=quote(query))
        try:
            response = session.get(api_url, headers=DEFAULT_HEADERS, timeout=timeout)
            response.raise_for_status()
            payload = parse_jsonp_payload(response.text)
            items = ((payload.get("data") or {}).get("items") or [])
            api_candidates = []
            for item in items:
                article_url = item.get("url") or item.get("shareUrl")
                if not self.is_article_url(str(article_url or "")):
                    continue
                api_candidates.append(
                    self._build_result(
                        {
                            "title": item.get("title"),
                            "url": article_url,
                            "source": item.get("source") or self.site_name,
                            "publish_time": item.get("newsTime") or item.get("time"),
                            "summary": item.get("summary") or item.get("desc"),
                        }
                    )
                )
            raw_results.extend(api_candidates)
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": api_url,
                    "status": "success",
                    "candidate_count": len(api_candidates),
                    "interface": "jsonp_api",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": api_url,
                    "status": "success",
                    "candidate_count": len(api_candidates),
                    "interface": "jsonp_api",
                    "request_preview": self._preview_json({"url": api_url}),
                    "response_preview": self._preview_json(payload),
                    "result_preview": self._preview_results(api_candidates),
                },
            )
        except (requests.RequestException, ValueError) as exc:
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": api_url,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "jsonp_api",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": api_url,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "jsonp_api",
                    "request_preview": self._preview_json({"url": api_url}),
                },
            )
            if not raw_results:
                raise ParserError(str(exc)) from exc

        return self.finalize_results(
            raw_results=raw_results,
            query=query,
            top_k=top_k,
            session=session,
            timeout=timeout,
        )
