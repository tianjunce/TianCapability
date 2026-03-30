from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from app.capabilities.get_weather.city_codes import CITY_CODE_MAP


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)

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


class WeatherFetchError(RuntimeError):
    """Raised when the upstream weather source cannot be fetched."""


class WeatherParseError(RuntimeError):
    """Raised when the upstream weather source format cannot be parsed."""


def get_city_code(city_name: str) -> str:
    code = CITY_CODE_MAP.get(city_name)
    if not code:
        raise ValueError(f"未找到城市代码: {city_name}")
    return code


def fetch_simple_weather_by_code(city_code: str) -> dict[str, str]:
    url = f"https://www.weather.com.cn/weather1d/{city_code}.shtml"
    try:
        response = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherFetchError(f"天气源请求失败: {exc}") from exc

    response.encoding = response.apparent_encoding or "utf-8"
    text = BeautifulSoup(response.text, "html.parser").get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    day_lines = _find_block(lines, r"\d+日白天", r"\d+日夜间")
    night_lines = _find_block(lines, r"\d+日夜间", r"生活指数")

    if not day_lines:
        raise WeatherParseError("无法定位白天区块")
    if not night_lines:
        raise WeatherParseError("无法定位夜间区块")

    day_weather = _find_weather_text(day_lines)
    day_temp = _find_temp_text(day_lines)
    night_temp = _find_temp_text(night_lines)

    if not day_weather:
        raise WeatherParseError("无法解析白天天气")
    if not day_temp:
        raise WeatherParseError("无法解析白天最高温")
    if not night_temp:
        raise WeatherParseError("无法解析夜间最低温")

    return {
        "weather": day_weather,
        "temp_current": day_temp,
        "temp_high_day": day_temp,
        "temp_low_night": night_temp,
    }


def _find_weather_text(lines: list[str]) -> str | None:
    for line in lines:
        candidate = line.strip()
        if candidate in WEATHER_WORDS:
            return candidate
    return None


def _find_temp_text(lines: list[str]) -> str | None:
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

