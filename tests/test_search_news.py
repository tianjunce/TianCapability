from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.capabilities.search_news.handler import handle
from app.capabilities.search_news.parsers.base import NewsSearchResult, ParserError
from app.capabilities.search_news.parsers.chinanews import ChinaNewsParser
from app.capabilities.search_news.parsers.ifanr import IfanrParser
from app.capabilities.search_news.parsers.ifeng_ent import IfengEntertainmentParser
from app.capabilities.search_news.parsers.qq_news import QQNewsParser
from app.capabilities.search_news.parsers.sohu import SohuEntertainmentParser
from app.capabilities.search_news.search_client import normalize_top_k, search_news


class SearchNewsClientTests(unittest.TestCase):
    def test_normalize_top_k_bounds_value(self) -> None:
        self.assertEqual(normalize_top_k(None), 5)
        self.assertEqual(normalize_top_k("0"), 1)
        self.assertEqual(normalize_top_k("99"), 10)

    def test_search_news_routes_to_primary_parser(self) -> None:
        with patch(
            "app.capabilities.search_news.search_client.ChinaNewsParser.search",
            return_value=[
                NewsSearchResult(
                    title="OpenAI 发布新模型",
                    url="https://www.chinanews.com.cn/cj/2026/04-09/123456.shtml",
                    source="中国新闻网",
                    publish_time="2026-04-09 10:00",
                    summary="模型更新摘要",
                    content="这里是文章详情正文",
                )
            ],
        ):
            payload = search_news(query="OpenAI", category="news", top_k=5)

        self.assertEqual(payload["site"], "中国新闻网")
        self.assertFalse(payload["fallback_used"])
        self.assertIsNone(payload["error"])
        self.assertIn("已在中国新闻网完成", payload["result"])
        self.assertEqual(payload["results"][0]["content"], "这里是文章详情正文")
        self.assertEqual(payload["results"][0]["title"], "OpenAI 发布新模型")
        self.assertIsInstance(payload["debug"], dict)

    def test_search_news_falls_back_to_qq(self) -> None:
        with patch(
            "app.capabilities.search_news.search_client.IfanrParser.search",
            side_effect=ParserError("ifanr unavailable"),
        ), patch(
            "app.capabilities.search_news.search_client.QQNewsParser.search",
            return_value=[
                NewsSearchResult(
                    title="OpenAI 相关新闻",
                    url="https://news.qq.com/rain/a/20260409A00001",
                    source="腾讯新闻",
                    publish_time="2026-04-09 11:00",
                    summary="腾讯侧抓到的摘要",
                    content="腾讯新闻正文详情",
                )
            ],
        ):
            payload = search_news(query="OpenAI", category="tech", top_k=5)

        self.assertEqual(payload["site"], "腾讯新闻")
        self.assertTrue(payload["fallback_used"])
        self.assertIsNone(payload["error"])
        self.assertIn("已自动回退到腾讯新闻", payload["result"])
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["content"], "腾讯新闻正文详情")
        self.assertIsInstance(payload["debug"], dict)

    def test_search_news_routes_entertainment_to_sohu(self) -> None:
        with patch(
            "app.capabilities.search_news.search_client.SohuEntertainmentParser.search",
            return_value=[
                NewsSearchResult(
                    title="周杰伦专辑新动态",
                    url="https://www.sohu.com/a/987654321_121124372",
                    source="搜狐",
                    publish_time="2026-04-09 12:30",
                    summary="搜狐搜索结果摘要",
                    content="搜狐详情页正文内容",
                )
            ],
        ):
            payload = search_news(query="周杰伦专辑", category="entertainment", top_k=5)

        self.assertEqual(payload["site"], "搜狐")
        self.assertFalse(payload["fallback_used"])
        self.assertIsNone(payload["error"])
        self.assertIn("已在搜狐完成", payload["result"])
        self.assertEqual(payload["results"][0]["content"], "搜狐详情页正文内容")


class ParserTests(unittest.TestCase):
    def test_chinanews_parser_uses_exact_search_url(self) -> None:
        parser = ChinaNewsParser()
        urls = parser.build_search_urls("nasa")

        self.assertEqual(
            urls,
            [
                "https://sou.chinanews.com.cn/search.do?q=nasa",
            ],
        )

    def test_sohu_parser_uses_exact_search_url(self) -> None:
        parser = SohuEntertainmentParser()
        urls = parser.build_search_urls("周杰伦专辑")

        self.assertEqual(
            urls,
            [
                "https://search.sohu.com/?keyword=%E5%91%A8%E6%9D%B0%E4%BC%A6%E4%B8%93%E8%BE%91&type=10002&ie=utf8&queryType=default&spm=smpc.channel_217.search-box.17757178389800ZadonL_1125",
            ],
        )

    def test_sohu_search_uses_odin_api_then_detail(self) -> None:
        parser = SohuEntertainmentParser()

        class Response:
            def __init__(self, text: str = "", json_data=None) -> None:
                self.text = text
                self._json_data = json_data
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self) -> None:
                return None

            def json(self):  # noqa: ANN201
                return self._json_data

        detail_html = """
        <html>
          <body>
            <article>
              <p>搜狐娱乐详情正文第一段，长度足够。</p>
              <p>搜狐娱乐详情正文第二段，也会被提取。</p>
            </article>
          </body>
        </html>
        """

        class Session:
            def get(self, url: str, headers=None, timeout=None):  # noqa: ANN001
                if url.startswith("https://search.sohu.com/"):
                    return Response("<html><body><div id='search-page'></div></body></html>")
                if url == "https://www.sohu.com/a/987654321_121124372":
                    return Response(detail_html)
                raise AssertionError(f"unexpected GET {url}")

            def post(self, url: str, headers=None, json=None, timeout=None):  # noqa: ANN001
                self.post_url = url
                self.post_json = json
                return Response(
                    json_data={
                        "code": 0,
                        "data": {
                            "news-list": {
                                "list": [
                                    {
                                        "titleHL": "<em>金莎</em>结婚最新动态",
                                        "url": "https://www.sohu.com/a/987654321_121124372",
                                        "briefAlgHL": "搜狐搜索接口返回的<em>摘要</em>",
                                        "authorName": "搜狐娱乐",
                                        "postTime": "2026-04-09 12:00:00",
                                    }
                                ]
                            }
                        },
                    }
                )

        session = Session()
        results = parser.search(query="金莎 结婚", session=session, top_k=5, timeout=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://www.sohu.com/a/987654321_121124372")
        self.assertIn("详情正文第一段", results[0].content)
        self.assertEqual(results[0].source, "搜狐娱乐")
        self.assertEqual(parser.debug_info["strategy"], "search_page_and_api_then_detail")
        self.assertEqual(parser.debug_info["page_fetches"][1]["interface"], "odin_api")

    def test_ifanr_search_uses_algolia_then_detail(self) -> None:
        parser = IfanrParser()

        class Response:
            def __init__(self, text: str = "", json_data=None) -> None:
                self.text = text
                self._json_data = json_data
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self) -> None:
                return None

            def json(self):  # noqa: ANN201
                return self._json_data

        detail_html = """
        <html>
          <body>
            <article>
              <p>这是爱范儿详情正文第一段，长度足够。</p>
              <p>这是爱范儿详情正文第二段，也会被提取。</p>
            </article>
          </body>
        </html>
        """

        class Session:
            def get(self, url: str, headers=None, timeout=None):  # noqa: ANN001
                if url.startswith("https://www.ifanr.com/search?query="):
                    return Response("<html><body><div class='js-search-result'></div></body></html>")
                if url == "https://www.ifanr.com/1661343":
                    return Response(detail_html)
                raise AssertionError(f"unexpected GET {url}")

            def post(self, url: str, headers=None, json=None, timeout=None):  # noqa: ANN001
                self.post_url = url
                self.post_json = json
                return Response(
                    json_data={
                        "results": [
                            {
                                "hits": [
                                    {
                                        "ID": 1661343,
                                        "title": "OpenAI 与 小米手机",
                                        "pubDate": "2026-04-09 11:30:00",
                                        "content": "<p>搜索结果摘要里提到了小米手机和 OpenAI。</p>",
                                    }
                                ]
                            }
                        ]
                    }
                )

        session = Session()
        results = parser.search(query="小米手机", session=session, top_k=5, timeout=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://www.ifanr.com/1661343")
        self.assertIn("详情正文第一段", results[0].content)
        self.assertEqual(parser.debug_info["strategy"], "search_api_then_detail")
        self.assertEqual(parser.debug_info["page_fetches"][1]["interface"], "algolia_api")

    def test_ifeng_search_uses_jsonp_api(self) -> None:
        parser = IfengEntertainmentParser()

        class Response:
            def __init__(self, text: str) -> None:
                self.text = text
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self) -> None:
                return None

        detail_html = """
        <html>
          <body>
            <article>
              <p>凤凰娱乐详情正文第一段，长度足够。</p>
            </article>
          </body>
        </html>
        """

        class Session:
            def get(self, url: str, headers=None, timeout=None):  # noqa: ANN001
                if url.startswith("https://so.ifeng.com/"):
                    return Response("<html><body><div id='root'></div></body></html>")
                if url.startswith("https://d.shankapi.ifeng.com/api/getSoFengData/"):
                    return Response(
                        'getSoFengDataCallback({"code":0,"data":{"items":[{"title":"明星新动态","url":"https://ent.ifeng.com/c/8abcde","newsTime":"2026-04-09 09:20:00","summary":"搜索摘要"}]}})'
                    )
                if url == "https://ent.ifeng.com/c/8abcde":
                    return Response(detail_html)
                raise AssertionError(f"unexpected GET {url}")

        results = parser.search(query="明星", session=Session(), top_k=5, timeout=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "明星新动态")
        self.assertEqual(parser.debug_info["page_fetches"][1]["interface"], "jsonp_api")

    def test_qq_search_uses_json_api(self) -> None:
        parser = QQNewsParser()

        class Response:
            def __init__(self, text: str = "", json_data=None) -> None:
                self.text = text
                self._json_data = json_data
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self) -> None:
                return None

            def json(self):  # noqa: ANN201
                return self._json_data

        detail_html = """
        <html>
          <body>
            <article>
              <p>腾讯新闻详情正文第一段，长度足够。</p>
            </article>
          </body>
        </html>
        """

        class Session:
            def get(self, url: str, headers=None, params=None, timeout=None):  # noqa: ANN001
                if url.startswith("https://news.qq.com/search?query="):
                    return Response("<html><body><div id='root'></div></body></html>")
                if url == "https://i.news.qq.com/gw/pc_search/result":
                    return Response(
                        json_data={
                            "secList": [
                                {
                                    "newsList": [
                                        {
                                            "title": "腾讯新闻里的科技结果",
                                            "url": "https://view.inews.qq.com/a/20260409A00001",
                                            "time": "2026-04-09 12:00:00",
                                            "abstract": "搜索摘要",
                                            "source": "腾讯新闻",
                                        }
                                    ]
                                }
                            ]
                        }
                    )
                if url == "https://view.inews.qq.com/a/20260409A00001":
                    return Response(detail_html)
                raise AssertionError(f"unexpected GET {url}")

        results = parser.search(query="科技", session=Session(), top_k=5, timeout=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "腾讯新闻")
        self.assertEqual(parser.debug_info["page_fetches"][1]["interface"], "json_api")

    def test_parse_detail_page_returns_content_and_summary(self) -> None:
        html = """
        <html>
          <head>
            <meta name="description" content="这是一段摘要" />
          </head>
          <body>
            <article>
              <p>第一段正文内容，长度足够用于详情提取。</p>
              <p>第二段正文内容，也应该被拼接到 content 中。</p>
            </article>
            <time datetime="2026-04-09 08:00:00"></time>
          </body>
        </html>
        """

        parser = IfanrParser()
        content, summary, publish_time, source = parser.parse_detail_page(html_text=html)

        self.assertIn("第一段正文内容", content)
        self.assertIn("第二段正文内容", content)
        self.assertEqual(summary, "这是一段摘要")
        self.assertEqual(publish_time, "2026-04-09 08:00:00")
        self.assertEqual(source, "爱范儿")

    def test_ifanr_search_debug_shows_strategy(self) -> None:
        parser = IfanrParser()

        class Response:
            def __init__(self, text: str = "", json_data=None) -> None:
                self.text = text
                self._json_data = json_data
                self.encoding = "utf-8"
                self.apparent_encoding = "utf-8"

            def raise_for_status(self) -> None:
                return None

            def json(self):  # noqa: ANN201
                return self._json_data

        detail_html = """
        <html>
          <body>
            <article>
              <p>正文第一段，足够长。</p>
              <p>正文第二段，足够长。</p>
            </article>
          </body>
        </html>
        """
        responses = {
            "https://www.ifanr.com/search?query=OpenAI": Response("<html></html>"),
            "https://www.ifanr.com/1661343": Response(detail_html),
        }

        class Session:
            def get(self, url: str, headers=None, timeout=None):  # noqa: ANN001
                return responses[url]

            def post(self, url: str, headers=None, json=None, timeout=None):  # noqa: ANN001
                return Response(
                    json_data={
                        "results": [
                            {
                                "hits": [
                                    {
                                        "ID": 1661343,
                                        "title": "OpenAI 新动态",
                                        "pubDate": "2026-04-09 10:00:00",
                                        "content": "<p>搜索摘要</p>",
                                    }
                                ]
                            }
                        ]
                    }
                )

        results = parser.search(query="OpenAI", session=Session(), top_k=5, timeout=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(parser.debug_info["strategy"], "search_api_then_detail")
        self.assertEqual(parser.debug_info["deduped_count"], 1)
        self.assertTrue(parser.debug_info["detail_fetches"])


class SearchNewsHandlerTests(unittest.TestCase):
    def test_handle_returns_structured_payload(self) -> None:
        with patch(
            "app.capabilities.search_news.handler.search_news",
            return_value={
                "query": "OpenAI",
                "category": "tech",
                "site": "爱范儿",
                "result": "已在爱范儿完成“OpenAI”搜索，共整理 1 条结果。",
                "results": [
                    {
                        "title": "OpenAI 发布桌面助手",
                        "url": "https://www.ifanr.com/1661343",
                        "source": "爱范儿",
                        "publish_time": "2026-04-09 11:30",
                        "summary": "详情页前几段摘要",
                        "content": "详情页正文内容",
                    }
                ],
                "fallback_used": False,
                "debug": {
                    "primary": {
                        "parser": "IfanrParser",
                        "strategy": "search_api_then_detail"
                    },
                    "fallback": None
                },
                "error": None,
            },
        ):
            payload = asyncio.run(handle({"query": "OpenAI", "category": "tech", "top_k": 3}, {}))

        self.assertEqual(payload["site"], "爱范儿")
        self.assertIn("已在爱范儿完成", payload["result"])
        self.assertEqual(payload["results"][0]["content"], "详情页正文内容")
        self.assertEqual(payload["results"][0]["source"], "爱范儿")
        self.assertEqual(payload["debug"]["primary"]["strategy"], "search_api_then_detail")

    def test_handle_rejects_invalid_category(self) -> None:
        with self.assertRaisesRegex(Exception, "field 'category' must be one of"):
            asyncio.run(handle({"query": "OpenAI", "category": "finance"}, {}))


if __name__ == "__main__":
    unittest.main()
