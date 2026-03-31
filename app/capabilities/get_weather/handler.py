from __future__ import annotations

import asyncio
from typing import Any

from app.capabilities.get_weather.weather_source import (
    WeatherDateError,
    WeatherFetchError,
    WeatherParseError,
    build_weather_response,
    fetch_weather_forecast,
    load_cached_weather_forecast_for_city,
    resolve_city,
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
    requested_date = str(input.get("date") or "今天").strip() or "今天"
    if not city:
        raise CapabilityExecutionError(code="invalid_input", message="field 'city' is required")

    writer.running(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)
    forecast_bundle = await asyncio.to_thread(load_cached_weather_forecast_for_city, city)
    if forecast_bundle is not None:
        writer.success(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)
        writer.running(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
        writer.success(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
    else:
        try:
            resolved_city = resolve_city(city)
        except WeatherFetchError as exc:
            writer.error(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)
            raise CapabilityExecutionError(code="weather_fetch_failed", message=str(exc)) from exc
        except ValueError as exc:
            writer.error(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)
            raise CapabilityExecutionError(code="city_not_found", message=str(exc)) from exc
        writer.success(RESOLVE_CITY_STEP_ID, RESOLVE_CITY_LABEL)

        writer.running(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
        try:
            forecast_bundle = await asyncio.to_thread(
                fetch_weather_forecast,
                resolved_city,
                city_name=city,
            )
        except WeatherParseError as exc:
            writer.error(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
            raise CapabilityExecutionError(code="weather_parse_failed", message=str(exc)) from exc
        except WeatherFetchError as exc:
            writer.error(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)
            raise CapabilityExecutionError(code="weather_fetch_failed", message=str(exc)) from exc
        writer.success(FETCH_WEATHER_STEP_ID, FETCH_WEATHER_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    try:
        weather_payload = build_weather_response(
            city_name=city,
            requested_date=requested_date,
            forecast_bundle=forecast_bundle,
        )
    except WeatherDateError as exc:
        writer.error(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
        raise CapabilityExecutionError(code=exc.code, message=exc.message) from exc
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)

    return {
        "city": city,
        "date": weather_payload["date"],
        "matched_date": weather_payload["matched_date"],
        "city_code": forecast_bundle.city_code,
        "weather": weather_payload["weather"],
        "forecast_days": weather_payload["forecast_days"],
        "summary": weather_payload["summary"],
        "source": weather_payload["source"],
    }
