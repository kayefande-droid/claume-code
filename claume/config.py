"""Persistent configuration for claume-code.

Everything lives under ``%USERPROFILE%\\.claume`` on Windows (or
``~/.claume`` elsewhere) so the tool works from any working directory.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

APP_DIR_NAME = ".claume"

# NVIDIA NIM models confirmed gone (410 Gone - end of life).
DEAD_MODELS = {
    "meta/llama-3.3-70b-instruct",   # EOL 2026-08-26
}

# Deliberately kept out of any cloud sync folder; USERS/admin style layout.
def home_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def claume_dir() -> Path:
    return home_dir() / APP_DIR_NAME


def proxy_state_path() -> Path:
    return claume_dir() / "proxy.json"


def log_dir() -> Path:
    return claume_dir() / "logs"


def log_file_path() -> Path:
    return log_dir() / "claume.log"


def sessions_dir() -> Path:
    return claume_dir() / "sessions"


def skills_dir() -> Path:
    return claume_dir() / "skills"


def mcp_dir() ->Path:
    return claume_dir() / "mcp"


def config_path() -> Path:
    return claume_dir() / "config.json"


def env_path() -> Path:
    return claume_dir() / ".env"


class Config:
    """JSON-backed settings store with dot-key access."""

    DEFAULTS: Dict[str, Any] = {
        "provider": "nvidia",
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "model_fallbacks": [],
        "effort": "balanced",
        "auto_mode": False,
        "classifier_enabled": True,
        "proxy_port": 8000,
        "proxy_host": "127.0.0.1",
        "max_steps": 24,
        "max_tool_calls_per_turn": 40,
        "stream": True,
        "theme": "nvidia-green",
        "pixel_animations": True,
        "confirm_destructive": True,
        "history_limit": 120,
        "context_tokens_soft_limit": 96_000,
        "mcp_servers": {},
        "key_vault": {},
        "last_version": "",
        "first_run_done": False,
    }

    def __init__(self) -> None:
        self._path = config_path()
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            else:
                self._data = {}
        except Exception:
            self._data = {}
        # Merge defaults for forward compatibility.
        for key, value in self.DEFAULTS.items():
            self._data.setdefault(key, value)
        # One-way migration: NVIDIA has retired these models (HTTP 410 EOL).
        if self._data.get("model") in DEAD_MODELS:
            self._data["model"] = self.DEFAULTS["model"]
            try:
                self.save()
            except Exception:
                pass

    def save(self) -> None:
        claume_dir().mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8"
        )

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.save()

    # Convenience -------------------------------------------------------
    @property
    def model(self) -> str:
        return str(self.get("model"))

    @property
    def effort(self) -> str:
        return str(self.get("effort"))

    @property
    def auto_mode(self) -> bool:
        return bool(self.get("auto_mode"))


def load_proxy_state() -> Optional[Dict[str, Any]]:
    try:
        if proxy_state_path().exists():
            return json.loads(proxy_state_path().read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def save_proxy_state(state: Dict[str, Any]) -> None:
    claume_dir().mkdir(parents=True, exist_ok=True)
    proxy_state_path().write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


def clear_proxy_state() -> None:
    try:
        proxy_state_path().unlink(missing_ok=True)
    except Exception:
        pass
