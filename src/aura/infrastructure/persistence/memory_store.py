from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.user_file = self.memory_dir / "user_profile.json"
        self.projects_file = self.memory_dir / "projects.json"
        self.logs_file = self.memory_dir / "action_log.jsonl"
        self._lock = threading.RLock()
        self._json_cache: dict[Path, tuple[int, Any]] = {}
        self._logs_cache_mtime_ns: int | None = None
        self._logs_cache: list[dict[str, Any]] = []

    def _read_json(self, path: Path, default: Any) -> Any:
        with self._lock:
            if not path.exists():
                return default
            mtime_ns = path.stat().st_mtime_ns
            cached = self._json_cache.get(path)
            if cached is not None and cached[0] == mtime_ns:
                return copy.deepcopy(cached[1])
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._json_cache[path] = (mtime_ns, data)
            return copy.deepcopy(data)

    def _write_json(self, path: Path, data: Any) -> None:
        with self._lock:
            temp_path = path.with_suffix(path.suffix + ".tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(path)
            self._json_cache[path] = (path.stat().st_mtime_ns, copy.deepcopy(data))

    def get_user_profile(self) -> dict[str, Any]:
        return self._read_json(self.user_file, {})

    def update_user_profile(self, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            profile = self.get_user_profile()
            profile.update(updates)
            self._write_json(self.user_file, profile)
            return profile

    def get_projects(self) -> dict[str, Any]:
        return self._read_json(self.projects_file, {})

    def upsert_project(self, key: str, project_data: dict[str, Any]) -> None:
        with self._lock:
            projects = self.get_projects()
            projects[key] = project_data
            self._write_json(self.projects_file, projects)

    def append_log(self, event: dict[str, Any]) -> None:
        with self._lock:
            with self.logs_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=True) + "\n")
            if self._logs_cache_mtime_ns is not None:
                self._logs_cache.append(event)
                self._logs_cache_mtime_ns = self.logs_file.stat().st_mtime_ns

    def read_recent_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            if not self.logs_file.exists():
                return []
            mtime_ns = self.logs_file.stat().st_mtime_ns
            if self._logs_cache_mtime_ns != mtime_ns:
                rows: list[dict[str, Any]] = []
                with self.logs_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        text = line.strip()
                        if not text:
                            continue
                        try:
                            payload = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(payload, dict):
                            rows.append(payload)
                self._logs_cache = rows
                self._logs_cache_mtime_ns = mtime_ns
            rows = list(self._logs_cache)
            return rows if limit <= 0 else rows[-limit:]

    def get_project_by_keyword(self, terms: list[str]) -> dict | None:
        """Return the first project whose key contains any of the given terms.

        Returns None if no projects exist or no keyword matches.
        """
        if not terms:
            return None
        projects = self.get_projects()
        terms_lower = [t.lower() for t in terms if t]
        for key, data in projects.items():
            key_lower = key.lower()
            if any(t in key_lower for t in terms_lower):
                matched = dict(data)
                matched["_key"] = key
                return matched
        return None
