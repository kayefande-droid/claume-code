"""claume reach — social posting, email, and payout plumbing.

Everything here is **bring-your-own-credentials**: claume never creates
accounts on your behalf without you supplying the keys, and every
outgoing action is confirmed in the REPL first (manual/accept modes) or
runs in auto mode with a full ledger trail.

Capabilities
------------
* **Telegram channel** — the ONLY fully-free, bot-first social platform:
  create a channel, add @BotFather's bot as admin, paste the token +
  chat_id, and claume can post text/images/video natively (Bot API is
  plain HTTPS — no SDK, stdlib only).
* **Email (SMTP/IMAP)** — Gmail app-password or any provider: send the
  verification/onboarding mail, check the inbox for verification links,
  extract them for you to open.
* **Payout ledger + MTN MoMo** — every monetization event is recorded in
  a local ledger; payouts target Cameroon MTN Mobile Money. MTN's
  official MoMo OpenAPI requires a paid business contract, so the
  default FREE rails are: Telegram Stars/TON withdrawal → P2P exchange
  → MTN MoMo, or manual transfer coordination by email. The module
  prepares the payout instruction; YOU approve the actual money move.
* **Passwords** — stdlib ``secrets``-based generator for app-specific
  passwords; nothing is stored unless you ask (keyvault).

Security posture
----------------
- credentials live in the local keyvault (OS user-scoped)
- every payout requires explicit confirmation — claume never moves money
  autonomously, by design
- SMTP uses STARTTLS/SSL only; tokens never appear in transcripts
  (scrubbed by the security layer)
"""
from __future__ import annotations

import json
import re
import secrets
import smtplib
import string
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def _reach_dir() -> Path:
    from . import config

    d = config.claume_dir() / "reach"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ledger_path() -> Path:
    return _reach_dir() / "ledger.json"


# ---------------------------------------------------------------------------
# passwords
# ---------------------------------------------------------------------------
def generate_password(length: int = 20, symbols: bool = True) -> str:
    """Cryptographically random password (stdlib `secrets`)."""
    alphabet = string.ascii_letters + string.digits
    if symbols:
        alphabet += "!@#$%^&*()-_=+?"
    # guarantee one of each class
    pw = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
    ]
    if symbols:
        pw.append(secrets.choice("!@#$%^&*()-_=+?"))
    pw += [secrets.choice(alphabet) for _ in range(max(8, length) - len(pw))]
    secrets.SystemRandom().shuffle(pw)
    return "".join(pw)


# ---------------------------------------------------------------------------
# telegram channel (free, bot-first)
# ---------------------------------------------------------------------------
TELEGRAM_API = "https://api.telegram.org"


def telegram_post(text: str, image_path: str = "", video_path: str = "") -> Tuple[str, bool]:
    """Post to the configured Telegram channel via Bot API."""
    from . import keyvault

    token = keyvault.resolve_key("TELEGRAM_BOT_TOKEN")
    chat_id = keyvault.resolve_key("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return (
            "error: Telegram not configured — run /social setup telegram "
            "(token from @BotFather, chat id of your channel)",
            True,
        )
    try:
        method, field = "sendMessage", None
        if image_path:
            method, field = "sendPhoto", "photo"
        elif video_path:
            method, field = "sendVideo", "video"
        url = f"{TELEGRAM_API}/bot{token}/{method}"
        if field:
            boundary = "----claume" + secrets.token_hex(8)
            with open(image_path if image_path else video_path, "rb") as fh:
                media = fh.read()
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="caption"\r\n\r\n{text}\r\n'
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field}"; filename="upload"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + media + f"\r\n--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        else:
            data = urllib.parse.urlencode(
                {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML"}
            ).encode("utf-8")
            req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if payload.get("ok"):
            kind = "photo" if image_path else ("video" if video_path else "message")
            return f"posted {kind} to the Telegram channel", False
        return f"error: telegram said: {payload.get('description', 'unknown')}", True
    except Exception as exc:
        return f"error: telegram post failed: {exc}", True


def telegram_status() -> str:
    from . import keyvault

    token = keyvault.resolve_key("TELEGRAM_BOT_TOKEN")
    chat = keyvault.resolve_key("TELEGRAM_CHAT_ID")
    if token and chat:
        return "telegram configured (channel live)"
    if token:
        return "telegram token set — missing channel chat id"
    return "telegram not configured"


# ---------------------------------------------------------------------------
# email (SMTP send / IMAP check)
# ---------------------------------------------------------------------------
def _smtp_config() -> Optional[Dict[str, str]]:
    from . import keyvault

    host = keyvault.resolve_key("SMTP_HOST")
    user = keyvault.resolve_key("SMTP_USER")
    pw = keyvault.resolve_key("SMTP_PASS")
    if not (host and user and pw):
        return None
    port = int(keyvault.resolve_key("SMTP_PORT") or 587)
    return {"host": host, "port": str(port), "user": user, "pass": pw}


def send_email(to: str, subject: str, body: str) -> Tuple[str, bool]:
    """Send an email via configured SMTP (STARTTLS)."""
    cfgm = _smtp_config()
    if not cfgm:
        return (
            "error: email not configured — run /email setup (needs SMTP_HOST, "
            "SMTP_USER, SMTP_PASS; for Gmail use an app password: "
            "https://myaccount.google.com/apppasswords)",
            True,
        )
    try:
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = cfgm["user"]
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        if cfgm["port"] == "465":
            with smtplib.SMTP_SSL(cfgm["host"], 465, timeout=30) as s:
                s.login(cfgm["user"], cfgm["pass"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfgm["host"], int(cfgm["port"]), timeout=30) as s:
                s.starttls()
                s.login(cfgm["user"], cfgm["pass"])
                s.send_message(msg)
        return f"email sent to {to}: {subject}", False
    except Exception as exc:
        return f"error: send failed: {exc}", True


def check_inbox(limit: int = 8, mark_seen: bool = False) -> Tuple[str, bool]:
    """List recent unread messages (subject + from + verification links)."""
    from . import keyvault

    host = keyvault.resolve_key("IMAP_HOST")
    user = keyvault.resolve_key("SMTP_USER")
    pw = keyvault.resolve_key("SMTP_PASS")
    if not (host and user and pw):
        return "error: IMAP not configured — run /email setup (IMAP_HOST needed)", True
    try:
        import imaplib
        from email import policy
        from email.parser import BytesParser

        imap = imaplib.IMAP4_SSL(host, 993, timeout=30)
        imap.login(user, pw)
        imap.select("INBOX")
        _, data = imap.search(None, "(UNSEEN)")
        ids = data[0].split()[-limit:]
        lines: List[str] = []
        link_re = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
        for i in reversed(ids):
            _, msg_data = imap.fetch(i, "(RFC822)")
            msg = BytesParser(policy=policy.default).parsebytes(msg_data[0][1])
            body_txt = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body_txt = part.get_content()
                        break
            else:
                body_txt = msg.get_content()
            links = link_re.findall(body_txt or "")
            verify = [l for l in links if any(k in l.lower() for k in ("verify", "confirm", "activate", "token"))]
            lines.append(
                f"· {msg.get('From', '?')[:48]} — {msg.get('Subject', '(no subject)')[:70]}"
                + (f"\n    links: {verify[0] if verify else (links[0] if links else '')}"
                   if (verify or links) else "")
            )
            if mark_seen:
                imap.store(i, "+FLAGS", "\\Seen")
        imap.logout()
        if not lines:
            return "inbox: no unread messages", False
        return "unread:\n" + "\n".join(lines), False
    except Exception as exc:
        return f"error: inbox check failed: {exc}", True


# ---------------------------------------------------------------------------
# payout ledger + MTN MoMo instruction
# ---------------------------------------------------------------------------
def ledger_add(entry: Dict[str, Any]) -> None:
    """Append a monetization/payout event to the local ledger."""
    path = _ledger_path()
    try:
        book = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        book = []
    entry = dict(entry)
    entry.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    book.append(entry)
    path.write_text(json.dumps(book, indent=2), encoding="utf-8")


def ledger_summary() -> str:
    path = _ledger_path()
    if not path.exists():
        return "ledger is empty — no monetization events recorded yet"
    try:
        book = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "ledger file unreadable"
    if not book:
        return "ledger is empty"
    income = sum(float(e.get("amount", 0)) for e in book if e.get("type") == "income")
    paid = sum(float(e.get("amount", 0)) for e in book if e.get("type") == "payout")
    lines = [f"events: {len(book)} · earned {income:.2f} · paid out {paid:.2f} · balance {income - paid:.2f}"]
    for e in book[-6:]:
        lines.append(f"· {e['ts'][:16]} {e.get('type','?'):6} {e.get('amount',0):>8} {e.get('source','')[:40]}")
    return "\n".join(lines)


def momo_payout_instruction(amount: float, currency: str = "XAF") -> Tuple[str, bool]:
    """Record a payout intent for the MTN Cameroon MoMo target.

    NOTE: claume PREPARES the transfer; moving money needs your explicit
    approval (and on free rails, a manual/P2P step). This records the
    instruction and returns exactly what to do.
    """
    from . import keyvault

    momo = keyvault.resolve_key("MOMO_NUMBER") or ""
    email = keyvault.resolve_key("OWNER_EMAIL") or ""
    if not momo:
        momo = "+237 678302909"
    ledger_add({"type": "payout_intent", "amount": amount, "currency": currency,
                "target": "MTN MoMo " + momo, "source": "claume ledger"})
    return (
        f"payout intent recorded: {amount:.2f} {currency} → MTN MoMo {momo}\n"
        f"free rails (pick one):\n"
        f"  1. Telegram Stars/TON from channel revenue → withdraw to an exchange\n"
        f"     → P2P sell for XAF → MTN MoMo to {momo}\n"
        f"  2. Manual bank/MoMo transfer coordinated via {email or 'your email'}\n"
        f"MTN's official MoMo OpenAPI needs a paid business contract — when you\n"
        f"have one, set MOMO_API_KEY + MOMO_SUBSCRIPTION_KEY and claume can\n"
        f"disburse directly (still with your confirmation).",
        False,
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
def status() -> str:
    bits = [telegram_status()]
    if _smtp_config():
        bits.append("email configured")
    else:
        bits.append("email not configured")
    from . import keyvault

    bits.append("MoMo " + (keyvault.resolve_key("MOMO_NUMBER") or "not set"))
    return "reach · " + " · ".join(bits)
