from __future__ import annotations

import re
from urllib.parse import quote

import requests

from .base import BaseNewsParser, DEFAULT_HEADERS, NewsSearchResult, ParserError
from .utils import extract_result_candidates_from_anchors, extract_result_candidates_from_json


QQ_ARTICLE_RE = re.compile(r"^https?://(?:(?:news|new)\.qq\.com/(?:rain/a|omn/|rz/|.*?/a/)|view\.inews\.qq\.com/a/)")
QQ_SEARCH_API = "https://i.news.qq.com/gw/pc_search/result"


class QQNewsParser(BaseNewsParser):
    site_name = "腾讯新闻"
    base_url = "https://news.qq.com/"
    strategy_name = "search_api_then_detail"
    detail_summary_selectors = (
        ".article-content p",
        ".content-article p",
        "article p",
    )

    def build_search_urls(self, query: str) -> list[str]:
        return [f"https://news.qq.com/search?query={quote(query)}&page=1"]

    def is_article_url(self, url: str) -> bool:
        return bool(QQ_ARTICLE_RE.match(url))

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

        page_url = search_urls[0]
        try:
            response = session.get(page_url, headers=DEFAULT_HEADERS, timeout=timeout)
            response.raise_for_status()
            response.encoding = response.encoding or response.apparent_encoding or "utf-8"
            shell_results = self.parse_page(html_text=response.text, page_url=page_url, query=query)
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "success",
                    "candidate_count": len(shell_results),
                    "interface": "search_page",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": page_url,
                    "status": "success",
                    "candidate_count": len(shell_results),
                    "interface": "search_page",
                    "response_preview": self._preview_text(response.text),
                    "result_preview": self._preview_results(shell_results),
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

        params = {
            "page": "0",
            "query": query,
            "is_pc": "1",
            "search_type": "all",
            "search_count_limit": str(max(top_k * 2, 8)),
            "appver": "15.5_qqnews_7.1.80",
        }

        try:
            response = session.get(
                QQ_SEARCH_API,
                headers={**DEFAULT_HEADERS, "Referer": page_url},
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            raw_results: list[NewsSearchResult] = []
            for section in payload.get("secList") or []:
                for item in section.get("newsList") or []:
                    article_url = item.get("url") or item.get("surl") or item.get("short_url")
                    if not self.is_article_url(str(article_url or "")):
                        continue
                    raw_results.append(
                        self._build_result(
                            {
                                "title": item.get("title") or item.get("longtitle"),
                                "url": article_url,
                                "source": item.get("source") or ((item.get("card") or {}).get("chlname")) or self.site_name,
                                "publish_time": item.get("time"),
                                "summary": item.get("abstract") or item.get("nlpAbstract"),
                            }
                        )
                    )
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": QQ_SEARCH_API,
                    "status": "success",
                    "candidate_count": len(raw_results),
                    "interface": "json_api",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": QQ_SEARCH_API,
                    "status": "success",
                    "candidate_count": len(raw_results),
                    "interface": "json_api",
                    "request_preview": self._preview_json(
                        {
                            "url": QQ_SEARCH_API,
                            "params": params,
                            "headers": {"Referer": page_url},
                        }
                    ),
                    "response_preview": self._preview_json(payload),
                    "result_preview": self._preview_results(raw_results),
                },
            )
        except (requests.RequestException, ValueError) as exc:
            self.debug_info["page_fetches"].append(
                {
                    "method": "GET",
                    "url": QQ_SEARCH_API,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "json_api",
                }
            )
            self._log_console_event(
                "page_fetch",
                {
                    "method": "GET",
                    "url": QQ_SEARCH_API,
                    "status": "error",
                    "error": str(exc),
                    "candidate_count": 0,
                    "interface": "json_api",
                    "request_preview": self._preview_json(
                        {
                            "url": QQ_SEARCH_API,
                            "params": params,
                            "headers": {"Referer": page_url},
                        }
                    ),
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
