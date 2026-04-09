from __future__ import annotations

from urllib.parse import quote

from .base import BaseNewsParser, NewsSearchResult
from .utils import extract_result_candidates_from_anchors, extract_result_candidates_from_json


class ToutiaoParser(BaseNewsParser):
    site_name = "今日头条"
    base_url = "https://www.toutiao.com/"
    strategy_name = "search_page_then_detail"
    detail_summary_selectors = (
        "article p",
        ".article-content p",
        ".tt-article-content p",
        ".main-content p",
    )

    def build_search_urls(self, query: str) -> list[str]:
        encoded_query = quote(query)
        return [
            (
                "https://so.toutiao.com/search"
                f"?source=search_subtab_switch&keyword={encoded_query}&enable_druid_v2=1"
                "&dvpf=pc&pd=information&action_type=search_subtab_switch&page_num=0"
                "&search_id=&from=news&cur_tab_title=news"
            )
        ]

    def is_article_url(self, url: str) -> bool:
        return url.startswith("http") and "so.toutiao.com" not in url and "toutiao.com" in url

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
