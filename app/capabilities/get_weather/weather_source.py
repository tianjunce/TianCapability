from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import date as LocalDate
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.capabilities.get_weather.city_codes import CITY_CODE_MAP


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

CMA_BASE_URL = "https://weather.cma.cn"
CMA_AREA_URL = f"{CMA_BASE_URL}/web/text/area.html"
CMA_INDEX_TTL_SECONDS = 6 * 60 * 60

CMA_HEADERS = {
    "User-Agent": UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://weather.cma.cn/",
    "Upgrade-Insecure-Requests": "1",
}

WEATHER_WORDS = {
    "晴",
    "多云",
    "阴",
    "小雨",
    "中雨",
    "大雨",
    "暴雨",
    "阵雨",
    "雷阵雨",
    "雷阵雨伴有冰雹",
    "小雪",
    "中雪",
    "大雪",
    "暴雪",
    "雨夹雪",
    "冻雨",
    "雾",
    "霾",
    "沙尘",
    "浮尘",
    "扬沙",
    "强沙尘暴",
}

WEEKDAY_NAME_MAP = {
    0: "周一",
    1: "周二",
    2: "周三",
    3: "周四",
    4: "周五",
    5: "周六",
    6: "周日",
}

WEEKDAY_TOKEN_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

CITY_SUFFIXES = (
    "自治县",
    "自治州",
    "地区",
    "新区",
    "开发区",
    "高新区",
    "市",
    "区",
    "县",
    "旗",
    "盟",
)

_CMA_CITY_URL_CACHE: dict[str, str] = {}
_CMA_CITY_URL_CACHE_LOADED_AT = 0.0
_CMA_CITY_URL_CACHE_LOCK = threading.Lock()
_CMA_CITY_URL_CACHE_AVAILABLE: bool | None = None

WEATHER_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
WEATHER_FORECAST_CACHE_PATH = WEATHER_CACHE_DIR / "forecast-cache.json"
_WEATHER_FORECAST_CACHE_LOCK = threading.Lock()


class WeatherFetchError(RuntimeError):
    """Raised when the upstream weather source cannot be fetched."""


class WeatherParseError(RuntimeError):
    """Raised when the upstream weather source format cannot be parsed."""


class WeatherDateError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResolvedCity:
    city_code: str
    source: str
    detail_url: str | None = None
    fallback_legacy_code: str | None = None


@dataclass(frozen=True)
class ForecastDay:
    forecast_date: LocalDate
    weekday_text: str
    display_date: str
    weather_day: str
    temp_high_day: str
    temp_low_night: str
    weather_night: str | None = None
    temp_current: str | None = None


@dataclass(frozen=True)
class ForecastBundle:
    city_code: str
    source: str
    publish_date: LocalDate
    daily_forecasts: list[ForecastDay]


def resolve_city(city_name: str) -> ResolvedCity:
    normalized_name = city_name.strip()
    legacy_code = _get_legacy_city_code(normalized_name)
    detail_url = _find_cma_detail_url(normalized_name)
    if detail_url:
        return ResolvedCity(
            city_code=_extract_cma_city_code(detail_url),
            source="cma",
            detail_url=detail_url,
            fallback_legacy_code=legacy_code,
        )

    if legacy_code:
        return ResolvedCity(city_code=legacy_code, source="weather.com.cn")

    if _CMA_CITY_URL_CACHE_AVAILABLE is False:
        raise WeatherFetchError("CMA城市索引请求被站点拦截，且当前城市没有旧天气源回退")

    raise ValueError(f"未找到城市代码: {city_name}")


def load_cached_weather_forecast_for_city(city_name: str) -> ForecastBundle | None:
    for cache_key in _build_city_weather_cache_keys(city_name):
        cached_bundle = _load_cached_forecast_bundle(cache_key)
        if cached_bundle is not None:
            return cached_bundle
    return None


def fetch_weather_forecast(
    resolved_city: ResolvedCity, *, city_name: str | None = None
) -> ForecastBundle:
    cache_keys = _build_weather_cache_keys(resolved_city, city_name=city_name)
    for cache_key in cache_keys:
        cached_bundle = _load_cached_forecast_bundle(cache_key)
        if cached_bundle is not None:
            return cached_bundle

    if resolved_city.source == "cma" and resolved_city.detail_url:
        try:
            bundle = _fetch_cma_forecast_by_url(
                city_code=resolved_city.city_code,
                detail_url=resolved_city.detail_url,
            )
            if _should_cache_forecast_bundle(bundle):
                _save_cached_forecast_bundle_for_keys(cache_keys, bundle)
            return bundle
        except (WeatherFetchError, WeatherParseError):
            if resolved_city.fallback_legacy_code:
                return _fetch_legacy_forecast_by_code(resolved_city.fallback_legacy_code)
            raise

    bundle = _fetch_legacy_forecast_by_code(resolved_city.city_code)
    return bundle


def build_weather_response(
    *,
    city_name: str,
    requested_date: str,
    forecast_bundle: ForecastBundle,
) -> dict[str, Any]:
    selection = _resolve_requested_dates(
        request_text=requested_date,
        publish_date=forecast_bundle.publish_date,
        daily_forecasts=forecast_bundle.daily_forecasts,
    )
    selected_days = [
        item for item in forecast_bundle.daily_forecasts if item.forecast_date in selection.forecast_dates
    ]
    if not selected_days:
        raise WeatherDateError(code="date_out_of_range", message="未命中可用天气日期")

    weather = _build_weather_object(selected_days)
    forecast_days = [_serialize_forecast_day(item) for item in selected_days]
    summary = _build_summary(
        city_name=city_name,
        request_label=selection.request_label,
        selected_days=selected_days,
        publish_date=forecast_bundle.publish_date,
    )

    return {
        "date": selection.request_label,
        "matched_date": _format_matched_date(selected_days),
        "weather": weather,
        "summary": summary,
        "forecast_days": forecast_days,
        "source": forecast_bundle.source,
    }


def fetch_simple_weather(resolved_city: ResolvedCity) -> dict[str, Any]:
    forecast_bundle = fetch_weather_forecast(resolved_city)
    return build_weather_response(
        city_name="",
        requested_date="今天",
        forecast_bundle=forecast_bundle,
    )


@dataclass(frozen=True)
class _DateSelection:
    request_label: str
    forecast_dates: list[LocalDate]


def _resolve_requested_dates(
    *,
    request_text: str,
    publish_date: LocalDate,
    daily_forecasts: list[ForecastDay],
) -> _DateSelection:
    normalized_text = _normalize_request_text(request_text)
    available_dates = [item.forecast_date for item in daily_forecasts]
    available_set = set(available_dates)

    if normalized_text in {"", "今天", "今日", "现在", "当前"}:
        target_dates = [publish_date]
        request_label = "今天"
    elif target_date := _parse_exact_date(normalized_text, publish_date):
        target_dates = [target_date]
        request_label = normalized_text
    elif target_date := _parse_relative_date(normalized_text, publish_date):
        target_dates = [target_date]
        request_label = normalized_text
    elif range_dates := _parse_named_range_dates(
        normalized_text,
        publish_date=publish_date,
        available_dates=available_dates,
    ):
        target_dates = range_dates
        request_label = normalized_text
    elif weekend_dates := _parse_weekend_dates(normalized_text, publish_date):
        target_dates = weekend_dates
        request_label = normalized_text
    elif target_date := _parse_weekday_date(normalized_text, publish_date):
        target_dates = [target_date]
        request_label = normalized_text
    else:
        raise WeatherDateError(
            code="date_not_supported",
            message=f"暂不支持的日期表达: {request_text}",
        )

    if any(item not in available_set for item in target_dates):
        raise WeatherDateError(
            code="date_out_of_range",
            message=_build_date_out_of_range_message(available_dates),
        )

    return _DateSelection(request_label=request_label, forecast_dates=target_dates)


def _parse_named_range_dates(
    request_text: str,
    *,
    publish_date: LocalDate,
    available_dates: list[LocalDate],
) -> list[LocalDate] | None:
    if request_text in {"最近", "最近几天", "最近这几天", "近几天"}:
        return available_dates[: min(3, len(available_dates))]

    if request_text in {"最近一周", "最近7天", "未来一周", "未来7天", "这一周"}:
        return available_dates[: min(7, len(available_dates))]

    if request_text in {"这周", "本周", "这个星期"}:
        end_of_week = publish_date + timedelta(days=6 - publish_date.weekday())
        return [item for item in available_dates if publish_date <= item <= end_of_week]

    return None


def _parse_exact_date(request_text: str, publish_date: LocalDate) -> LocalDate | None:
    full_date_match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", request_text)
    if full_date_match:
        year, month, day = (int(value) for value in full_date_match.groups())
        return _safe_date(year, month, day)

    short_date_match = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})", request_text)
    if not short_date_match:
        return None

    month, day = (int(value) for value in short_date_match.groups())
    candidate = _safe_date(publish_date.year, month, day)
    if candidate is None:
        return None
    if candidate < publish_date and publish_date.month == 12 and month == 1:
        return _safe_date(publish_date.year + 1, month, day)
    return candidate


def _parse_relative_date(request_text: str, publish_date: LocalDate) -> LocalDate | None:
    fixed_offsets = {
        "今天": 0,
        "今日": 0,
        "明天": 1,
        "后天": 2,
        "大后天": 3,
    }
    if request_text in fixed_offsets:
        return publish_date + timedelta(days=fixed_offsets[request_text])

    match = re.fullmatch(r"(\d+)天后", request_text)
    if not match:
        return None
    return publish_date + timedelta(days=int(match.group(1)))


def _parse_weekend_dates(request_text: str, publish_date: LocalDate) -> list[LocalDate] | None:
    if request_text in {"周末", "本周末", "这周末", "这个周末"}:
        days_until_saturday = (5 - publish_date.weekday()) % 7
    elif request_text in {"下周末", "下个周末"}:
        days_until_saturday = (5 - publish_date.weekday()) % 7 + 7
    else:
        return None

    saturday = publish_date + timedelta(days=days_until_saturday)
    return [saturday, saturday + timedelta(days=1)]


def _parse_weekday_date(request_text: str, publish_date: LocalDate) -> LocalDate | None:
    prefix, weekday_token = _match_weekday_request_text(request_text)
    if weekday_token is None:
        return None

    weekday = WEEKDAY_TOKEN_MAP[weekday_token]
    start_of_week = publish_date - timedelta(days=publish_date.weekday())

    if prefix in {"本周", "这周"}:
        return start_of_week + timedelta(days=weekday)
    if prefix == "下周":
        return start_of_week + timedelta(days=7 + weekday)

    return publish_date + timedelta(days=(weekday - publish_date.weekday()) % 7)


def _match_weekday_request_text(request_text: str) -> tuple[str | None, str | None]:
    compact_match = re.fullmatch(
        r"(本周|这周|下周|下个周|本星期|这星期|下星期|下个星期|本礼拜|这礼拜|下礼拜|下个礼拜)([一二三四五六日天])",
        request_text,
    )
    if compact_match:
        raw_prefix, weekday_token = compact_match.groups()
        return _normalize_weekday_prefix(raw_prefix), weekday_token

    match = re.fullmatch(r"(本周|这周|下周)?(?:星期|周|礼拜)([一二三四五六日天])", request_text)
    if not match:
        return None, None

    raw_prefix, weekday_token = match.groups()
    return _normalize_weekday_prefix(raw_prefix), weekday_token


def _normalize_weekday_prefix(prefix: str | None) -> str | None:
    if prefix in {"本周", "本星期", "本礼拜"}:
        return "本周"
    if prefix in {"这周", "这星期", "这礼拜"}:
        return "这周"
    if prefix in {"下周", "下个周", "下星期", "下个星期", "下礼拜", "下个礼拜"}:
        return "下周"
    return prefix


def _build_date_out_of_range_message(available_dates: list[LocalDate]) -> str:
    if not available_dates:
        return "当前天气源没有可用日期"

    start = available_dates[0].isoformat()
    end = available_dates[-1].isoformat()
    return f"请求日期超出当前可用天气范围，当前支持 {start} 到 {end}"


def _build_summary(
    *,
    city_name: str,
    request_label: str,
    selected_days: list[ForecastDay],
    publish_date: LocalDate,
) -> str:
    prefix = city_name + request_label if city_name else request_label
    if len(selected_days) == 1:
        forecast = selected_days[0]
        if forecast.forecast_date == publish_date and forecast.temp_current:
            return (
                f"{prefix}{forecast.weather_day}，"
                f"当前{forecast.temp_current}°C，"
                f"最高{forecast.temp_high_day}°C，"
                f"最低{forecast.temp_low_night}°C。"
            )
        return (
            f"{prefix}{forecast.weather_day}，"
            f"最高{forecast.temp_high_day}°C，"
            f"最低{forecast.temp_low_night}°C。"
        )

    parts = []
    for item in selected_days:
        parts.append(
            f"{item.forecast_date.month}月{item.forecast_date.day}日（{_short_weekday(item.forecast_date)}）"
            f"{item.weather_day}，{item.temp_low_night}~{item.temp_high_day}°C"
        )
    return f"{prefix}天气：{'；'.join(parts)}。"


def _build_weather_object(selected_days: list[ForecastDay]) -> dict[str, str]:
    if len(selected_days) == 1:
        forecast = selected_days[0]
        return {
            "weather": forecast.weather_day,
            "temp_current": forecast.temp_current or forecast.temp_high_day,
            "temp_high_day": forecast.temp_high_day,
            "temp_low_night": forecast.temp_low_night,
        }

    max_high = max(selected_days, key=lambda item: _temperature_to_number(item.temp_high_day)).temp_high_day
    min_low = min(selected_days, key=lambda item: _temperature_to_number(item.temp_low_night)).temp_low_night
    weather_text = " / ".join(dict.fromkeys(item.weather_day for item in selected_days))
    first_day = selected_days[0]
    return {
        "weather": weather_text,
        "temp_current": first_day.temp_current or first_day.temp_high_day,
        "temp_high_day": max_high,
        "temp_low_night": min_low,
    }


def _serialize_forecast_day(forecast: ForecastDay) -> dict[str, str]:
    return {
        "date": forecast.forecast_date.isoformat(),
        "weekday": _short_weekday(forecast.forecast_date),
        "weather": forecast.weather_day,
        "temp_current": forecast.temp_current or forecast.temp_high_day,
        "temp_high_day": forecast.temp_high_day,
        "temp_low_night": forecast.temp_low_night,
    }


def _format_matched_date(selected_days: list[ForecastDay]) -> str:
    if len(selected_days) == 1:
        return selected_days[0].forecast_date.isoformat()
    return f"{selected_days[0].forecast_date.isoformat()} ~ {selected_days[-1].forecast_date.isoformat()}"


def _short_weekday(target_date: LocalDate) -> str:
    return WEEKDAY_NAME_MAP[target_date.weekday()]


def _fetch_cma_forecast_by_url(*, city_code: str, detail_url: str) -> ForecastBundle:
    session = _create_cma_session()
    html = _fetch_cma_html(session, detail_url)
    return _parse_cma_forecast_html(html=html, city_code=city_code)


def _parse_cma_forecast_html(*, html: str, city_code: str) -> ForecastBundle:
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    lines = [_normalize_line_text(line) for line in text.splitlines() if _normalize_line_text(line)]
    if not lines:
        raise WeatherParseError("CMA天气页内容为空")

    header_index = _find_line_index(lines, r"7天天气预报")
    if header_index is None:
        raise WeatherParseError("无法定位7天天气预报区块")

    publish_at = _parse_cma_publish_at(lines[header_index])
    daily_blocks = _extract_cma_daily_blocks(lines[header_index + 1 :])
    if not daily_blocks:
        raise WeatherParseError("无法解析CMA每日天气区块")

    daily_forecasts = []
    for index, block in enumerate(daily_blocks):
        daily_forecasts.append(
            _parse_cma_daily_block(
                block=block,
                forecast_date=publish_at.date() + timedelta(days=index),
            )
        )

    hourly_blocks = _extract_cma_hourly_blocks(lines[header_index + 1 :])
    if daily_forecasts and hourly_blocks:
        publish_hour = publish_at.hour
        current_temperature = _extract_hourly_temperature(hourly_blocks[0], publish_hour=publish_hour)
        if current_temperature is not None:
            daily_forecasts[0] = replace(daily_forecasts[0], temp_current=current_temperature)

    return ForecastBundle(
        city_code=city_code,
        source="cma",
        publish_date=publish_at.date(),
        daily_forecasts=daily_forecasts,
    )


def _parse_cma_publish_at(line: str) -> datetime:
    match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2}) (\d{1,2}):(\d{2})发布", line)
    if not match:
        raise WeatherParseError("无法解析CMA发布时间")
    year, month, day, hour, minute = (int(value) for value in match.groups())
    return datetime(year, month, day, hour, minute)


def _extract_cma_daily_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        if line.startswith("时间 "):
            break
        if line in {"更新", "*"}:
            continue
        if re.fullmatch(r"星期[一二三四五六日天]", line):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
            continue
        if current_block:
            current_block.append(line)

    if current_block:
        blocks.append(current_block)
    return blocks


def _parse_cma_daily_block(*, block: list[str], forecast_date: LocalDate) -> ForecastDay:
    if not block:
        raise WeatherParseError("CMA天气日块为空")

    weekday_text = block[0]
    display_date = next((line for line in block if re.fullmatch(r"\d{2}/\d{2}", line)), forecast_date.strftime("%m/%d"))
    weather_texts = [line for line in block if _looks_like_cma_weather_text(line)]
    temperatures = _extract_temperatures(block)

    if not weather_texts:
        raise WeatherParseError("无法解析CMA天气现象")
    if len(temperatures) < 2:
        raise WeatherParseError("无法解析CMA昼夜温度")

    return ForecastDay(
        forecast_date=forecast_date,
        weekday_text=weekday_text,
        display_date=display_date,
        weather_day=weather_texts[0],
        weather_night=weather_texts[1] if len(weather_texts) > 1 else None,
        temp_high_day=temperatures[0],
        temp_low_night=temperatures[1],
    )


def _extract_cma_hourly_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        if line.startswith("时间 "):
            if current_block:
                blocks.append(current_block)
            current_block = [line]
            continue
        if current_block:
            current_block.append(line)

    if current_block:
        blocks.append(current_block)
    return blocks


def _extract_hourly_temperature(block_lines: list[str], *, publish_hour: int) -> str | None:
    if not block_lines:
        return None

    time_line = block_lines[0]
    if not time_line.startswith("时间 "):
        return None

    time_labels = time_line.split()[1:]
    temperature_line = next((line for line in block_lines if line.startswith("气温 ")), None)
    if temperature_line is None:
        return None

    temperatures = re.findall(r"(-?\d+(?:\.\d+)?)℃", temperature_line)
    if not temperatures:
        return None

    target_label = f"{publish_hour:02d}:00"
    if target_label in time_labels:
        target_index = time_labels.index(target_label)
        if target_index < len(temperatures):
            return _normalize_temperature(temperatures[target_index])

    return _normalize_temperature(temperatures[0])


def _fetch_legacy_forecast_by_code(city_code: str) -> ForecastBundle:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    html = _fetch_legacy_html(session, f"https://www.weather.com.cn/weather/{city_code}.shtml")
    bundle = _parse_legacy_forecast_html(html=html, city_code=city_code)

    try:
        current_weather = _fetch_legacy_current_weather_by_code(city_code)
    except (WeatherFetchError, WeatherParseError):
        return bundle

    if not bundle.daily_forecasts:
        return bundle

    first_day = replace(
        bundle.daily_forecasts[0],
        weather_day=current_weather["weather"],
        temp_current=current_weather["temp_current"],
        temp_high_day=current_weather["temp_high_day"],
        temp_low_night=current_weather["temp_low_night"],
    )
    return replace(bundle, daily_forecasts=[first_day, *bundle.daily_forecasts[1:]])


def _fetch_legacy_html(session: requests.Session, url: str) -> str:
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherFetchError(f"天气源请求失败: {exc}") from exc

    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def _parse_legacy_forecast_html(*, html: str, city_code: str) -> ForecastBundle:
    soup = BeautifulSoup(html, "html.parser")
    legacy_root = soup.find(id="7d")
    forecast_root = legacy_root.find("ul", class_="t") if legacy_root is not None else None
    if forecast_root is None:
        raise WeatherParseError("无法定位旧天气源7天天气区块")

    forecast_items = forecast_root.find_all("li", class_=lambda value: value and "sky" in value.split(), recursive=False)
    if not forecast_items:
        raise WeatherParseError("无法解析旧天气源7天天气")

    publish_date = _parse_legacy_publish_date(soup) or LocalDate.today()
    hidden_title = _parse_legacy_hidden_title(soup)
    daily_forecasts = []
    for index, item in enumerate(forecast_items):
        daily_forecasts.append(
            _parse_legacy_daily_item(
                item=item,
                forecast_date=publish_date + timedelta(days=index),
                hidden_title=hidden_title if index == 0 else None,
            )
        )

    return ForecastBundle(
        city_code=city_code,
        source="weather.com.cn",
        publish_date=publish_date,
        daily_forecasts=daily_forecasts,
    )


def _parse_legacy_publish_date(soup: BeautifulSoup) -> LocalDate | None:
    update_input = soup.select_one("#fc_24h_internal_update_time")
    if update_input is None:
        return None
    raw_value = str(update_input.get("value") or "").strip()
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})\d{2}", raw_value)
    if not match:
        return None
    year, month, day = (int(value) for value in match.groups())
    return _safe_date(year, month, day)


def _parse_legacy_hidden_title(soup: BeautifulSoup) -> dict[str, str] | None:
    hidden_input = soup.select_one("#hidden_title")
    if hidden_input is None:
        return None
    raw_value = str(hidden_input.get("value") or "").strip()
    if not raw_value:
        return None

    weather_match = re.search(r"\s([\u4e00-\u9fff]+(?:转[\u4e00-\u9fff]+)?)\s+(-?\d+)\/(-?\d+)°C", raw_value)
    if not weather_match:
        return None

    weather, low_temp, high_temp = weather_match.groups()
    return {
        "weather": weather,
        "temp_high_day": _normalize_temperature(high_temp),
        "temp_low_night": _normalize_temperature(low_temp),
    }


def _parse_legacy_daily_item(
    *,
    item: Any,
    forecast_date: LocalDate,
    hidden_title: dict[str, str] | None,
) -> ForecastDay:
    weather_text = _normalize_line_text(item.select_one("p.wea").get_text(" ", strip=True)) if item.select_one("p.wea") else ""
    temperature_node = item.select_one("p.tem")
    if not weather_text or temperature_node is None:
        raise WeatherParseError("无法解析旧天气源日天气")

    high_node = temperature_node.select_one("span")
    low_node = temperature_node.select_one("i")
    high_temp = _parse_temperature_node(high_node)
    low_temp = _parse_temperature_node(low_node)

    if hidden_title:
        weather_text = hidden_title.get("weather") or weather_text
        high_temp = high_temp or hidden_title.get("temp_high_day")
        low_temp = low_temp or hidden_title.get("temp_low_night")

    if not high_temp and low_temp:
        high_temp = low_temp
    if not low_temp and high_temp:
        low_temp = high_temp
    if not high_temp or not low_temp:
        raise WeatherParseError("无法解析旧天气源温度")

    header_text = _normalize_line_text(item.select_one("h1").get_text(" ", strip=True)) if item.select_one("h1") else ""
    return ForecastDay(
        forecast_date=forecast_date,
        weekday_text=header_text or f"星期{_short_weekday(forecast_date)[1:]}",
        display_date=forecast_date.strftime("%m/%d"),
        weather_day=weather_text,
        temp_high_day=high_temp,
        temp_low_night=low_temp,
    )


def _parse_temperature_node(node: Any) -> str | None:
    if node is None:
        return None
    raw_text = _normalize_line_text(node.get_text(" ", strip=True))
    match = re.search(r"(-?\d+(?:\.\d+)?)℃", raw_text)
    if not match:
        return None
    return _normalize_temperature(match.group(1))


def _fetch_legacy_current_weather_by_code(city_code: str) -> dict[str, str]:
    html = _fetch_legacy_html(requests.Session(), f"https://www.weather.com.cn/weather1d/{city_code}.shtml")
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    day_lines = _find_block(lines, r"\d+日白天", r"\d+日夜间")
    night_lines = _find_block(lines, r"\d+日夜间", r"生活指数")
    if not day_lines or not night_lines:
        raise WeatherParseError("无法定位旧天气源昼夜区块")

    day_weather = _find_legacy_current_weather_text(day_lines)
    day_temp = _find_legacy_temp_text(day_lines)
    night_temp = _find_legacy_temp_text(night_lines)

    if not day_weather or not day_temp or not night_temp:
        raise WeatherParseError("无法解析旧天气源当前天气")

    return {
        "weather": day_weather,
        "temp_current": day_temp,
        "temp_high_day": day_temp,
        "temp_low_night": night_temp,
    }


def _find_cma_detail_url(city_name: str) -> str | None:
    city_index = _load_cma_city_url_cache()
    for candidate in _build_city_lookup_keys(city_name):
        detail_url = city_index.get(candidate)
        if detail_url:
            return detail_url
    return None


def _load_cma_city_url_cache() -> dict[str, str]:
    global _CMA_CITY_URL_CACHE_AVAILABLE
    global _CMA_CITY_URL_CACHE_LOADED_AT

    with _CMA_CITY_URL_CACHE_LOCK:
        if _CMA_CITY_URL_CACHE and (
            time.time() - _CMA_CITY_URL_CACHE_LOADED_AT < CMA_INDEX_TTL_SECONDS
        ):
            return dict(_CMA_CITY_URL_CACHE)

    try:
        city_index = _build_cma_city_url_index()
    except WeatherFetchError:
        _CMA_CITY_URL_CACHE_AVAILABLE = False
        return {}

    _CMA_CITY_URL_CACHE_AVAILABLE = True
    if not city_index:
        return {}

    with _CMA_CITY_URL_CACHE_LOCK:
        _CMA_CITY_URL_CACHE.clear()
        _CMA_CITY_URL_CACHE.update(city_index)
        _CMA_CITY_URL_CACHE_LOADED_AT = time.time()
        return dict(_CMA_CITY_URL_CACHE)


def _build_cma_city_url_index() -> dict[str, str]:
    session = _create_cma_session()
    area_html = _fetch_cma_html(session, CMA_AREA_URL)
    city_index = _extract_weather_links(area_html)

    for province_url in _extract_province_urls(area_html):
        try:
            province_html = _fetch_cma_html(session, province_url)
        except WeatherFetchError:
            continue
        for key, value in _extract_weather_links(province_html).items():
            city_index.setdefault(key, value)

    return city_index


def _create_cma_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(CMA_HEADERS)
    return session


def _fetch_cma_html(session: requests.Session, url: str) -> str:
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherFetchError(f"CMA天气页请求失败: {exc}") from exc

    response.encoding = response.apparent_encoding or "utf-8"
    html = response.text
    if _is_cma_blocked_page(html):
        raise WeatherFetchError("CMA天气页请求被站点拦截")
    return html


def _extract_weather_links(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    city_index: dict[str, str] = {}

    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue

        absolute_url = urljoin(CMA_BASE_URL, href)
        if not _is_cma_detail_url(absolute_url):
            continue

        anchor_text = _normalize_line_text(anchor.get_text(" ", strip=True))
        if not anchor_text or anchor_text in {"详情>>", "Image"}:
            continue

        for key in _build_city_lookup_keys(anchor_text):
            city_index.setdefault(key, absolute_url)

    return city_index


def _extract_province_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        if not href:
            continue
        absolute_url = urljoin(CMA_BASE_URL, href)
        if not re.search(r"/web/text/HD/[A-Z0-9]+\.html$", absolute_url):
            continue
        if absolute_url in seen:
            continue
        seen.add(absolute_url)
        urls.append(absolute_url)

    return urls


def _extract_cma_city_code(detail_url: str) -> str:
    match = re.search(r"/web/weather/([^/?#]+?)(?:\.html)?$", detail_url)
    if not match:
        raise WeatherParseError(f"无法从CMA详情页提取城市编码: {detail_url}")
    return match.group(1)


def _is_cma_detail_url(url: str) -> bool:
    return bool(re.search(r"/web/weather/[^/?#]+(?:\.html)?$", url))


def _is_cma_blocked_page(html: str) -> bool:
    return "您的请求可能存在威胁" in html or "已被拦截" in html


def _get_legacy_city_code(city_name: str) -> str | None:
    for candidate in _build_city_lookup_keys(city_name):
        code = CITY_CODE_MAP.get(candidate)
        if code:
            return code
    return None


def _looks_like_cma_weather_text(line: str) -> bool:
    if line in WEATHER_WORDS:
        return True
    if not line or line == "Image":
        return False
    if line.startswith(("星期", "时间 ", "天气 ", "气温 ", "降水 ", "风速 ", "风向 ", "气压 ", "湿度 ", "云量 ")):
        return False
    if re.fullmatch(r"\d{2}/\d{2}", line):
        return False
    if re.fullmatch(r"-?\d+(?:\.\d+)?℃", line):
        return False
    if line == "微风" or line == "无降水":
        return False
    if re.search(r"(级|m/s|hPa|%)", line):
        return False
    if line.endswith("风") or "无持续风向" in line:
        return False
    return True


def _looks_like_legacy_weather_text(line: str) -> bool:
    if not line:
        return False
    if line.startswith(("# ", "分时段预报", "今天", "7天", "8-15天", "40天")):
        return False
    if "℃" in line or "级" in line:
        return False
    if line.startswith("周边") or line.startswith("生活指数"):
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fff]+(?:转[\u4e00-\u9fff]+)?", line))


def _extract_temperatures(lines: list[str]) -> list[str]:
    temperatures: list[str] = []
    for line in lines:
        for value in re.findall(r"(-?\d+(?:\.\d+)?)℃", line):
            temperatures.append(_normalize_temperature(value))
    return temperatures


def _find_legacy_current_weather_text(lines: list[str]) -> str | None:
    for line in lines:
        candidate = line.strip()
        if candidate in WEATHER_WORDS:
            return candidate
    return None


def _find_legacy_temp_text(lines: list[str]) -> str | None:
    for index in range(len(lines) - 1):
        current = lines[index].strip()
        following = lines[index + 1].strip()
        if re.fullmatch(r"-?\d+", current) and following == "°C":
            return current

    for line in lines:
        match = re.fullmatch(r"(-?\d+)°C", line.strip())
        if match:
            return match.group(1)
    return None


def _find_block(lines: list[str], start_pattern: str, end_pattern: str | None = None) -> list[str]:
    start_index: int | None = None
    end_index: int | None = None

    for index, line in enumerate(lines):
        if start_index is None and re.search(start_pattern, line):
            start_index = index
            continue
        if start_index is not None and end_pattern and re.search(end_pattern, line):
            end_index = index
            break

    if start_index is None:
        return []
    if end_index is None:
        return lines[start_index + 1 :]
    return lines[start_index + 1 : end_index]


def _find_line_index(lines: list[str], pattern: str) -> int | None:
    for index, line in enumerate(lines):
        if re.search(pattern, line):
            return index
    return None


def _build_city_lookup_keys(city_name: str) -> list[str]:
    compact_name = _compact_lookup_text(city_name)
    normalized_name = _normalize_city_name(compact_name)

    keys: list[str] = []
    for candidate in (compact_name, normalized_name):
        if candidate and candidate not in keys:
            keys.append(candidate)
    return keys


def _normalize_city_name(city_name: str) -> str:
    normalized = _compact_lookup_text(city_name)
    changed = True
    while changed and normalized:
        changed = False
        for suffix in CITY_SUFFIXES:
            if normalized.endswith(suffix) and len(normalized) > len(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
                break
    return normalized


def _compact_lookup_text(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _normalize_line_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_request_text(value: str) -> str:
    return _compact_lookup_text(value)


def _normalize_temperature(value: str) -> str:
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value


def _temperature_to_number(value: str) -> float:
    return float(value)


def _safe_date(year: int, month: int, day: int) -> LocalDate | None:
    try:
        return LocalDate(year, month, day)
    except ValueError:
        return None


def _build_weather_cache_key(resolved_city: ResolvedCity) -> str:
    if resolved_city.detail_url:
        return resolved_city.detail_url
    return resolved_city.city_code


def _build_weather_cache_keys(
    resolved_city: ResolvedCity, *, city_name: str | None
) -> list[str]:
    keys = _build_city_weather_cache_keys(city_name or "")
    resolved_key = _build_weather_cache_key(resolved_city)
    if resolved_key not in keys:
        keys.append(resolved_key)
    return keys


def _build_city_weather_cache_keys(city_name: str) -> list[str]:
    return [f"city:{candidate}" for candidate in _build_city_lookup_keys(city_name)]


def _load_cached_forecast_bundle(cache_key: str) -> ForecastBundle | None:
    today = LocalDate.today().isoformat()
    with _WEATHER_FORECAST_CACHE_LOCK:
        cache_data = _read_weather_cache_file()
        cache_data, changed = _prune_weather_cache_data(cache_data, scope_date=today)
        if changed:
            _write_weather_cache_file(cache_data)
        entry = cache_data.get(cache_key)
        if not isinstance(entry, dict):
            return None
        bundle_data = entry.get("bundle")
        if not isinstance(bundle_data, dict):
            return None
        try:
            bundle = _deserialize_forecast_bundle(bundle_data)
        except (TypeError, ValueError, KeyError):
            cache_data.pop(cache_key, None)
            _write_weather_cache_file(cache_data)
            return None
        if not _should_cache_forecast_bundle(bundle):
            cache_data.pop(cache_key, None)
            _write_weather_cache_file(cache_data)
            return None
        return bundle


def _save_cached_forecast_bundle(cache_key: str, bundle: ForecastBundle) -> None:
    _save_cached_forecast_bundle_for_keys([cache_key], bundle)


def _save_cached_forecast_bundle_for_keys(cache_keys: list[str], bundle: ForecastBundle) -> None:
    if not _should_cache_forecast_bundle(bundle):
        return
    with _WEATHER_FORECAST_CACHE_LOCK:
        cache_data = _read_weather_cache_file()
        today = LocalDate.today().isoformat()
        cache_data, _ = _prune_weather_cache_data(cache_data, scope_date=today)
        bundle_data = _serialize_forecast_bundle(bundle)
        for cache_key in cache_keys:
            cache_data[cache_key] = {
                "fetched_on": today,
                "bundle": bundle_data,
            }
        _write_weather_cache_file(cache_data)


def _read_weather_cache_file() -> dict[str, Any]:
    try:
        raw_text = WEATHER_FORECAST_CACHE_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def _prune_weather_cache_data(
    cache_data: dict[str, Any], *, scope_date: str
) -> tuple[dict[str, Any], bool]:
    pruned_cache: dict[str, Any] = {}
    changed = False

    for cache_key, entry in cache_data.items():
        if not isinstance(entry, dict):
            changed = True
            continue
        if str(entry.get("fetched_on") or "") != scope_date:
            changed = True
            continue
        if not isinstance(entry.get("bundle"), dict):
            changed = True
            continue
        pruned_cache[cache_key] = entry

    if len(pruned_cache) != len(cache_data):
        changed = True

    return pruned_cache, changed


def _should_cache_forecast_bundle(bundle: ForecastBundle) -> bool:
    return bundle.source == "cma" and len(bundle.daily_forecasts) >= 7


def _write_weather_cache_file(cache_data: dict[str, Any]) -> None:
    try:
        WEATHER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = WEATHER_FORECAST_CACHE_PATH.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(cache_data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(WEATHER_FORECAST_CACHE_PATH)
    except OSError:
        return


def _serialize_forecast_bundle(bundle: ForecastBundle) -> dict[str, Any]:
    return {
        "city_code": bundle.city_code,
        "source": bundle.source,
        "publish_date": bundle.publish_date.isoformat(),
        "daily_forecasts": [_serialize_forecast_day_full(item) for item in bundle.daily_forecasts],
    }


def _serialize_forecast_day_full(forecast: ForecastDay) -> dict[str, Any]:
    return {
        "forecast_date": forecast.forecast_date.isoformat(),
        "weekday_text": forecast.weekday_text,
        "display_date": forecast.display_date,
        "weather_day": forecast.weather_day,
        "temp_high_day": forecast.temp_high_day,
        "temp_low_night": forecast.temp_low_night,
        "weather_night": forecast.weather_night,
        "temp_current": forecast.temp_current,
    }


def _deserialize_forecast_bundle(data: dict[str, Any]) -> ForecastBundle | None:
    try:
        publish_date_raw = str(data.get("publish_date") or "").strip()
        publish_date = LocalDate.fromisoformat(publish_date_raw)
        daily_forecasts_raw = data.get("daily_forecasts") or []
        if not isinstance(daily_forecasts_raw, list):
            return None
        daily_forecasts = [_deserialize_forecast_day(item) for item in daily_forecasts_raw]
        if any(item is None for item in daily_forecasts):
            return None
        return ForecastBundle(
            city_code=str(data.get("city_code") or "").strip(),
            source=str(data.get("source") or "").strip(),
            publish_date=publish_date,
            daily_forecasts=[item for item in daily_forecasts if item is not None],
        )
    except Exception:
        return None


def _deserialize_forecast_day(data: Any) -> ForecastDay | None:
    if not isinstance(data, dict):
        return None
    try:
        return ForecastDay(
            forecast_date=LocalDate.fromisoformat(str(data.get("forecast_date") or "").strip()),
            weekday_text=str(data.get("weekday_text") or "").strip(),
            display_date=str(data.get("display_date") or "").strip(),
            weather_day=str(data.get("weather_day") or "").strip(),
            temp_high_day=str(data.get("temp_high_day") or "").strip(),
            temp_low_night=str(data.get("temp_low_night") or "").strip(),
            weather_night=_normalize_optional_string(data.get("weather_night")),
            temp_current=_normalize_optional_string(data.get("temp_current")),
        )
    except Exception:
        return None


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
