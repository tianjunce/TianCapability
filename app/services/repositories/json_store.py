from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar


T = TypeVar("T")
_STORE_LOCKS: dict[str, threading.Lock] = {}
_STORE_LOCKS_GUARD = threading.Lock()


def get_runtime_data_dir() -> Path:
    configured_path = os.getenv("CAPABILITY_DATA_DIR", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    return Path(__file__).resolve().parents[3] / "runtime-data"


def _lock_for_path(path: Path) -> threading.Lock:
    lock_key = str(path.resolve())
    with _STORE_LOCKS_GUARD:
        lock = _STORE_LOCKS.get(lock_key)
        if lock is None:
            lock = threading.Lock()
            _STORE_LOCKS[lock_key] = lock
        return lock


class JsonStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = _lock_for_path(path)

    def read(self, *, default_factory: Callable[[], T]) -> T:
        with self._lock:
            return self._read_unlocked(default_factory=default_factory)

    def update(
        self,
        *,
        default_factory: Callable[[], T],
        update_fn: Callable[[T], tuple[T, Any]],
    ) -> Any:
        with self._lock:
            current_value = self._read_unlocked(default_factory=default_factory)
            next_value, result = update_fn(current_value)
            self._write_unlocked(next_value)
            return result

    def _read_unlocked(self, *, default_factory: Callable[[], T]) -> T:
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except OSError:
            return default_factory()

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            return default_factory()

    def _write_unlocked(self, value: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
