from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

import requests


BASE_URL = "http://115.239.197.198:8688/chat/"
LOGIN_URL = "http://115.239.197.198:8688/login"
USERNAME = "zzg123"
PASSWORD = "Cj_66666"
DEFAULT_TOP_K = 5
REQUEST_TIMEOUT = 15
RICE_HINT_PREFIX = "水稻病虫害"
RICE_OBJECT_HINTS = {
    "大螟",
    "二化螟",
    "灰飞虱",
    "白背飞虱",
    "褐飞虱",
    "稻瘟病",
    "纹枯病",
    "白叶枯病",
    "条纹叶枯病",
}


class KnowledgeClientError(Exception):
    pass


def normalize_query(*, message: str, project: str, item_name: str | None = None) -> str:
    text = str(message or "").strip()
    if not text:
        return text

    if project != "rice":
        return text

    if "水稻" in text or "稻" in text or "病虫" in text or "虫害" in text or "病害" in text:
        return text

    item = str(item_name or "").strip()
    target = item or text

    if target in RICE_OBJECT_HINTS or any(name in text for name in RICE_OBJECT_HINTS):
        return f"{RICE_HINT_PREFIX} {text}"

    return text


def login() -> str:
    response = requests.post(
        LOGIN_URL,
        data={"username": USERNAME, "password": PASSWORD},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise KnowledgeClientError("login response is not an object")

    token = str(data.get("access_token") or "").strip()
    if not token:
        raise KnowledgeClientError("login response missing access_token")
    return token


def query_knowledge(
    *,
    message: str,
    project: str,
    top_k: int = DEFAULT_TOP_K,
    item_name: str | None = None,
) -> Any:
    token = login()
    normalized_message = normalize_query(message=message, project=project, item_name=item_name)
    url = urljoin(BASE_URL, "api/knowledge/query")
    response = requests.get(
        url,
        params={
            "message": normalized_message,
            "project": project,
            "top_k": top_k,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    try:
        return response.json()
    except ValueError:
        return response.text


def validate_upstream_result(raw_data: Any) -> None:
    if not isinstance(raw_data, dict):
        return

    code = raw_data.get("code")
    if code in (None, 200, "200"):
        return

    message = str(raw_data.get("msg") or raw_data.get("message") or "upstream knowledge query failed").strip()
    raise KnowledgeClientError(message)


def normalize_references(raw_data: Any) -> list[Any]:
    if isinstance(raw_data, dict):
        for key in ("reference_list", "references", "reference", "docs", "documents", "items", "data"):
            value = raw_data.get(key)
            if isinstance(value, list):
                return value
        return []

    if isinstance(raw_data, list):
        return raw_data

    return []


def extract_answer(raw_data: Any) -> str:
    if isinstance(raw_data, dict):
        data_value = raw_data.get("data")
        if isinstance(data_value, list):
            joined_text = _join_text_items(data_value)
            if joined_text:
                return joined_text

        for key in ("answer", "result", "summary", "content", "message", "text"):
            value = raw_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        references = normalize_references(raw_data)
        if references:
            return _stringify_data(references)

        return _stringify_data(raw_data)

    if isinstance(raw_data, list):
        return _stringify_data(raw_data)

    if isinstance(raw_data, str):
        return raw_data.strip()

    return _stringify_data(raw_data)


def _join_text_items(items: list[Any]) -> str:
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _stringify_data(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()
    try:
        return json.dumps(data, ensure_ascii=False)
    except TypeError:
        return str(data)
