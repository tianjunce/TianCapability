from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import date as LocalDate
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from app.capabilities.get_weather.handler import handle
from app.capabilities.get_weather.weather_source import (
    ForecastBundle,
    ForecastDay,
    ResolvedCity,
    WeatherDateError,
    WeatherFetchError,
    _extract_weather_links,
    _load_cached_forecast_bundle,
    _parse_cma_forecast_html,
    _parse_legacy_forecast_html,
    _save_cached_forecast_bundle,
    build_weather_response,
    fetch_weather_forecast,
    load_cached_weather_forecast_for_city,
    resolve_city,
)


def _build_cma_html() -> str:
    daily_blocks = [
        ("星期一", "03/30", "小雨", "25", "13"),
        ("星期二", "03/31", "中雨", "17", "13"),
        ("星期三", "04/01", "多云", "20", "13"),
        ("星期四", "04/02", "多云", "23", "14"),
        ("星期五", "04/03", "大雨", "19", "14"),
        ("星期六", "04/04", "晴", "22", "12"),
        ("星期日", "04/05", "多云", "24", "15"),
    ]

    parts = [
        "<html><body>",
        "<div>杭州</div>",
        "<div>7天天气预报（2026/03/30 20:00发布）</div>",
    ]
    for weekday, display_date, weather, high, low in daily_blocks:
        parts.extend(
            [
                f"<div>{weekday}</div>",
                f"<div>{display_date}</div>",
                "<div>Image</div>",
                f"<div>{weather}</div>",
                "<div>西北风</div>",
                "<div>微风</div>",
                f"<div>{high}℃</div>",
                f"<div>{low}℃</div>",
                "<div>Image</div>",
                f"<div>{weather}</div>",
                "<div>北风</div>",
                "<div>微风</div>",
            ]
        )
    parts.extend(
        [
            "<div>时间 17:00 20:00 23:00</div>",
            "<div>天气 Image Image Image</div>",
            "<div>气温 18.6℃ 17.2℃ 16.1℃</div>",
            "<div>降水 无降水 无降水 无降水</div>",
            "</body></html>",
        ]
    )
    return "".join(parts)


def _build_legacy_html() -> str:
    return """
    <html>
      <body>
        <div id="7d" class="c7d">
          <input type="hidden" id="hidden_title" value="03月30日20时 周一  小雨转中雨  13/17°C" />
          <input type="hidden" id="fc_24h_internal_update_time" value="2026033020" />
          <ul class="t clearfix">
            <li class="sky skyid lv3 on">
              <h1>30日（今天）</h1>
              <p title="小雨" class="wea">小雨</p>
              <p class="tem">
                <i>13℃</i>
              </p>
            </li>
            <li class="sky skyid lv3">
              <h1>31日（明天）</h1>
              <p title="中雨转小雨" class="wea">中雨转小雨</p>
              <p class="tem">
                <span>17℃</span>/<i>13℃</i>
              </p>
            </li>
            <li class="sky skyid lv2">
              <h1>1日（后天）</h1>
              <p title="多云转晴" class="wea">多云转晴</p>
              <p class="tem">
                <span>20℃</span>/<i>13℃</i>
              </p>
            </li>
          </ul>
        </div>
      </body>
    </html>
    """


class CmaWeatherParsingTests(unittest.TestCase):
    def test_parse_cma_forecast_and_build_today_response(self) -> None:
        bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        payload = build_weather_response(
            city_name="杭州",
            requested_date="今天",
            forecast_bundle=bundle,
        )

        self.assertEqual(bundle.publish_date, LocalDate(2026, 3, 30))
        self.assertEqual(payload["matched_date"], "2026-03-30")
        self.assertEqual(payload["weather"]["weather"], "小雨")
        self.assertEqual(payload["weather"]["temp_current"], "17.2")
        self.assertEqual(payload["forecast_days"][0]["date"], "2026-03-30")

    def test_build_weather_response_supports_exact_date(self) -> None:
        bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        payload = build_weather_response(
            city_name="杭州",
            requested_date="2026-04-04",
            forecast_bundle=bundle,
        )

        self.assertEqual(payload["date"], "2026-04-04")
        self.assertEqual(payload["matched_date"], "2026-04-04")
        self.assertEqual(payload["weather"]["weather"], "晴")
        self.assertEqual(payload["weather"]["temp_high_day"], "22")
        self.assertIn("最高22°C", payload["summary"])

    def test_build_weather_response_supports_weekend_range(self) -> None:
        bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        payload = build_weather_response(
            city_name="杭州",
            requested_date="周末",
            forecast_bundle=bundle,
        )

        self.assertEqual(payload["matched_date"], "2026-04-04 ~ 2026-04-05")
        self.assertEqual(len(payload["forecast_days"]), 2)
        self.assertEqual(payload["forecast_days"][0]["date"], "2026-04-04")
        self.assertEqual(payload["forecast_days"][1]["date"], "2026-04-05")
        self.assertEqual(payload["weather"]["weather"], "晴 / 多云")

    def test_build_weather_response_supports_recent_days_range(self) -> None:
        bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        payload = build_weather_response(
            city_name="杭州",
            requested_date="最近几天",
            forecast_bundle=bundle,
        )

        self.assertEqual(payload["matched_date"], "2026-03-30 ~ 2026-04-01")
        self.assertEqual(len(payload["forecast_days"]), 3)
        self.assertEqual(payload["forecast_days"][0]["date"], "2026-03-30")
        self.assertEqual(payload["forecast_days"][-1]["date"], "2026-04-01")

    def test_build_weather_response_supports_this_week_range(self) -> None:
        bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        payload = build_weather_response(
            city_name="杭州",
            requested_date="这周",
            forecast_bundle=bundle,
        )

        self.assertEqual(payload["matched_date"], "2026-03-30 ~ 2026-04-05")
        self.assertEqual(len(payload["forecast_days"]), 7)

    def test_build_weather_response_supports_next_week_weekday(self) -> None:
        daily_forecasts = [
            ForecastDay(
                forecast_date=LocalDate(2026, 4, 11) + timedelta(days=offset),
                weekday_text=f"星期{offset}",
                display_date=(LocalDate(2026, 4, 11) + timedelta(days=offset)).strftime("%m/%d"),
                weather_day="多云",
                temp_high_day=str(20 + offset),
                temp_low_night=str(10 + offset),
            )
            for offset in range(7)
        ]
        bundle = ForecastBundle(
            city_code="58457",
            source="cma",
            publish_date=LocalDate(2026, 4, 11),
            daily_forecasts=daily_forecasts,
        )

        payload = build_weather_response(
            city_name="杭州",
            requested_date="下周二",
            forecast_bundle=bundle,
        )

        self.assertEqual(payload["date"], "下周二")
        self.assertEqual(payload["matched_date"], "2026-04-14")
        self.assertEqual(len(payload["forecast_days"]), 1)
        self.assertEqual(payload["forecast_days"][0]["date"], "2026-04-14")

    def test_build_weather_response_rejects_date_out_of_range(self) -> None:
        bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        with self.assertRaises(WeatherDateError) as context:
            build_weather_response(
                city_name="杭州",
                requested_date="下周末",
                forecast_bundle=bundle,
            )

        self.assertEqual(context.exception.code, "date_out_of_range")

    def test_build_weather_response_rejects_unsupported_date_expression(self) -> None:
        bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        with self.assertRaises(WeatherDateError) as context:
            build_weather_response(
                city_name="杭州",
                requested_date="今晚8点",
                forecast_bundle=bundle,
            )

        self.assertEqual(context.exception.code, "date_not_supported")

    def test_extract_weather_links_collects_city_detail_pages(self) -> None:
        html = """
        <html>
          <body>
            <a href="/web/weather/58457.html">杭州</a>
            <a href="/web/weather/58562.html">宁波市</a>
            <a href="/web/weather/58367.html">徐家汇</a>
            <a href="/web/text/HD/AZJ.html">浙江</a>
            <a href="/web/weather/99999.html">详情&gt;&gt;</a>
          </body>
        </html>
        """

        city_index = _extract_weather_links(html)

        self.assertEqual(city_index["杭州"], "https://weather.cma.cn/web/weather/58457.html")
        self.assertEqual(city_index["宁波"], "https://weather.cma.cn/web/weather/58562.html")
        self.assertEqual(city_index["徐家汇"], "https://weather.cma.cn/web/weather/58367.html")
        self.assertNotIn("浙江", city_index)

    def test_parse_legacy_forecast_html_from_real_dom_shape(self) -> None:
        bundle = _parse_legacy_forecast_html(html=_build_legacy_html(), city_code="101210101")

        self.assertEqual(bundle.publish_date, LocalDate(2026, 3, 30))
        self.assertEqual(len(bundle.daily_forecasts), 3)
        self.assertEqual(bundle.daily_forecasts[0].weather_day, "小雨转中雨")
        self.assertEqual(bundle.daily_forecasts[0].temp_high_day, "17")
        self.assertEqual(bundle.daily_forecasts[0].temp_low_night, "13")
        self.assertEqual(bundle.daily_forecasts[1].weather_day, "中雨转小雨")


class WeatherSourceFallbackTests(unittest.TestCase):
    def test_fetch_weather_forecast_falls_back_to_legacy_source(self) -> None:
        resolved_city = ResolvedCity(
            city_code="58457",
            source="cma",
            detail_url="https://weather.cma.cn/web/weather/58457.html",
            fallback_legacy_code="101210101",
        )
        fallback_bundle = ForecastBundle(
            city_code="101210101",
            source="weather.com.cn",
            publish_date=LocalDate(2026, 3, 30),
            daily_forecasts=[
                ForecastDay(
                    forecast_date=LocalDate(2026, 3, 30),
                    weekday_text="星期一",
                    display_date="03/30",
                    weather_day="晴",
                    temp_current="25",
                    temp_high_day="25",
                    temp_low_night="16",
                )
            ],
        )

        with patch(
            "app.capabilities.get_weather.weather_source._fetch_cma_forecast_by_url",
            side_effect=WeatherFetchError("blocked"),
        ), patch(
            "app.capabilities.get_weather.weather_source._fetch_legacy_forecast_by_code",
            return_value=fallback_bundle,
        ):
            result = fetch_weather_forecast(resolved_city)

        self.assertEqual(result.source, "weather.com.cn")
        self.assertEqual(result.city_code, "101210101")
        self.assertEqual(result.daily_forecasts[0].weather_day, "晴")

    def test_fetch_weather_forecast_does_not_cache_legacy_fallback(self) -> None:
        resolved_city = ResolvedCity(
            city_code="58457",
            source="cma",
            detail_url="https://weather.cma.cn/web/weather/58457.html",
            fallback_legacy_code="101210101",
        )
        fallback_bundle = ForecastBundle(
            city_code="101210101",
            source="weather.com.cn",
            publish_date=LocalDate(2026, 3, 30),
            daily_forecasts=[
                ForecastDay(
                    forecast_date=LocalDate(2026, 3, 30),
                    weekday_text="星期一",
                    display_date="03/30",
                    weather_day="晴",
                    temp_current="25",
                    temp_high_day="25",
                    temp_low_night="16",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ), patch(
                "app.capabilities.get_weather.weather_source._fetch_cma_forecast_by_url",
                side_effect=WeatherFetchError("blocked"),
            ), patch(
                "app.capabilities.get_weather.weather_source._fetch_legacy_forecast_by_code",
                return_value=fallback_bundle,
            ):
                result = fetch_weather_forecast(resolved_city)

        self.assertEqual(result.source, "weather.com.cn")
        self.assertFalse(cache_path.exists())

    def test_fetch_weather_forecast_uses_daily_cache(self) -> None:
        resolved_city = ResolvedCity(
            city_code="58457",
            source="cma",
            detail_url="https://weather.cma.cn/web/weather/58457.html",
        )
        cached_bundle = ForecastBundle(
            city_code="58457",
            source="cma",
            publish_date=LocalDate(2026, 3, 30),
            daily_forecasts=[
                ForecastDay(
                    forecast_date=LocalDate(2026, 3, 30),
                    weekday_text="星期一",
                    display_date="03/30",
                    weather_day="晴",
                    temp_current="25",
                    temp_high_day="25",
                    temp_low_night="16",
                ),
                ForecastDay(
                    forecast_date=LocalDate(2026, 3, 31),
                    weekday_text="星期二",
                    display_date="03/31",
                    weather_day="多云",
                    temp_current=None,
                    temp_high_day="23",
                    temp_low_night="15",
                ),
                ForecastDay(
                    forecast_date=LocalDate(2026, 4, 1),
                    weekday_text="星期三",
                    display_date="04/01",
                    weather_day="小雨",
                    temp_current=None,
                    temp_high_day="20",
                    temp_low_night="14",
                ),
                ForecastDay(
                    forecast_date=LocalDate(2026, 4, 2),
                    weekday_text="星期四",
                    display_date="04/02",
                    weather_day="阴",
                    temp_current=None,
                    temp_high_day="21",
                    temp_low_night="13",
                ),
                ForecastDay(
                    forecast_date=LocalDate(2026, 4, 3),
                    weekday_text="星期五",
                    display_date="04/03",
                    weather_day="多云",
                    temp_current=None,
                    temp_high_day="22",
                    temp_low_night="12",
                ),
                ForecastDay(
                    forecast_date=LocalDate(2026, 4, 4),
                    weekday_text="星期六",
                    display_date="04/04",
                    weather_day="晴",
                    temp_current=None,
                    temp_high_day="24",
                    temp_low_night="11",
                ),
                ForecastDay(
                    forecast_date=LocalDate(2026, 4, 5),
                    weekday_text="星期日",
                    display_date="04/05",
                    weather_day="晴",
                    temp_current=None,
                    temp_high_day="26",
                    temp_low_night="13",
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ), patch(
                "app.capabilities.get_weather.weather_source._current_weather_cache_scope_date",
                return_value=LocalDate(2026, 3, 30),
            ):
                _save_cached_forecast_bundle("https://weather.cma.cn/web/weather/58457.html", cached_bundle)
                with patch(
                    "app.capabilities.get_weather.weather_source._fetch_cma_forecast_by_url",
                    side_effect=AssertionError("should not fetch upstream when cache exists"),
                ):
                    result = fetch_weather_forecast(resolved_city)

        self.assertEqual(result.city_code, "58457")
        self.assertEqual(result.daily_forecasts[0].weather_day, "晴")

    def test_load_cached_weather_forecast_for_city_uses_city_alias_keys(self) -> None:
        resolved_city = ResolvedCity(
            city_code="58457",
            source="cma",
            detail_url="https://weather.cma.cn/web/weather/58457.html",
        )
        cached_bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ), patch(
                "app.capabilities.get_weather.weather_source._current_weather_cache_scope_date",
                return_value=LocalDate(2026, 3, 30),
            ), patch(
                "app.capabilities.get_weather.weather_source._fetch_cma_forecast_by_url",
                return_value=cached_bundle,
            ):
                fetch_weather_forecast(resolved_city, city_name="杭州市")
                result = load_cached_weather_forecast_for_city("杭州")

        self.assertIsNotNone(result)
        self.assertEqual(result.city_code, "58457")
        self.assertEqual(result.daily_forecasts[-1].forecast_date, LocalDate(2026, 4, 5))

    def test_load_cached_forecast_bundle_prunes_stale_entries(self) -> None:
        bundle = ForecastBundle(
            city_code="101210101",
            source="weather.com.cn",
            publish_date=LocalDate(2026, 3, 30),
            daily_forecasts=[
                ForecastDay(
                    forecast_date=LocalDate(2026, 3, 30),
                    weekday_text="星期一",
                    display_date="03/30",
                    weather_day="晴",
                    temp_current="25",
                    temp_high_day="25",
                    temp_low_night="16",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            stale_cache = {
                "101210101": {
                    "fetched_on": (LocalDate.today() - timedelta(days=1)).isoformat(),
                    "bundle": {
                        "city_code": bundle.city_code,
                        "source": bundle.source,
                        "publish_date": bundle.publish_date.isoformat(),
                        "daily_forecasts": [
                            {
                                "forecast_date": bundle.daily_forecasts[0].forecast_date.isoformat(),
                                "weekday_text": bundle.daily_forecasts[0].weekday_text,
                                "display_date": bundle.daily_forecasts[0].display_date,
                                "weather_day": bundle.daily_forecasts[0].weather_day,
                                "temp_high_day": bundle.daily_forecasts[0].temp_high_day,
                                "temp_low_night": bundle.daily_forecasts[0].temp_low_night,
                                "weather_night": bundle.daily_forecasts[0].weather_night,
                                "temp_current": bundle.daily_forecasts[0].temp_current,
                            }
                        ],
                    },
                }
            }
            cache_path.write_text(json.dumps(stale_cache, ensure_ascii=False), encoding="utf-8")

            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ):
                result = _load_cached_forecast_bundle("101210101")
                rewritten_cache = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertIsNone(result)
        self.assertEqual(rewritten_cache, {})

    def test_load_cached_forecast_bundle_prunes_previous_day_publish_after_midnight(self) -> None:
        stale_publish_bundle = ForecastBundle(
            city_code="58457",
            source="cma",
            publish_date=LocalDate(2026, 4, 10),
            daily_forecasts=[
                ForecastDay(
                    forecast_date=LocalDate(2026, 4, 10) + timedelta(days=offset),
                    weekday_text=f"星期{offset}",
                    display_date=(LocalDate(2026, 4, 10) + timedelta(days=offset)).strftime("%m/%d"),
                    weather_day="多云",
                    temp_current="20" if offset == 0 else None,
                    temp_high_day=str(25 + offset),
                    temp_low_night=str(15 + offset),
                )
                for offset in range(7)
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            cache_data = {
                "https://weather.cma.cn/web/weather/58457.html": {
                    "fetched_on": "2026-04-11",
                    "bundle": {
                        "city_code": stale_publish_bundle.city_code,
                        "source": stale_publish_bundle.source,
                        "publish_date": stale_publish_bundle.publish_date.isoformat(),
                        "daily_forecasts": [
                            {
                                "forecast_date": item.forecast_date.isoformat(),
                                "weekday_text": item.weekday_text,
                                "display_date": item.display_date,
                                "weather_day": item.weather_day,
                                "temp_high_day": item.temp_high_day,
                                "temp_low_night": item.temp_low_night,
                                "weather_night": item.weather_night,
                                "temp_current": item.temp_current,
                            }
                            for item in stale_publish_bundle.daily_forecasts
                        ],
                    },
                }
            }
            cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")

            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ), patch(
                "app.capabilities.get_weather.weather_source._current_weather_cache_scope_date",
                return_value=LocalDate(2026, 4, 11),
            ):
                result = _load_cached_forecast_bundle("https://weather.cma.cn/web/weather/58457.html")
                rewritten_cache = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertIsNone(result)
        self.assertEqual(rewritten_cache, {})

    def test_load_cached_forecast_bundle_prunes_legacy_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            cache_data = {
                "https://weather.cma.cn/web/weather/58457.html": {
                    "fetched_on": LocalDate.today().isoformat(),
                    "bundle": {
                        "city_code": "101210101",
                        "source": "weather.com.cn",
                        "publish_date": "2026-03-30",
                        "daily_forecasts": [
                            {
                                "forecast_date": "2026-03-30",
                                "weekday_text": "星期一",
                                "display_date": "03/30",
                                "weather_day": "晴",
                                "temp_high_day": "25",
                                "temp_low_night": "16",
                                "weather_night": None,
                                "temp_current": "25",
                            }
                        ],
                    },
                }
            }
            cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")

            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ):
                result = _load_cached_forecast_bundle("https://weather.cma.cn/web/weather/58457.html")
                rewritten_cache = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertIsNone(result)
        self.assertEqual(rewritten_cache, {})

    def test_handle_uses_city_cache_before_resolve_city(self) -> None:
        cached_bundle = _parse_cma_forecast_html(html=_build_cma_html(), city_code="58457")

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ), patch(
                "app.capabilities.get_weather.weather_source._current_weather_cache_scope_date",
                return_value=LocalDate(2026, 3, 30),
            ):
                _save_cached_forecast_bundle("city:杭州", cached_bundle)
                with patch(
                    "app.capabilities.get_weather.handler.resolve_city",
                    side_effect=AssertionError("resolve_city should not be called when city cache exists"),
                ):
                    payload = asyncio.run(handle({"city": "杭州市", "date": "周末"}, {}))

        self.assertEqual(payload["city_code"], "58457")
        self.assertEqual(payload["matched_date"], "2026-04-04 ~ 2026-04-05")
        self.assertEqual(payload["source"], "cma")

    def test_save_cached_forecast_bundle_skips_previous_day_publish_after_midnight(self) -> None:
        stale_publish_bundle = ForecastBundle(
            city_code="58457",
            source="cma",
            publish_date=LocalDate(2026, 4, 10),
            daily_forecasts=[
                ForecastDay(
                    forecast_date=LocalDate(2026, 4, 10) + timedelta(days=offset),
                    weekday_text=f"星期{offset}",
                    display_date=(LocalDate(2026, 4, 10) + timedelta(days=offset)).strftime("%m/%d"),
                    weather_day="多云",
                    temp_current="20" if offset == 0 else None,
                    temp_high_day=str(25 + offset),
                    temp_low_night=str(15 + offset),
                )
                for offset in range(7)
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "forecast-cache.json"
            with patch(
                "app.capabilities.get_weather.weather_source.WEATHER_FORECAST_CACHE_PATH",
                cache_path,
            ), patch(
                "app.capabilities.get_weather.weather_source.WEATHER_CACHE_DIR",
                cache_path.parent,
            ), patch(
                "app.capabilities.get_weather.weather_source._current_weather_cache_scope_date",
                return_value=LocalDate(2026, 4, 11),
            ):
                _save_cached_forecast_bundle(
                    "https://weather.cma.cn/web/weather/58457.html",
                    stale_publish_bundle,
                )

        self.assertFalse(cache_path.exists())

    def test_resolve_city_reports_fetch_error_when_cma_index_unavailable(self) -> None:
        with patch(
            "app.capabilities.get_weather.weather_source._find_cma_detail_url",
            return_value=None,
        ), patch(
            "app.capabilities.get_weather.weather_source._get_legacy_city_code",
            return_value=None,
        ), patch(
            "app.capabilities.get_weather.weather_source._CMA_CITY_URL_CACHE_AVAILABLE",
            False,
        ):
            with self.assertRaisesRegex(WeatherFetchError, "CMA城市索引请求被站点拦截"):
                resolve_city("宁波")


if __name__ == "__main__":
    unittest.main()
