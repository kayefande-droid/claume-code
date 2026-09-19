"""claume bootstrap — first-run key checks.

claume runs exclusively on **NVIDIA NIM** through the local free-claume
proxy. There are no built-in provider keys anymore: run `claume` once and
the interactive setup asks for your free NVIDIA API key (build.nvidia.com),
or set it with `/key NVIDIA_API_KEY <key>` / the proxy admin UI.
"""
from __future__ import annotations

from typing import List

# No built-in keys — NVIDIA NIM only. Kept as an empty map so any existing
# callers keep working.
BUILTIN_KEYS = {}

# Keys that must exist in the vault for the default provider to work.
_REQUIRED_FOR_DEFAULT = ("NVIDIA_API_KEY",)


def seed_builtin_keys() -> List[str]:
    """No-op for key seeding (kept for API compatibility) — but migrates any
    legacy provider=tokenin config to the NVIDIA NIM default."""
    try:
        from . import config

        cfg = config.Config()
        if str(cfg.get("provider", "")) == "tokenin":
            cfg.set("provider", "nvidia")
            cfg.set("model", config.Config.DEFAULTS["model"])
            return ["migrated: provider tokenin → nvidia (NIM only)"]
    except Exception:
        pass
    return []


def missing_for_default_provider() -> List[str]:
    """Built-in keys missing from the vault (should normally be [])."""
    try:
        from . import config, keyvault

        cfg = config.Config()
        if cfg.get("provider") != "nvidia":
            return []
        missing = []
        for name in _REQUIRED_FOR_DEFAULT:
            if not keyvault.resolve_key(name):
                missing.append(name)
        return missing
    except Exception:
        return []
