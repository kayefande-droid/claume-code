"""Safety layer: classify commands as safe / caution / destructive.

The agent consults this before executing shell commands. Destructive
commands require explicit user confirmation unless auto_mode is on *and*
the user disabled confirmations (we never silently auto-accept rm -rf).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

DESTRUCTIVE_PATTERNS: List[str] = [
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b",
    r"\brm\s+-[a-zA-Z]*r",
    r"\bdel\s+/[sq]",
    r"\brmdir\s+/s",
    r"\bRemove-Item\b.*-Recurse",
    r"\bformat\b\s+[a-zA-Z]:",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd[a-z]",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-zA-Z]*f",
    r"\bdrop\s+(database|table)\b",
    r"\btruncate\s+table\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\btaskkill\s+/f\b",
    r"\bkill\s+-9\b",
    r"\bchmod\s+-R\s+777\b",
    r"\breg\s+delete\b",
    r"\bvssadmin\s+delete",
    r"\bcipher\s+/w",
]

CAUTION_PATTERNS: List[str] = [
    r"\bnpm\s+(install|i)\b",
    r"\bpip\s+install\b",
    r"\bcurl\b.*\|\s*(ba)?sh",
    r"\biwr\b.*\|\s*iex",
    r"\bInvoke-WebRequest\b.*Invoke-Expression",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bgit\s+(push|reset|checkout\s+--)\b",
    r"\bdocker\s+(rm|rmi|system\s+prune)\b",
    r"\bmv\b\s+",
    r"\bcurl\s+-o\b",
    r"\bwinget\s+(install|uninstall)\b",
    r"\bscoop\s+(install|uninstall)\b",
    r"\bchoco\s+(install|uninstall)\b",
    r"\bapt\s+(remove|purge|autoremove)\b",
]


@dataclass
class SafetyVerdict:
    level: str  # "safe" | "caution" | "destructive"
    reason: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return self.level in ("caution", "destructive")


def classify_command(command: str) -> SafetyVerdict:
    cmd = command.strip()
    low = cmd.lower()

    if not cmd:
        return SafetyVerdict("safe")

    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, low):
            return SafetyVerdict("destructive", f"matches dangerous pattern: {pattern}")

    for pattern in CAUTION_PATTERNS:
        if re.search(pattern, low):
            return SafetyVerdict("caution", "modifies system state")

    return SafetyVerdict("safe")


def is_destructive(command: str) -> bool:
    return classify_command(command).level == "destructive"


def redact_secrets(text: str, secrets: Optional[List[str]] = None) -> str:
    """Scrub known secret values out of any text destined for the model."""
    if not secrets:
        return text
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    return text
