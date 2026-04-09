from __future__ import annotations

import re

from .base import BaseNewsParser, NewsSearchResult
from .utils import extract_result_candidates_from_anchors


ITHOME_ARTICLE_RE = re.compile(r"^https?://(?:www\.)?ithome\.com/\d+/\d+/\d+\.htm$")


class ITHomeParser(BaseNewsParser):
    site_name = "IT之家"
    base_url = "https://www.ithome.com/"
    detail_summary_selectors = (
        "#paragraph p",
        ".news-content p",
        ".post-content p",
        "article p",
    )

    def build_list_urls(self, query: str) -> list[str]:
        return [
            self.base_url,
            "https://next.ithome.com/",
        ]

    def is_article_url(self, url: str) -> bool:
        return bool(ITHOME_ARTICLE_RE.match(url))

    def parse_page(self, *, html_text: str, page_url: str, query: str) -> list[NewsSearchResult]:
        raw_candidates = extract_result_candidates_from_anchors(
            html_text=html_text,
            base_url=page_url,
            site_name=self.site_name,
            is_article_url=self.is_article_url,
        )
        return [self._build_result(candidate) for candidate in raw_candidates]
