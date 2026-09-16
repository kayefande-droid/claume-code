"""claume bootstrap — built-in free keys so v3 works out of the box.

claume v3 defaults to the **tokenin** provider (https://tokenin.my.id/v1 —
OpenAI-compatible community pool of free models). A community key ships with
claume so the very first `claume` run talks to a model without any setup.
Users can override it anytime with `/key TOKENIN_API_KEY <their own>`.
"""
from __future__ import annotations

from typing import List

# Built-in community keys (name → value). Seeded into the vault on boot if
# absent — the vault, not the source, stays the single place keys live.
BUILTIN_KEYS = {
    "TOKENIN_API_KEY": "sk-06f1ac0102a33b6cf55cf37b98421e6612913744",
}

# Keys that must exist in the vault for the default provider to work.
_REQUIRED_FOR_DEFAULT = ("TOKENIN_API_KEY",)


def seed_builtin_keys() -> List[str]:
    """Vault any built-in keys that are missing. Returns names seeded."""
    seeded: List[str] = []
    try:
        from . import config, keyvault

        config.claume_dir().mkdir(parents=True, exist_ok=True)
        for name, value in BUILTIN_KEYS.items():
            if keyvault.get_key(name):
                continue  # user set their own — never overwrite
            keyvault.set_key(name, value)
            seeded.append(name)
    except Exception:
        pass
    return seeded


def missing_for_default_provider() -> List[str]:
    """Built-in keys missing from the vault (should normally be [])."""
    try:
        from . import config, keyvault

        cfg = config.Config()
        if cfg.get("provider") != "tokenin":
            return []
        vault = cfg.get("key_vault", {}) or {}
        return [n for n in _REQUIRED_FOR_DEFAULT if not vault.get(n)]
    except Exception:
        return []
