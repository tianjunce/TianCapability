from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
import hashlib
import hmac
import json
from statistics import mean
from typing import Any
from urllib.parse import urljoin

import requests

from app.schemas.common import CapabilityExecutionError
from app.services.env_config import get_config_value
from app.services.progress_writer import ProgressWriter


VALIDATE_AUTH_STEP_ID = "validate_auth_context"
FETCH_AREAS_STEP_ID = "fetch_user_areas"
FETCH_DASHBOARD_STEP_ID = "fetch_dashboard_data"
FORMAT_RESULT_STEP_ID = "format_dashboard_result"

VALIDATE_AUTH_LABEL = "校验用户上下文"
FETCH_AREAS_LABEL = "查询用户基地列表"
FETCH_DASHBOARD_LABEL = "查询基地数据"
FORMAT_RESULT_LABEL = "整理基地结果"

SPECIAL_SCREEN_RICESTAGE_IDS = {"11", "330727001"}

SECRET_KEY = "jlsdjfWeer12341"
ALGORITHM = "HS256"
DEBUG_PREFIX = "[capability:get_base_basic_data]"


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def create_token(username: str, level: int, key: str = SECRET_KEY, alg: str = ALGORITHM) -> str:
    if alg != "HS256":
        raise CapabilityExecutionError(code="invalid_config", message=f"unsupported algorithm: {alg}")

    token_data = {
        "username": username,
        "level": level,
        "exp": int((datetime.utcnow() + timedelta(hours=48)).timestamp()),
    }
    header = {"alg": alg, "typ": "JWT"}

    header_part = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _base64url_encode(json.dumps(token_data, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("utf-8")
    signature = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_part = _base64url_encode(signature)
    return f"{header_part}.{payload_part}.{signature_part}"


def _resolve_user_level(user_id: str) -> int:
    return 0 if user_id.strip().lower() == "admin" else 5


def _build_access_token_from_context(*, context: dict[str, Any]) -> tuple[str, str]:
    user_id = str(context.get("user_id") or "").strip()
    if not user_id:
        raise CapabilityExecutionError(code="invalid_request", message="context.user_id is required")
    return create_token(user_id, level=_resolve_user_level(user_id)), user_id


def _api_base_url() -> str:
    value = get_config_value("RICE_API_BASE_URL", "http://115.239.197.198:8688")
    return value.rstrip("/")


def _api_timeout() -> int:
    raw = get_config_value("RICE_API_TIMEOUT_SECONDS", "20")
    try:
        return max(int(raw), 5)
    except ValueError:
        return 20


class RiceApiClient:
    def __init__(self, *, base_url: str, access_token: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.headers = {
            "Authorization": f"Bearer {access_token}",
        }

    def get_json(self, path: str, *, params: dict[str, Any] | None = None, label: str | None = None) -> Any:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        request_params = params or {}
        request_label = label or path
        # print(f"{DEBUG_PREFIX} request label={request_label} path={path} params={request_params}")
        try:
            response = self.session.get(
                url,
                params=request_params,
                headers=self.headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            print(f"{DEBUG_PREFIX} request_error label={request_label} error={exc.__class__.__name__}: {str(exc)}")
            raise

        # print(f"{DEBUG_PREFIX} response label={request_label} status={response.status_code} ok={response.ok}")
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            print(f"{DEBUG_PREFIX} json_error label={request_label} path={path}")
            raise CapabilityExecutionError(code="upstream_invalid_json", message=f"接口返回非 JSON：{path}") from exc



async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    writer.running(VALIDATE_AUTH_STEP_ID, VALIDATE_AUTH_LABEL)
    action = str(input.get("action") or "overview").strip().lower() or "overview"
    if action != "overview":
        writer.error(VALIDATE_AUTH_STEP_ID, VALIDATE_AUTH_LABEL)
        raise CapabilityExecutionError(code="invalid_input", message="field 'action' must be 'overview'")

    try:
        access_token, _user_id = _build_access_token_from_context(context=context)
    except CapabilityExecutionError:
        writer.error(VALIDATE_AUTH_STEP_ID, VALIDATE_AUTH_LABEL)
        raise

    area_id = str(input.get("area_id") or "").strip()
    area_name = str(input.get("area_name") or "").strip()
    start_date, end_date = _resolve_date_range(
        start_date=str(input.get("start_date") or "").strip(),
        end_date=str(input.get("end_date") or "").strip(),
    )
    # print(f"{DEBUG_PREFIX} input action={action} area_id={area_id!r} area_name={area_name!r} start={start_date} end={end_date} user_id={_user_id}")
    writer.success(VALIDATE_AUTH_STEP_ID, VALIDATE_AUTH_LABEL)

    client = RiceApiClient(
        base_url=_api_base_url(),
        access_token=access_token,
        timeout_seconds=_api_timeout(),
    )

    writer.running(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)
    try:
        areas = _fetch_all_areas(client=client, area_name_filter=area_name)
    except requests.HTTPError as exc:
        writer.error(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code in {401, 403}:
            raise CapabilityExecutionError(code="auth_required", message="登录态已过期，请重新登录后再试") from exc
        raise CapabilityExecutionError(code="area_query_failed", message=f"查询基地列表失败（HTTP {status_code}）") from exc

    # print(f"{DEBUG_PREFIX} area_rows_fetched raw_count={len(areas)}")
    if not areas:
        writer.error(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)
        raise CapabilityExecutionError(code="area_not_found", message="当前账号没有可访问基地")

    selected_area, need_input = _select_area(
        areas=areas,
        area_id=area_id,
        area_name=area_name,
        start_date=start_date,
        end_date=end_date,
    )
    if need_input is not None:
        reason = str(((need_input.get("context") or {}).get("reason") or "需要先指定基地")).strip()
        area_options = (need_input.get("slots") or {}).get("area_options")
        option_text = "请提供基地名称或基地 ID"
        if isinstance(area_options, list):
            option_lines = [
                f"{str(item.get('area_name') or '').strip()}（ID: {str(item.get('area_id') or '').strip()}）"
                for item in area_options[:12]
                if isinstance(item, dict)
                and str(item.get("area_id") or "").strip()
                and str(item.get("area_name") or "").strip()
            ]
            if option_lines:
                option_text = "；".join(option_lines)
        writer.error(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)
        raise CapabilityExecutionError(
            code="area_selection_required",
            message=f"{reason}。可选：{option_text}",
        )
    writer.success(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)
    # print(f"{DEBUG_PREFIX} selected_area id={str(selected_area.get('id') or '').strip()} name={str(selected_area.get('area_name') or '').strip()}")

    writer.running(FETCH_DASHBOARD_STEP_ID, FETCH_DASHBOARD_LABEL)
    warnings: list[str] = []

    area_id_value = str(selected_area.get("id") or "").strip()
    area_name_value = str(selected_area.get("area_name") or "").strip() or area_id_value
    met_num = str(selected_area.get("met_num") or "").strip()
    insects_num = str(selected_area.get("insects_num") or "").strip()
    ricestage_num = str(selected_area.get("ricestage_num") or "").strip()
    # print(f"{DEBUG_PREFIX} device_refs met_num={met_num!r} insects_num={insects_num!r} ricestage_num={ricestage_num!r}")

    met_data = _fetch_optional(
        client=client,
        path="/screen/getMet",
        params={"deviceNum": met_num, "startTime": start_date, "endTime": end_date},
        empty_condition=not met_num,
        label="温湿度",
        warnings=warnings,
    )
    insect_data = _fetch_optional(
        client=client,
        path="/pengbo/getInsect",
        params={"deviceNum": insects_num, "startTime": start_date, "endTime": end_date},
        empty_condition=not insects_num,
        label="虫情",
        warnings=warnings,
    )
    latest_data = _fetch_optional(
        client=client,
        path="/screen/getLatestData",
        params={"areaId": area_id_value},
        empty_condition=not area_id_value,
        label="最新系统数据",
        warnings=warnings,
    )
    rice_stage_data, stage_meta = _fetch_rice_stage(
        client=client,
        ricestage_num=ricestage_num,
        start_date=start_date,
        end_date=end_date,
        warnings=warnings,
    )

    writer.success(FETCH_DASHBOARD_STEP_ID, FETCH_DASHBOARD_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    met_overview = _build_met_overview(met_data)
    insect_overview = _build_insect_overview(insect_data)
    rice_stage_overview = _build_rice_stage_overview(rice_stage_data, stage_meta=stage_meta)
    latest_snapshot = latest_data if isinstance(latest_data, dict) else {}

    summary = _build_summary(
        area_name=area_name_value,
        start_date=start_date,
        end_date=end_date,
        met_overview=met_overview,
        insect_overview=insect_overview,
        latest_snapshot=latest_snapshot,
        warnings=warnings,
    )
    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    # print(f"{DEBUG_PREFIX} result warnings={len(warnings)} met_series={len(met_overview.get('temp_series') or [])} insect_series={len(insect_overview.get('ehm_series') or [])}")

    return {
        "summary": summary,
        "selected_area_id": area_id_value,
        "selected_area_name": area_name_value,
        "date_range_start": start_date,
        "date_range_end": end_date,
        "device_refs": {
            "met_num": met_num,
            "insects_num": insects_num,
            "ricestage_num": ricestage_num,
        },
        "met_overview": met_overview,
        "insect_overview": insect_overview,
        "rice_stage_overview": rice_stage_overview,
        "latest_snapshot": latest_snapshot,
        "warnings": warnings,
    }


def _resolve_date_range(*, start_date: str, end_date: str) -> tuple[str, str]:
    today = date.today()
    default_start = today - timedelta(days=365)

    resolved_start = _parse_date(start_date) if start_date else default_start
    resolved_end = _parse_date(end_date) if end_date else today

    if resolved_start > resolved_end:
        raise CapabilityExecutionError(code="invalid_input", message="start_date 不能晚于 end_date")

    return resolved_start.strftime("%Y-%m-%d"), resolved_end.strftime("%Y-%m-%d")


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CapabilityExecutionError(code="invalid_input", message=f"日期格式不合法：{value}，应为 YYYY-MM-DD") from exc


def _unwrap_api_payload(payload: Any, *, path: str) -> Any:
    if not isinstance(payload, dict):
        return payload

    code = payload.get("code")
    if code not in (None, 0, 200, "200"):
        message = str(payload.get("msg") or payload.get("message") or f"接口调用失败：{path}").strip()
        raise CapabilityExecutionError(code="upstream_request_failed", message=message)

    if "data" in payload:
        return payload.get("data")
    return payload


def _fetch_all_areas(*, client: RiceApiClient, area_name_filter: str) -> list[dict[str, Any]]:
    page_num = 1
    page_size = 200
    rows: list[dict[str, Any]] = []

    while True:
        payload = client.get_json(
            "/area/page",
            params={
                "page_num": page_num,
                "page_size": page_size,
                "area_name": area_name_filter,
            },
            label="area_page",
        )
        data = _unwrap_api_payload(payload, path="/area/page")
        if not isinstance(data, dict):
            raise CapabilityExecutionError(code="area_query_failed", message="基地列表响应格式错误")

        current_rows = data.get("rows")
        if not isinstance(current_rows, list):
            current_rows = []

        normalized_rows = [item for item in current_rows if isinstance(item, dict)]
        rows.extend(normalized_rows)

        total = _coerce_int(data.get("total"), default=len(rows))
        # print(f"{DEBUG_PREFIX} area_page_result page={page_num} rows_in_page={len(normalized_rows)} rows_accumulated={len(rows)} total={total}")
        if len(rows) >= total:
            break
        if len(normalized_rows) < page_size:
            break

        page_num += 1
        if page_num > 50:
            break

    return rows


def _select_area(
    *,
    areas: list[dict[str, Any]],
    area_id: str,
    area_name: str,
    start_date: str,
    end_date: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if area_id:
        exact = [area for area in areas if str(area.get("id") or "").strip() == area_id]
        if len(exact) == 1:
            return exact[0], None
        return None, _build_need_input_for_area(
            areas=areas,
            start_date=start_date,
            end_date=end_date,
            reason=f"未找到基地 ID 为 {area_id} 的记录",
        )

    if area_name:
        normalized_target = area_name.strip().lower()
        exact_name = [
            area
            for area in areas
            if str(area.get("area_name") or "").strip().lower() == normalized_target
        ]
        if len(exact_name) == 1:
            return exact_name[0], None

        fuzzy_name = [
            area
            for area in areas
            if normalized_target in str(area.get("area_name") or "").strip().lower()
        ]
        if len(fuzzy_name) == 1:
            return fuzzy_name[0], None

        candidates = exact_name if exact_name else fuzzy_name
        if candidates:
            return None, _build_need_input_for_area(
                areas=candidates,
                start_date=start_date,
                end_date=end_date,
                reason=f"基地名称“{area_name}”匹配到多个结果",
            )

        return None, _build_need_input_for_area(
            areas=areas,
            start_date=start_date,
            end_date=end_date,
            reason=f"未找到基地名称“{area_name}”",
        )

    if len(areas) == 1:
        return areas[0], None

    return None, _build_need_input_for_area(
        areas=areas,
        start_date=start_date,
        end_date=end_date,
        reason="当前账号可访问多个基地，请先选择一个基地",
    )


def _build_need_input_for_area(
    *,
    areas: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    reason: str,
) -> dict[str, Any]:
    options = [
        {
            "area_id": str(area.get("id") or "").strip(),
            "area_name": str(area.get("area_name") or "").strip(),
        }
        for area in areas
        if str(area.get("id") or "").strip() and str(area.get("area_name") or "").strip()
    ]

    option_lines = [f"{item['area_name']}（ID: {item['area_id']}）" for item in options[:12]]
    option_text = "；".join(option_lines) if option_lines else "请提供基地名称或基地 ID"

    return {
        "question": f"{reason}。请回复基地名称或基地 ID。可选：{option_text}",
        "missing_fields": ["area_name"],
        "slots": {
            "action": "overview",
            "start_date": start_date,
            "end_date": end_date,
            "area_options": options,
        },
        "context": {
            "reason": reason,
            "candidate_area_count": len(options),
        },
        "hints": [
            "可以直接回复“基地名称”或“ID:xxxx”",
            "若要改时间范围，也可以一并补充 start_date / end_date（YYYY-MM-DD）",
        ],
    }


def _fetch_optional(
    *,
    client: RiceApiClient,
    path: str,
    params: dict[str, Any],
    empty_condition: bool,
    label: str,
    warnings: list[str],
) -> Any:
    if empty_condition:
        warnings.append(f"{label}缺少设备编号，已跳过")
        print(f"{DEBUG_PREFIX} skip label={label} path={path} reason=missing_device_num params={params}")
        return None

    try:
        payload = client.get_json(path, params=params, label=label)
        return _unwrap_api_payload(payload, path=path)
    except CapabilityExecutionError as exc:
        warnings.append(f"{label}查询失败：{exc.message}")
    except requests.RequestException as exc:
        warnings.append(f"{label}查询失败：{str(exc)}")
    return None


def _fetch_rice_stage(
    *,
    client: RiceApiClient,
    ricestage_num: str,
    start_date: str,
    end_date: str,
    warnings: list[str],
) -> tuple[Any, dict[str, Any]]:
    if not ricestage_num:
        warnings.append("生育期缺少设备编号，已跳过")
        return None, {}

    if ricestage_num in SPECIAL_SCREEN_RICESTAGE_IDS:
        payload = _fetch_optional(
            client=client,
            path="/screen/getRiceStage",
            params={"deviceNum": ricestage_num, "startTime": start_date, "endTime": end_date},
            empty_condition=False,
            label="生育期",
            warnings=warnings,
        )
        return payload, {"source": "screen"}

    preset = ""
    crop = ""
    preset_payload = _fetch_optional(
        client=client,
        path="/aipp/getDevicePresets",
        params={"deviceNum": ricestage_num},
        empty_condition=False,
        label="生育期点位预设",
        warnings=warnings,
    )
    if isinstance(preset_payload, dict):
        presets = preset_payload.get("presets")
        if isinstance(presets, list) and presets:
            first_item = presets[0] if isinstance(presets[0], dict) else {}
            preset = str(first_item.get("preset") or "").strip()
            crop = str(first_item.get("crop") or "").strip()

    params = {
        "deviceNum": ricestage_num,
        "startTime": start_date,
        "endTime": end_date,
    }
    if preset:
        params["preset"] = preset

    payload = _fetch_optional(
        client=client,
        path="/aipp/getRiceStage",
        params=params,
        empty_condition=False,
        label="生育期",
        warnings=warnings,
    )
    return payload, {"source": "aipp", "preset": preset, "crop": crop}


def _build_met_overview(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    xticks = data.get("xticks") if isinstance(data.get("xticks"), list) else []
    return {
        "latest_date": xticks[-1] if xticks else None,
        "temp_series": _summarize_series_group(data.get("temp"), xticks=xticks),
        "hum_series": _summarize_series_group(data.get("hum"), xticks=xticks),
    }


def _build_insect_overview(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    xticks = data.get("xticks") if isinstance(data.get("xticks"), list) else []
    return {
        "latest_date": xticks[-1] if xticks else None,
        "ehm_series": _summarize_series_group(data.get("ehm"), xticks=xticks),
        "dzjym_series": _summarize_series_group(data.get("dzjym"), xticks=xticks),
        "hefs_series": _summarize_series_group(data.get("hefs"), xticks=xticks),
    }


def _build_rice_stage_overview(data: Any, *, stage_meta: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return stage_meta if stage_meta else {}

    xticks = data.get("xticks") if isinstance(data.get("xticks"), list) else []
    stage_series = _summarize_series_group(data.get("stage"), xticks=xticks)
    payload = {
        "latest_date": xticks[-1] if xticks else None,
        "stage_series": stage_series,
    }
    payload.update({key: value for key, value in stage_meta.items() if value})
    return payload


def _summarize_series_group(value: Any, *, xticks: list[Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    result: list[dict[str, Any]] = []
    latest_date = str(xticks[-1]) if xticks else ""
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip() or "series"
        data_points = item.get("data")
        if not isinstance(data_points, list):
            continue
        numbers = [_to_float(point) for point in data_points]
        valid = [point for point in numbers if point is not None]
        if not valid:
            continue
        summary = {
            "name": name,
            "latest": _round_number(valid[-1]),
            "min": _round_number(min(valid)),
            "max": _round_number(max(valid)),
            "mean": _round_number(mean(valid)),
            "count": len(valid),
        }
        if latest_date:
            summary["latest_date"] = latest_date
        result.append(summary)
    return result


def _build_summary(
    *,
    area_name: str,
    start_date: str,
    end_date: str,
    met_overview: dict[str, Any],
    insect_overview: dict[str, Any],
    latest_snapshot: dict[str, Any],
    warnings: list[str],
) -> str:
    lines = [f"基地“{area_name}”数据已获取（{start_date} ~ {end_date}）。"]

    temp_mean = _extract_nested_number(latest_snapshot, ("temp", "mean"))
    hum_mean = _extract_nested_number(latest_snapshot, ("hum", "mean"))
    if temp_mean is not None or hum_mean is not None:
        facts: list[str] = []
        if temp_mean is not None:
            facts.append(f"最新平均温度 {temp_mean}°C")
        if hum_mean is not None:
            facts.append(f"最新平均湿度 {hum_mean}%")
        lines.append("；".join(facts) + "。")

    latest_ehm = _extract_first_latest(insect_overview.get("ehm_series"))
    latest_dzjym = _extract_first_latest(insect_overview.get("dzjym_series"))
    insect_facts: list[str] = []
    if latest_ehm is not None:
        insect_facts.append(f"二化螟最新值 {latest_ehm}")
    if latest_dzjym is not None:
        insect_facts.append(f"稻纵卷叶螟最新值 {latest_dzjym}")
    if insect_facts:
        lines.append("；".join(insect_facts) + "。")

    temp_series_count = len(met_overview.get("temp_series") or [])
    hum_series_count = len(met_overview.get("hum_series") or [])
    if temp_series_count or hum_series_count:
        lines.append(f"温湿度序列：温度 {temp_series_count} 条，湿度 {hum_series_count} 条。")

    if warnings:
        lines.append("部分数据未获取：" + "；".join(warnings[:3]) + "。")

    return " ".join(lines)


def _extract_first_latest(series_list: Any) -> float | int | None:
    if not isinstance(series_list, list) or not series_list:
        return None
    first = series_list[0]
    if not isinstance(first, dict):
        return None
    value = first.get("latest")
    if isinstance(value, (int, float)):
        return _round_number(value)
    return None


def _extract_nested_number(source: dict[str, Any], path: tuple[str, ...]) -> float | int | None:
    current: Any = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    number = _to_float(current)
    if number is None:
        return None
    return _round_number(number)


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _round_number(value: float) -> float | int:
    rounded = round(value, 2)
    if abs(rounded - int(rounded)) < 1e-9:
        return int(rounded)
    return rounded


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default



