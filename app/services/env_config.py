from __future__ import annotations

import os
from pathlib import Path


def get_config_value(name: str, default: str = "") -> str:
    direct_value = os.getenv(name)
    if direct_value is not None and direct_value.strip():
        return direct_value.strip()

    dotenv_values = _load_dotenv_values()
    return str(dotenv_values.get(name, default)).strip()


def _load_dotenv_values() -> dict[str, str]:
    merged_values: dict[str, str] = {}
    for path in _dotenv_candidates():
        if not path.exists() or not path.is_file():
            continue
        merged_values.update(_parse_dotenv_file(path))
    return merged_values


def _dotenv_candidates() -> list[Path]:
    root = _config_root()
    return [
        root / ".env",
        root / ".env.local",
    ]


def _config_root() -> Path:
    configured_root = os.getenv("CAPABILITY_CONFIG_DIR", "").strip()
    if configured_root:
        return Path(configured_root).expanduser()
    return Path(__file__).resolve().parents[2]


def _parse_dotenv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        values[key] = _strip_quotes(value)
    return values


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
