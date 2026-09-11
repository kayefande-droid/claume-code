"""Web tools: search + fetch, used for docs lookups and error research."""
from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Tuple

from pathlib import Path as _P

_SSL_CTX = ssl.create_default_context()

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def web_search(base: Path, query: str, max_results: int = 6) -> Tuple[str, bool]:
    """DuckDuckGo HTML search — no API key required."""
    q = urllib.parse.quote(str(query))
    url = f"https://html.duckduckgo.com/html/?q={q}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return f"error: search failed: {exc}", True

    results: List[str] = []
    # <a rel="nofollow" class="result__a" href="...">Title</a>
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL
    ):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        # DDG wraps URLs: //duckduckgo.com/l/?uddg=<real>
        if "uddg=" in href:
            try:
                inner = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                href = inner
            except Exception:
                pass
        results.append(f"{len(results) + 1}. {title}\n   {href}")
        if len(results) >= int(max_results):
            break
    if not results:
        return "no results found (search page layout may have changed)", False
    return "\n".join(results), False


def fetch_url(base: Path, url: str, max_chars: int = 12_000) -> Tuple[str, bool]:
    """Fetch a page and return readable-ish text."""
    raw_url = str(url).strip()
    if not raw_url.startswith(("http://", "https://")):
        return "error: url must start with http:// or https://", True
    try:
        req = urllib.request.Request(
            raw_url, headers={"User-Agent": _UA, "Accept": "text/html,text/plain,*/*"}
        )
        with urllib.request.urlopen(req, timeout=25, context=_SSL_CTX) as resp:
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read(2_000_000)
    except Exception as exc:
        return f"error: fetch failed: {exc}", True

    if "json" in ctype or raw_url.endswith(".json"):
        try:
            pretty = json.dumps(json.loads(data.decode("utf-8", "replace")), indent=2)
            return pretty[: int(max_chars)], False
        except Exception:
            pass

    text = data.decode("utf-8", "replace")
    if "html" in ctype or "<html" in text[:500].lower():
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
        text = re.sub(r"&#39;", "'", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[: int(max_chars)], False
