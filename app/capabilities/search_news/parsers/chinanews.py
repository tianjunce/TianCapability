from __future__ import annotations

import re
from urllib.parse import quote

from .base import BaseNewsParser, NewsSearchResult
from .utils import extract_result_candidates_from_anchors, extract_result_candidates_from_json


CHINANEWS_ARTICLE_RE = re.compile(r"^https?://(?:[^/]+\.)?chinanews\.com\.cn/(?!search\.do)(?:[^?#]+)")


class ChinaNewsParser(BaseNewsParser):
    site_name = "中国新闻网"
    base_url = "https://www.chinanews.com.cn/"
    strategy_name = "search_page_then_detail"
    detail_summary_selectors = (
        ".left_zw p",
        ".content_desc p",
        ".article-content p",
        ".left_ph p",
        ".txt_c p",
        "article p",
    )
    detail_content_selectors = (
        ".left_zw p",
        ".content_desc p",
        ".article-content p",
        ".left_ph p",
        ".txt_c p",
        "article p",
    )

    def build_search_urls(self, query: str) -> list[str]:
        return [f"https://sou.chinanews.com.cn/search.do?q={quote(query)}"]

    def is_article_url(self, url: str) -> bool:
        return bool(CHINANEWS_ARTICLE_RE.match(url))

    def parse_page(self, *, html_text: str, page_url: str, query: str) -> list[NewsSearchResult]:
        raw_candidates = extract_result_candidates_from_anchors(
            html_text=html_text,
            base_url=page_url,
            site_name=self.site_name,
            is_article_url=self.is_article_url,
        )
        raw_candidates.extend(
            extract_result_candidates_from_json(
                html_text=html_text,
                base_url=page_url,
                site_name=self.site_name,
                is_article_url=self.is_article_url,
            )
        )
        return [self._build_result(candidate) for candidate in raw_candidates]
