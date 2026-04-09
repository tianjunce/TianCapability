from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any, Callable, Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup


WHITESPACE_RE = re.compile(r"\s+")
JSONP_RE = re.compile(r"^[^(]*\((?P<payload>.*)\)\s*;?\s*$", re.DOTALL)
ARTICLE_TIME_PATTERNS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m-%d %H:%M",
    "%m-%d",
    "%H:%M",
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    return WHITESPACE_RE.sub(" ", text).strip()


def clean_multiline_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value)).replace("\r\n", "\n").replace("\r", "\n")
    lines = [clean_text(line) for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n\n".join(lines).strip()


def strip_html_tags(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    return clean_text(BeautifulSoup(text, "html.parser").get_text(" ", strip=True))


def absolutize_url(url: str, base_url: str) -> str:
    cleaned = clean_text(url)
    if not cleaned:
        return ""
    return urljoin(base_url, cleaned)


def coerce_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("text", "marked", "name", "title", "content", "summary", "desc"):
            nested = clean_text(value.get(key))
            if nested:
                return nested
        return ""
    if isinstance(value, list):
        joined = " ".join(clean_text(item) for item in value if clean_text(item))
        return clean_text(joined)
    return clean_text(value)


def parse_publish_time(value: str | None) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None

    normalized = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", " ")
        .replace("/", "-")
        .replace("T", " ")
    )
    normalized = clean_text(normalized)
    now = datetime.now()

    for pattern in ARTICLE_TIME_PATTERNS:
        try:
            parsed = datetime.strptime(normalized, pattern)
        except ValueError:
            continue

        if pattern == "%m-%d %H:%M":
            return parsed.replace(year=now.year)
        if pattern == "%m-%d":
            return parsed.replace(year=now.year)
        if pattern == "%H:%M":
            return parsed.replace(year=now.year, month=now.month, day=now.day)
        return parsed

    return None


def compute_relevance(*, query: str, title: str, summary: str) -> float:
    normalized_query = clean_text(query).lower()
    if not normalized_query:
        return 0.0

    normalized_title = clean_text(title).lower()
    normalized_summary = clean_text(summary).lower()
    score = 0.0

    if normalized_query in normalized_title:
        score += 8.0
    if normalized_query in normalized_summary:
        score += 4.0

    token_candidates = [token for token in re.split(r"[\s,，。;；/|]+", normalized_query) if len(token) >= 2]
    if len(token_candidates) <= 1 and re.search(r"[\u4e00-\u9fff]", normalized_query) and len(normalized_query) >= 4:
        token_candidates = [normalized_query[index : index + 2] for index in range(len(normalized_query) - 1)]

    for token in dict.fromkeys(token_candidates):
        if token in normalized_title:
            score += 1.5
        if token in normalized_summary:
            score += 0.5

    return score


def summarize_paragraphs(paragraphs: Iterable[str], *, max_chars: int = 180) -> str:
    pieces: list[str] = []
    total = 0

    for paragraph in paragraphs:
        cleaned = clean_text(paragraph)
        if len(cleaned) < 12:
            continue
        pieces.append(cleaned)
        total += len(cleaned)
        if total >= max_chars or len(pieces) >= 3:
            break

    return clean_text(" ".join(pieces))[:max_chars]


def extract_detail_content(
    soup: BeautifulSoup,
    selectors: Iterable[str],
    *,
    max_chars: int = 6000,
) -> str:
    paragraphs: list[str] = []
    seen: set[str] = set()

    for selector in selectors:
        for element in soup.select(selector):
            cleaned = clean_text(element.get_text(" ", strip=True))
            if len(cleaned) < 10 or cleaned in seen:
                continue
            seen.add(cleaned)
            paragraphs.append(cleaned)

        if paragraphs:
            break

    if not paragraphs:
        for element in soup.select("article p, .article p, .content p, .main p, p"):
            cleaned = clean_text(element.get_text(" ", strip=True))
            if len(cleaned) < 10 or cleaned in seen:
                continue
            seen.add(cleaned)
            paragraphs.append(cleaned)

    if not paragraphs:
        return ""

    parts: list[str] = []
    total = 0
    for paragraph in paragraphs:
        parts.append(paragraph)
        total += len(paragraph)
        if total >= max_chars:
            break

    return clean_multiline_text("\n\n".join(parts))[:max_chars]


def find_json_blob(script_text: str) -> str | None:
    text = script_text.strip()
    if not text:
        return None

    start = -1
    for marker in ("{", "["):
        marker_index = text.find(marker)
        if marker_index >= 0 and (start < 0 or marker_index < start):
            start = marker_index

    if start < 0:
        return None

    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == opening:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def extract_json_objects(html_text: str) -> list[Any]:
    soup = BeautifulSoup(html_text, "html.parser")
    objects: list[Any] = []

    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        if not script_text or "{" not in script_text:
            continue
        blob = find_json_blob(script_text)
        if not blob:
            continue
        try:
            objects.append(json.loads(blob))
        except json.JSONDecodeError:
            continue

    return objects


def walk_json_nodes(data: Any) -> Iterable[dict[str, Any]]:
    stack: list[Any] = [data]

    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
            continue
        if isinstance(current, list):
            stack.extend(current)


def _pick_first(mapping: dict[str, Any], field_names: tuple[str, ...]) -> Any:
    for field_name in field_names:
        if field_name in mapping and mapping[field_name] not in (None, "", [], {}):
            return mapping[field_name]
    return None


def extract_result_candidates_from_json(
    *,
    html_text: str,
    base_url: str,
    site_name: str,
    is_article_url: Callable[[str], bool],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    for json_object in extract_json_objects(html_text):
        for node in walk_json_nodes(json_object):
            title = coerce_text(_pick_first(node, ("title", "name", "doc_title")))
            url = absolutize_url(coerce_text(_pick_first(node, ("url", "share_url", "open_url"))), base_url)
            if not title or not url or not is_article_url(url):
                continue

            summary = coerce_text(_pick_first(node, ("summary", "content", "abstract", "desc", "introduction")))
            source = coerce_text(_pick_first(node, ("source", "media_name", "media", "site_name", "account_name"))) or site_name
            publish_time = coerce_text(
                _pick_first(
                    node,
                    (
                        "publish_time",
                        "publishTime",
                        "newsTime",
                        "display_time",
                        "time",
                        "datetime",
                    ),
                )
            )
            candidates.append(
                {
                    "title": title,
                    "url": url,
                    "source": source,
                    "publish_time": publish_time,
                    "summary": summary,
                }
            )

    return candidates


def extract_result_candidates_from_anchors(
    *,
    html_text: str,
    base_url: str,
    site_name: str,
    is_article_url: Callable[[str], bool],
) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    candidates: list[dict[str, str]] = []

    for anchor in soup.select("a[href]"):
        url = absolutize_url(anchor.get("href", ""), base_url)
        if not url or not is_article_url(url):
            continue

        title = clean_text(anchor.get("title")) or clean_text(anchor.get_text(" ", strip=True))
        if len(title) < 6:
            continue

        parent = anchor.parent
        publish_time = ""
        if parent is not None:
            time_tag = parent.find(["time", "b", "i"])
            if time_tag is not None:
                publish_time = clean_text(time_tag.get_text(" ", strip=True))

        candidates.append(
            {
                "title": title,
                "url": url,
                "source": site_name,
                "publish_time": publish_time,
                "summary": "",
            }
        )

    return candidates


def extract_meta_content(soup: BeautifulSoup, names: Iterable[str]) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
        if tag and tag.get("content"):
            content = clean_text(tag.get("content"))
            if content:
                return content
    return ""


def extract_detail_summary(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for selector in selectors:
        paragraphs = [element.get_text(" ", strip=True) for element in soup.select(selector)]
        summary = summarize_paragraphs(paragraphs)
        if summary:
            return summary

    fallback_paragraphs = [element.get_text(" ", strip=True) for element in soup.select("article p, .article p, .content p, .main p, p")]
    return summarize_paragraphs(fallback_paragraphs)


def parse_jsonp_payload(payload: str) -> Any:
    text = str(payload or "").strip()
    if not text:
        raise ValueError("empty jsonp payload")

    match = JSONP_RE.match(text)
    if not match:
        raise ValueError("invalid jsonp payload")

    return json.loads(match.group("payload"))
