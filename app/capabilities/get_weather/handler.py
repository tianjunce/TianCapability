from __future__ import annotations

import asyncio
from typing import Any

from app.capabilities.get_weather.weather_source import (
    WeatherFetchError,
    WeatherParseError,
    fetch_simple_weather_by_code,
    get_city_code,
)
from app.schemas.common import CapabilityExecutionError
from app.services.progress_writer import ProgressWriter


RESOLVE_CITY_STEP_ID = "resolve_city_code"
FETCH_WEATHER_STEP_ID = "fetch_weather_source"
FORMAT_RESULT_STEP_ID = "format_weather_result"

RESOLVE_CITY_LABEL = "解析城市编码"
FETCH_WEATHER_LABEL = "查询天气源"
FORMAT_RESULT_LABEL = "整理天气结果"


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    city = str(input.get("city") or "").strip()
    date = str(input.get("date") or "今天").strip() or "今天"
    if not city:
        raise CapabilityExecutionError(code="invalid_input", message="field 'city' is required")

    writer.running(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)
    try:
        city_code = get_city_code(city)
    except ValueError as exc:
        writer.error(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)
        raise CapabilityExecutionError(code="city_not_found", message=str(exc)) from exc
    writer.success(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)

    writer.running(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
    try:
        weather = await asyncio.to_thread(fetch_simple_weather_by_code, city_code)
    except WeatherParseError as exc:
        writer.error(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
        raise CapabilityExecutionError(code="weather_parse_failed", message=str(exc)) from exc
    except WeatherFetchError as exc:
        writer.error(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
        raise CapabilityExecutionError(code="weather_fetch_failed", message=str(exc)) from exc
    writer.success(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    summary = (
        f"{city}{date}"
        f"{weather.get('weather', '天气未知')}，"
        f"当前{weather.get('temp_current', '?')}°C，"
        f"最高{weather.get('temp_high_day', '?')}°C，"
        f"最低{weather.get('temp_low_night', '?')}°C。"
    )
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)

    return {
        "city": city,
        "date": date,
        "city_code": city_code,
        "weather": weather,
        "summary": summary,
    }

