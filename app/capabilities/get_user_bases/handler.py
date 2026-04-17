from __future__ import annotations

import base64
from datetime import datetime, timedelta
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import urljoin

import requests

from app.schemas.common import CapabilityExecutionError
from app.services.env_config import get_config_value
from app.services.progress_writer import ProgressWriter


VALIDATE_AUTH_STEP_ID = "validate_auth_context"
FETCH_AREAS_STEP_ID = "fetch_user_areas"
FORMAT_RESULT_STEP_ID = "format_area_result"

VALIDATE_AUTH_LABEL = "校验用户上下文"
FETCH_AREAS_LABEL = "查询用户基地列表"
FORMAT_RESULT_LABEL = "整理基地结果"

SECRET_KEY = "jlsdjfWeer12341"
ALGORITHM = "HS256"
DEBUG_PREFIX = "[capability:get_user_bases]"


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


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def _normalize_area_item(area: dict[str, Any]) -> dict[str, str]:
    return {
        "area_id": str(area.get("id") or "").strip(),
        "area_name": str(area.get("area_name") or "").strip(),
        "met_num": str(area.get("met_num") or "").strip(),
        "insects_num": str(area.get("insects_num") or "").strip(),
        "ricestage_num": str(area.get("ricestage_num") or "").strip(),
    }


async def handle(input: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    writer = ProgressWriter.from_context(context)

    writer.running(VALIDATE_AUTH_STEP_ID, VALIDATE_AUTH_LABEL)
    action = str(input.get("action") or "list").strip().lower() or "list"
    if action != "list":
        writer.error(VALIDATE_AUTH_STEP_ID, VALIDATE_AUTH_LABEL)
        raise CapabilityExecutionError(code="invalid_input", message="field 'action' must be 'list'")

    access_token, _user_id = _build_access_token_from_context(context=context)
    writer.success(VALIDATE_AUTH_STEP_ID, VALIDATE_AUTH_LABEL)

    area_name_filter = str(input.get("area_name") or "").strip()
    # print(f"{DEBUG_PREFIX} input action={action} area_name={area_name_filter!r} user_id={_user_id}")

    client = RiceApiClient(
        base_url=_api_base_url(),
        access_token=access_token,
        timeout_seconds=_api_timeout(),
    )

    writer.running(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)
    try:
        rows = _fetch_all_areas(client=client, area_name_filter=area_name_filter)
    except requests.HTTPError as exc:
        writer.error(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code in {401, 403}:
            raise CapabilityExecutionError(code="auth_required", message="用户认证已过期，请稍后重试") from exc
        raise CapabilityExecutionError(code="area_query_failed", message=f"查询基地列表失败（HTTP {status_code}）") from exc

    # print(f"{DEBUG_PREFIX} area_rows_fetched raw_count={len(rows)}")
    areas = [
        item
        for item in (_normalize_area_item(row) for row in rows)
        if item["area_id"] and item["area_name"]
    ]
    writer.success(FETCH_AREAS_STEP_ID, FETCH_AREAS_LABEL)

    writer.running(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    area_count = len(areas)
    has_multiple_areas = area_count > 1

    # print(f"{DEBUG_PREFIX} area_result_count={area_count} has_multiple={has_multiple_areas}")
    if area_count == 0:
        summary = "当前账号没有可访问基地。"
    elif area_name_filter:
        summary = f"按基地名称“{area_name_filter}”筛选到 {area_count} 个可访问基地。"
    else:
        summary = f"当前账号可访问 {area_count} 个基地。"

    writer.success(FORMAT_RESULT_STEP_ID, FORMAT_RESULT_LABEL)
    return {
        "summary": summary,
        "area_count": area_count,
        "has_multiple_areas": has_multiple_areas,
        "areas": areas,
    }
