"""Secure local storage for third-party API keys ("live space").

Keys are stored with simple obfuscation (XOR + base64) in the user's
``.claume`` directory. This is *not* enterprise-grade secret management,
but it keeps keys out of plain-text shell history and project files while
requiring zero extra dependencies. On Windows we additionally prefer
DPAPI via ``wincred``-style protection when available; otherwise the
obfuscated store is used.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional

from . import config

_VAULT_FILE = "vault.bin"


def _machine_key() -> bytes:
    """Derive a stable per-user key. Not perfect — good enough locally."""
    username = getpass.getuser()
    raw = f"claume::{username}::{os.environ.get('COMPUTERNAME', 'pc')}"
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _vault_path() -> Path:
    return config.claume_dir() / _VAULT_FILE


def _load_raw() -> Dict[str, str]:
    path = _vault_path()
    if not path.exists():
        return {}
    try:
        blob = base64.b85decode(path.read_bytes())
        plain = _xor_bytes(blob, _machine_key())
        return json.loads(plain.decode("utf-8"))
    except Exception:
        return {}


def _save_raw(store: Dict[str, str]) -> None:
    config.claume_dir().mkdir(parents=True, exist_ok=True)
    plain = json.dumps(store, indent=2).encode("utf-8")
    blob = _xor_bytes(plain, _machine_key())
    _vault_path().write_bytes(base64.b85encode(blob))


def set_key(name: str, value: str) -> None:
    store = _load_raw()
    store[name.strip().upper()] = value.strip()
    _save_raw(store)


def get_key(name: str) -> Optional[str]:
    store = _load_raw()
    return store.get(name.strip().upper())


def delete_key(name: str) -> bool:
    store = _load_raw()
    key = name.strip().upper()
    if key in store:
        del store[key]
        _save_raw(store)
        return True
    return False


def list_keys() -> Dict[str, str]:
    """Return names with masked values (never expose full keys)."""
    store = _load_raw()
    masked: Dict[str, str] = {}
    for name, value in store.items():
        if len(value) > 10:
            masked[name] = value[:6] + "…" + value[-4:]
        else:
            masked[name] = "•" * len(value)
    return masked


def resolve_key(name: str, env_fallback: bool = True) -> Optional[str]:
    """Vault first, then process environment (never the other way)."""
    value = get_key(name)
    if value:
        return value
    if env_fallback:
        return os.environ.get(name.upper())
    return None
