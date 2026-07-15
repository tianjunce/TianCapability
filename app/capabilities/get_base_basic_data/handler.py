from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
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

SECRET_KEY = "jlsdjfWeer12341"
ALGORITHM = "HS256"
DEBUG_PREFIX = "[capability:get_base_basic_data]"
RESULT_LOG_DIR_NAME = "log"
RESULT_LOG_FILE_NAME = "get_base_basic_data_result.log"
API_CALL_LOG_FILE_NAME = "get_base_basic_data_api_calls.log"


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
            _append_api_call_log(
                record={
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "label": request_label,
                    "path": path,
                    "url": url,
                    "method": "GET",
                    "params": request_params,
                    "ok": False,
                    "status_code": None,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                    "response": None,
                }
            )
            print(f"{DEBUG_PREFIX} request_error label={request_label} error={exc.__class__.__name__}: {str(exc)}")
            raise

        # print(f"{DEBUG_PREFIX} response label={request_label} status={response.status_code} ok={response.ok}")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            _append_api_call_log(
                record={
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "label": request_label,
                    "path": path,
                    "url": url,
                    "method": "GET",
                    "params": request_params,
                    "ok": False,
                    "status_code": response.status_code,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                    "response": _raw_text_preview(response.text),
                }
            )
            raise
        try:
            payload = response.json()
        except ValueError as exc:
            _append_api_call_log(
                record={
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "label": request_label,
                    "path": path,
                    "url": url,
                    "method": "GET",
                    "params": request_params,
                    "ok": False,
                    "status_code": response.status_code,
                    "error_type": exc.__class__.__name__,
                    "error": "response is not valid json",
                    "response": _raw_text_preview(response.text),
                }
            )
            print(f"{DEBUG_PREFIX} json_error label={request_label} path={path}")
            raise CapabilityExecutionError(code="upstream_invalid_json", message=f"接口返回非 JSON：{path}") from exc

        _append_api_call_log(
            record={
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "label": request_label,
                "path": path,
                "url": url,
                "method": "GET",
                "params": request_params,
                "ok": True,
                "status_code": response.status_code,
                "error_type": "",
                "error": "",
                "response": payload,
            }
        )
        return payload



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
    raw_area_id = input.get("area_id")
    print(
        f"{DEBUG_PREFIX} incoming action={action!r} area_id_raw={raw_area_id!r} "
        f"area_id_type={type(raw_area_id).__name__} area_name={area_name!r} "
        f"start_date_raw={input.get('start_date')!r} end_date_raw={input.get('end_date')!r}"
    )
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
    suggest_num = str(selected_area.get("suggest_num") or "").strip()
    # print(f"{DEBUG_PREFIX} device_refs met_num={met_num!r} insects_num={insects_num!r} ricestage_num={ricestage_num!r}")

    history_start_time, history_end_time = _area_history_time_range(
        start_date=start_date,
        end_date=end_date,
    )
    met_data, met_status = _fetch_area_optional(
        client=client,
        path="/screen/getAreaMet",
        params={
            "areaId": area_id_value,
            "startTime": history_start_time,
            "endTime": history_end_time,
            "includeBindingMeta": False,
        },
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
    rice_stage_data, stage_meta = _fetch_area_rice_stage(
        client=client,
        area_id=area_id_value,
        start_date=start_date,
        end_date=end_date,
        warnings=warnings,
    )
    suggest_start_date = _offset_date(start_date, days=-14)
    suggest_data = _fetch_optional(
        client=client,
        path="/screen/v2/getSuggestRice",
        params={"deviceNum": suggest_num, "startTime": suggest_start_date, "endTime": end_date},
        empty_condition=not suggest_num,
        label="农事建议",
        warnings=warnings,
    )

    writer.success(FETCH_DASHBOARD_STEP_ID, FETCH_DASHBOARD_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    met_overview = _build_met_overview(met_data, binding_status=met_status)
    insect_overview = _build_insect_overview(insect_data)
    rice_stage_overview = _build_rice_stage_overview(rice_stage_data, stage_meta=stage_meta)
    suggest_overview = _build_suggest_overview(suggest_data)
    time_axes, met_overview, insect_overview, rice_stage_overview = _compact_time_axes(
        met_overview=met_overview,
        insect_overview=insect_overview,
        rice_stage_overview=rice_stage_overview,
    )

    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    # print(f"{DEBUG_PREFIX} result warnings={len(warnings)}")

    result = {
        "selected_area_id": area_id_value,
        "selected_area_name": area_name_value,
        "date_range_start": start_date,
        "date_range_end": end_date,
        "query_mode": "area",
        "device_refs": {
            "met_num": met_num,
            "insects_num": insects_num,
            "ricestage_num": ricestage_num,
            "suggest_num": suggest_num,
        },
        "time_axes": time_axes,
        "met_overview": met_overview,
        "insect_overview": insect_overview,
        "rice_stage_overview": rice_stage_overview,
        "suggest_overview": suggest_overview,
        "module_statuses": {
            "weather": met_status,
            "rice_stage": str(stage_meta.get("binding_status") or "NORMAL"),
            "rice_stage_preset": str(stage_meta.get("preset_status") or "NORMAL"),
        },
        "warnings": warnings,
    }
    _append_result_log(input_payload=input, context=context, result=result)
    # print(f"{DEBUG_PREFIX} final_result={json.dumps(result, ensure_ascii=False, default=str)}")
    return result


def _resolve_date_range(*, start_date: str, end_date: str) -> tuple[str, str]:
    today = date.today()
    # 默认最近 20 天（含今天）
    default_start = today - timedelta(days=20)

    resolved_start = _parse_date(start_date) if start_date else default_start
    resolved_end = _parse_date(end_date) if end_date else today

    if resolved_start > resolved_end:
        raise CapabilityExecutionError(code="invalid_input", message="start_date 不能晚于 end_date")

    return resolved_start.strftime("%Y-%m-%d"), resolved_end.strftime("%Y-%m-%d")


def _append_result_log(*, input_payload: dict[str, Any], context: dict[str, Any], result: dict[str, Any]) -> None:
    # pass
    log_dir = Path(__file__).resolve().parent / RESULT_LOG_DIR_NAME
    log_file = log_dir / RESULT_LOG_FILE_NAME
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "capability": "get_base_basic_data",
        "user_id": str(context.get("user_id") or "").strip(),
        "input": input_payload,
        "result": result,
    }

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, default=str))
            fp.write("\n")
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"{DEBUG_PREFIX} write_result_log_failed error={exc.__class__.__name__}: {str(exc)}")


def _append_api_call_log(*, record: dict[str, Any]) -> None:
    # pass
    log_dir = Path(__file__).resolve().parent / RESULT_LOG_DIR_NAME
    log_file = log_dir / API_CALL_LOG_FILE_NAME

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, default=str))
            fp.write("\n")
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"{DEBUG_PREFIX} write_api_log_failed error={exc.__class__.__name__}: {str(exc)}")


def _raw_text_preview(value: Any, *, limit: int = 4000) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated)"


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CapabilityExecutionError(code="invalid_input", message=f"日期格式不合法：{value}，应为 YYYY-MM-DD") from exc


def _offset_date(value: str, *, days: int) -> str:
    return (_parse_date(value) + timedelta(days=days)).strftime("%Y-%m-%d")


def _area_history_time_range(*, start_date: str, end_date: str) -> tuple[str, str]:
    """Convert the inclusive input dates to a local-time half-open range."""
    start = _parse_date(start_date)
    end_exclusive = _parse_date(end_date) + timedelta(days=1)
    return (
        f"{start.strftime('%Y-%m-%d')} 00:00:00",
        f"{end_exclusive.strftime('%Y-%m-%d')} 00:00:00",
    )


def _unwrap_api_payload(payload: Any, *, path: str) -> Any:
    if not isinstance(payload, dict):
        return payload

    code = payload.get("code")
    if code not in (None, 0, 200, "200"):
        message = str(payload.get("msg") or payload.get("message") or f"接口调用失败：{path}").strip()
        data = payload.get("data")
        error_code = str(data.get("errorCode") or "").strip() if isinstance(data, dict) else ""
        raise CapabilityExecutionError(code=error_code or "upstream_request_failed", message=message)

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


def _fetch_area_optional(
    *,
    client: RiceApiClient,
    path: str,
    params: dict[str, Any],
    label: str,
    warnings: list[str],
) -> tuple[Any, str]:
    """Read one area-scoped module without falling back to current device fields."""
    try:
        payload = client.get_json(path, params=params, label=label)
        data = _unwrap_api_payload(payload, path=path)
    except CapabilityExecutionError as exc:
        status = _status_from_error_code(exc.code)
        warnings.append(f"{label}：{status}（{exc.message}）")
        return None, status
    except requests.RequestException as exc:
        warnings.append(f"{label}查询失败：{str(exc)}")
        return None, "ERROR"

    status = _coverage_status(data)
    if status == "PARTIAL_COVERAGE":
        warnings.append(f"{label}仅覆盖部分查询时间（PARTIAL_COVERAGE）")
    elif status == "NOT_CONFIGURED":
        warnings.append(f"{label}未配置有效设备绑定（NOT_CONFIGURED）")
    elif status == "NEEDS_REVIEW":
        warnings.append(f"{label}设备绑定需要人工确认（NEEDS_REVIEW）")
        return None, status
    elif status == "DATA_INCONSISTENT":
        warnings.append(f"{label}设备绑定数据不一致（DATA_INCONSISTENT）")
        return None, status
    return data, status


def _coverage_status(data: Any) -> str:
    if not isinstance(data, dict):
        return "NORMAL"
    coverage = data.get("coverage")
    if not isinstance(coverage, dict):
        return "NORMAL"
    status = str(coverage.get("status") or "NORMAL").strip().upper()
    return status or "NORMAL"


def _status_from_error_code(error_code: str) -> str:
    normalized = str(error_code or "").strip().upper()
    status_by_error = {
        "RICE_STAGE_BINDING_NEEDS_MANUAL_REVIEW": "NEEDS_REVIEW",
        "RICE_STAGE_BINDING_NOT_AVAILABLE": "NOT_CONFIGURED",
        "BINDING_DATA_INCONSISTENT": "DATA_INCONSISTENT",
        "BOUNDARY_DATA_INCONSISTENT": "BOUNDARY_DATA_INCONSISTENT",
        "BOUNDARY_NOT_CONFIGURED": "NOT_CONFIGURED",
        "BOUNDARY_COVERAGE_GAP": "BOUNDARY_COVERAGE_GAP",
        "NO_PERMISSION": "NO_PERMISSION",
        "AREA_NOT_FOUND": "AREA_NOT_FOUND",
    }
    return status_by_error.get(normalized, normalized or "ERROR")


def _fetch_area_rice_stage(
    *,
    client: RiceApiClient,
    area_id: str,
    start_date: str,
    end_date: str,
    warnings: list[str],
) -> tuple[Any, dict[str, Any]]:
    preset = ""
    crop = ""
    preset_payload, preset_status = _fetch_area_optional(
        client=client,
        path="/aipp/area-device-presets",
        params={"areaId": area_id, "date": end_date},
        label="生育期点位预设",
        warnings=warnings,
    )
    if isinstance(preset_payload, dict):
        presets = preset_payload.get("presets")
        if isinstance(presets, list) and presets:
            first_item = presets[0] if isinstance(presets[0], dict) else {}
            preset = str(first_item.get("preset") or "").strip()
            crop = str(first_item.get("crop") or "").strip()

    if preset_status in {"NEEDS_REVIEW", "DATA_INCONSISTENT", "NO_PERMISSION", "AREA_NOT_FOUND"}:
        return None, {
            "source": "area",
            "preset": preset,
            "crop": crop,
            "binding_status": preset_status,
            "preset_status": preset_status,
        }

    history_start_time, history_end_time = _area_history_time_range(
        start_date=start_date,
        end_date=end_date,
    )
    params = {
        "areaId": area_id,
        "startTime": history_start_time,
        "endTime": history_end_time,
        "includeBindingMeta": False,
    }
    if preset:
        params["preset"] = preset

    payload, binding_status = _fetch_area_optional(
        client=client,
        path="/aipp/area-rice-stage",
        params=params,
        label="生育期",
        warnings=warnings,
    )
    return payload, {
        "source": "area",
        "preset": preset,
        "crop": crop,
        "binding_status": binding_status,
        "preset_status": preset_status,
    }


def _build_met_overview(data: Any, *, binding_status: str) -> dict[str, Any]:
    # 按 ScreenView.vue 保持原始字段口径，不在 capability 内做统计聚合
    if not isinstance(data, dict):
        return {"xticks": [], "temp": [], "hum": [], "binding_status": binding_status, "coverage": {}}
    return {
        "xticks": _as_list(data.get("xticks")),
        "temp": _as_list(data.get("temp")),
        "hum": _as_list(data.get("hum")),
        "binding_status": binding_status,
        "coverage": data.get("coverage") if isinstance(data.get("coverage"), dict) else {},
    }


def _build_insect_overview(data: Any) -> dict[str, Any]:
    # 按 ScreenView.vue 保持原始字段口径，不在 capability 内做统计聚合
    if not isinstance(data, dict):
        return {
            "xticks": [],
            "ehm": [],
            "dzjym": [],
            "hefs": [],
            "all_species_aggregate": {
                "species": [],
                "total_cumulative": 0,
                "global_max": 0,
            },
        }
    aggregate = _build_insect_aggregate(data)
    return {
        "xticks": _as_list(data.get("xticks")),
        "ehm": _as_list(data.get("ehm")),
        "dzjym": _as_list(data.get("dzjym")),
        "hefs": _as_list(data.get("hefs")),
        "all_species_aggregate": aggregate,
    }


def _build_rice_stage_overview(data: Any, *, stage_meta: dict[str, Any]) -> dict[str, Any]:
    xticks: list[Any] = []
    stage: list[Any] = []
    if isinstance(data, dict):
        xticks = _as_list(data.get("xticks"))
        stage = _as_list(data.get("stage"))

    return {
        "xticks": xticks,
        "stage": stage,
        "source": str(stage_meta.get("source") or ""),
        "preset": str(stage_meta.get("preset") or ""),
        "crop": str(stage_meta.get("crop") or ""),
        "binding_status": str(stage_meta.get("binding_status") or "NORMAL"),
        "preset_status": str(stage_meta.get("preset_status") or "NORMAL"),
        "coverage": data.get("coverage") if isinstance(data, dict) and isinstance(data.get("coverage"), dict) else {},
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _build_suggest_overview(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "sugF": [],
            "sugD": [],
            "sugI": [],
            "sug_data": [[], [], []],
        }

    sug_f_all = _normalize_suggest_list(data.get("sugF"))
    sug_d_all = _normalize_suggest_list(data.get("sugD"))
    sug_i_all = _normalize_suggest_list(data.get("sugI"))
    return {
        "sugF": sug_f_all,
        "sugD": sug_d_all,
        "sugI": sug_i_all,
        "sug_data": [sug_f_all, sug_d_all, sug_i_all],
    }


def _normalize_suggest_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return _remove_none_like_frontend(value)


def _build_insect_aggregate(data: dict[str, Any]) -> dict[str, Any]:
    species_stats: list[dict[str, Any]] = []
    total_cumulative = 0
    global_max = 0.0

    for key, value in data.items():
        if key == "xticks" or not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            series = item.get("data")
            if not isinstance(series, list):
                continue

            numbers = [num for num in (_to_float(cell) for cell in series) if num is not None]
            cumulative = _round_number(sum(numbers)) if numbers else 0
            max_value = _round_number(max(numbers)) if numbers else 0

            total_cumulative += cumulative if isinstance(cumulative, (int, float)) else 0
            if isinstance(max_value, (int, float)):
                global_max = max(global_max, float(max_value))

            species_stats.append(
                {
                    "name": name,
                    "key": key,
                    "cumulative": cumulative,
                    "max": max_value,
                }
            )

    return {
        "species": species_stats,
        "total_cumulative": _round_number(float(total_cumulative)),
        "global_max": _round_number(global_max),
    }


def _remove_none_like_frontend(value: list[Any]) -> list[Any]:
    # 对齐 ScreenView.vue 的 removeNone 语义，并补充空白字符串过滤
    result: list[Any] = []
    for item in value:
        if isinstance(item, list):
            if any(_has_suggest_value(sub_item) for sub_item in item):
                result.append(item)
            continue
        if _has_suggest_value(item):
            result.append(item)
    return result


def _has_suggest_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _compact_time_axes(
    *,
    met_overview: dict[str, Any],
    insect_overview: dict[str, Any],
    rice_stage_overview: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    axis_registry: dict[str, str] = {}
    time_axes: dict[str, Any] = {}

    def _register_axis(xticks: list[Any]) -> str:
        compact = _compact_daily_xticks(xticks)
        key = json.dumps(compact, ensure_ascii=False, sort_keys=True)
        axis_ref = axis_registry.get(key)
        if axis_ref:
            return axis_ref
        axis_ref = f"axis_{len(axis_registry) + 1}"
        axis_registry[key] = axis_ref
        time_axes[axis_ref] = compact
        return axis_ref

    def _bind_axis_ref(payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(payload)
        xticks = _as_list(merged.pop("xticks", []))
        merged["axis_ref"] = _register_axis(xticks)
        return merged

    return (
        time_axes,
        _bind_axis_ref(met_overview),
        _bind_axis_ref(insect_overview),
        _bind_axis_ref(rice_stage_overview),
    )


def _compact_daily_xticks(xticks: list[Any]) -> dict[str, Any]:
    values = [str(item).strip() for item in xticks if str(item).strip()]
    if not values:
        return {"type": "daily", "start": "", "end": "", "count": 0}

    parsed_dates: list[date] = []
    for item in values:
        try:
            parsed_dates.append(datetime.strptime(item, "%Y-%m-%d").date())
        except ValueError:
            return {"type": "list", "values": values, "count": len(values)}

    if any(parsed_dates[index] > parsed_dates[index + 1] for index in range(len(parsed_dates) - 1)):
        return {"type": "list", "values": values, "count": len(values)}

    start = parsed_dates[0]
    end = parsed_dates[-1]
    day_count = (end - start).days + 1
    full_dates = [(start + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(day_count)]
    present = set(values)
    missing = [item for item in full_dates if item not in present]

    if len(missing) > len(values):
        return {"type": "list", "values": values, "count": len(values)}

    compact: dict[str, Any] = {
        "type": "daily",
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "count": len(values),
    }
    if missing:
        compact["missing"] = missing
    duplicate_count = len(values) - len(present)
    if duplicate_count > 0:
        compact["duplicates"] = duplicate_count
    return compact


def _build_summary(
    *,
    area_name: str,
    start_date: str,
    end_date: str,
    met_overview: dict[str, Any],
    insect_overview: dict[str, Any],
    suggest_overview: dict[str, Any],
    warnings: list[str],
) -> str:
    lines = [f"基地“{area_name}”数据已获取（{start_date} ~ {end_date}）。"]

    temp_max = _extract_named_series_last(met_overview.get("temp"), ("最高",))
    temp_mean = _extract_named_series_last(met_overview.get("temp"), ("平均",))
    temp_min = _extract_named_series_last(met_overview.get("temp"), ("最低",))
    hum_max = _extract_named_series_last(met_overview.get("hum"), ("最高",))
    hum_mean = _extract_named_series_last(met_overview.get("hum"), ("平均",))
    hum_min = _extract_named_series_last(met_overview.get("hum"), ("最低",))

    temp_facts: list[str] = []
    if temp_max is not None:
        temp_facts.append(f"最高 {temp_max}°C")
    if temp_mean is not None:
        temp_facts.append(f"平均 {temp_mean}°C")
    if temp_min is not None:
        temp_facts.append(f"最低 {temp_min}°C")
    if temp_facts:
        lines.append("温度：" + "，".join(temp_facts) + "。")

    hum_facts: list[str] = []
    if hum_max is not None:
        hum_facts.append(f"最高 {hum_max}%")
    if hum_mean is not None:
        hum_facts.append(f"平均 {hum_mean}%")
    if hum_min is not None:
        hum_facts.append(f"最低 {hum_min}%")
    if hum_facts:
        lines.append("湿度：" + "，".join(hum_facts) + "。")

    latest_ehm = _extract_named_series_last(insect_overview.get("ehm"), ("二化螟",))
    latest_dzjym = _extract_named_series_last(insect_overview.get("dzjym"), ("稻纵卷叶螟",))
    latest_hefs = _extract_named_series_last(insect_overview.get("hefs"), ("褐飞虱",))
    insect_facts: list[str] = []
    if latest_ehm is not None:
        insect_facts.append(f"二化螟 {latest_ehm}")
    if latest_dzjym is not None:
        insect_facts.append(f"稻纵卷叶螟 {latest_dzjym}")
    if latest_hefs is not None:
        insect_facts.append(f"褐飞虱 {latest_hefs}")
    if insect_facts:
        lines.append("虫情：" + "，".join(insect_facts) + "。")

    suggest_values = suggest_overview.get("sug_data")
    if isinstance(suggest_values, list):
        rendered_suggest = [_stringify_suggest(value) for value in suggest_values[:3]]
        if any(item != "-" for item in rendered_suggest):
            lines.append(f"农事建议（施肥/ 病害/ 虫害）：{rendered_suggest[0]} / {rendered_suggest[1]} / {rendered_suggest[2]}。")

    if warnings:
        lines.append("部分数据未获取：" + "；".join(warnings[:3]) + "。")

    return " ".join(lines)


def _extract_named_series_last(series_group: Any, name_keywords: tuple[str, ...]) -> float | int | None:
    if not isinstance(series_group, list):
        return None

    normalized_keywords = tuple(keyword.replace(" ", "").strip() for keyword in name_keywords if keyword)
    for item in series_group:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").replace(" ", "").strip()
        if normalized_keywords and not any(keyword in name for keyword in normalized_keywords):
            continue
        return _extract_last_number(item.get("data"))
    return None


def _extract_last_number(data: Any) -> float | int | None:
    if not isinstance(data, list):
        return None
    for item in reversed(data):
        number = _to_float(item)
        if number is not None:
            return _round_number(number)
    return None


def _stringify_suggest(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(parts) if parts else "-"
    text = str(value).strip()
    return text or "-"


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
