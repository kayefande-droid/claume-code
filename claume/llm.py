"""LLM client for the agent.

Talks to the local free-claume proxy (OpenAI-compatible) by default, but
works with *any* OpenAI-compatible endpoint. Third-party providers whose
keys live in the vault (GROQ_API_KEY, OPENROUTER_API_KEY, …) are mapped
to their public endpoints — the "live space".
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import ssl
from typing import Any, Dict, Generator, List, Optional

from . import config, keyvault

_SSL_CTX = ssl.create_default_context()

# Well-known OpenAI-compatible public endpoints ("live space" providers).
# claume runs NVIDIA NIM through the local free-claume proxy by default —
# jarvis/claume both go through it so one NVIDIA_API_KEY powers everything.
PROVIDER_ENDPOINTS: Dict[str, str] = {
    "nvidia": "http://127.0.0.1:8000/v1",  # local free-claume proxy
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
}

PROVIDER_KEY_ENV: Dict[str, str] = {
    "nvidia": "NVIDIA_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "together": "TOGETHER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
}


# Provider-scoped fallback chains: applied on top of the primary model so
# switching providers never carries foreign model names across.
PROVIDER_MODEL_CHAINS: Dict[str, List[str]] = {}


class LLMError(Exception):
    pass


def _friendly_http_error(code: int, detail: str) -> str:
    """Turn nested provider JSON blobs into one clear sentence."""
    short = detail[:300]
    try:
        obj = json.loads(detail)
        msg = obj.get("error", {}).get("message", "") if isinstance(obj, dict) else ""
        if isinstance(msg, str) and msg:
            # The proxy wraps upstream JSON inside 'message' — unwrap once more.
            try:
                inner = json.loads(msg)
                msg = inner.get("detail") or inner.get("title") or msg
            except Exception:
                pass
            short = msg[:300]
    except Exception:
        pass
    low = short.lower()
    if code == 410 or "end of life" in low or "no longer available" in low:
        return (
            f"model retired upstream (410 Gone): {short} — "
            "run /model to pick another, or set fallbacks in the proxy admin UI"
        )
    if code == 401:
        return (
            f"invalid API key (401): {short} — run /key NVIDIA_API_KEY <key> "
            "or set it in the admin UI"
        )
    if code == 429:
        return f"rate limited (429): {short} — add another key (NVIDIA_API_KEY_2) or retry"
    if code == 402 or "saldo" in low or "insufficient_balance" in low:
        return (
            f"provider balance/credits empty (402): {short} — run /key to update "
            "the NVIDIA NIM key"
        )
    return f"LLM HTTP {code}: {short}"


def endpoint_for(provider: str) -> str:
    cfg = config.Config()
    custom = cfg.get(f"providers.{provider}.base_url")
    if custom:
        return str(custom)
    return PROVIDER_ENDPOINTS.get(provider, PROVIDER_ENDPOINTS["nvidia"])


def api_key_for(provider: str) -> Optional[str]:
    env = PROVIDER_KEY_ENV.get(provider, "NVIDIA_API_KEY")
    return keyvault.resolve_key(env)


def stream_chat(
    messages: List[Dict[str, Any]],  # content may be str OR multimodal list
    model: Optional[str] = None,
    provider: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    on_token: Optional[Any] = None,
    effort: Optional[str] = None,
) -> str:
    """Send a chat request; returns the full assistant text.

    When ``on_token`` is provided the request is streamed and the
    callback receives each text delta as it arrives.
    """
    cfg = config.Config()
    provider = provider or cfg.get("provider", "nvidia")
    # Model fallback chain: primary first, then each fallback (mirrors
    # FCC-style resilience so an EOL/dead model doesn't kill the task).
    model_chain: List[str] = []
    primary = model or cfg.model
    if primary:
        model_chain.append(primary)
    for fb in cfg.get("model_fallbacks", []) or []:
        fb = str(fb).strip()
        if fb and fb not in model_chain:
            model_chain.append(fb)
    # Provider-scoped chain — only models native to this provider join the chain.
    for fb in PROVIDER_MODEL_CHAINS.get(provider, []):
        fb = str(fb).strip()
        if fb and fb not in model_chain:
            model_chain.append(fb)
    endpoint = endpoint_for(provider).rstrip("/")
    key = api_key_for(provider)

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://freebuff.ai"
        headers["X-Title"] = "claume-code"

    # Effort knob: deeper effort = more output tokens + slightly more
    # deterministic sampling for planning-heavy steps.
    effort = effort or cfg.effort
    effort_map = {
        "fast": (1024, 0.4),
        "balanced": (4096, 0.2),
        "deep": (8192, 0.1),
        "ultra": (16_384, 0.05),
    }
    max_tokens, temperature = effort_map.get(effort, (4096, 0.2))

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": bool(on_token),
    }

    last_error: Optional[LLMError] = None
    for attempt_model in model_chain:
        payload["model"] = attempt_model
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{endpoint}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=300, context=_SSL_CTX)
            return _consume_response(resp, payload, on_token)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            err = LLMError(_friendly_http_error(exc.code, detail))
            # Only failover on model-level errors; auth/billing errors are fatal.
            # 504 included: free community pools often gateway-timeout on one
            # model while the next in the chain answers instantly.
            if exc.code in (400, 404, 410, 429, 500, 502, 503, 504) and len(model_chain) > 1:
                last_error = err
                continue
            raise err from exc
        except urllib.error.URLError as exc:
            # Connection-level failure: no point trying the same endpoint
            raise LLMError(
                f"cannot reach LLM endpoint {endpoint} — is the free-claume proxy running? ({exc})"
            ) from exc
    raise last_error or LLMError("all models in the fallback chain failed")


def _consume_response(resp: Any, payload: Dict[str, Any], on_token: Optional[Any]) -> str:
    """Read an OpenAI-compatible response (streamed or buffered) into text."""
    chunks: List[str] = []

    if payload.get("stream"):
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.strip()
            if line.startswith(b"data:"):
                data_str = line[5:].strip()
                if data_str == b"[DONE]":
                    break
                try:
                    obj = json.loads(data_str.decode("utf-8"))
                    delta = obj["choices"][0].get("delta", {})
                    text = delta.get("content") or ""
                    if text:
                        chunks.append(text)
                        if on_token:
                            on_token(text)
                except Exception:
                    continue
    else:
        data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"] or ""
        chunks.append(text)
        if on_token:
            on_token(text)

    return "".join(chunks)


def health_check(provider: Optional[str] = None) -> bool:
    """Cheap probe: 1-token ping to see whether the endpoint answers."""
    try:
        stream_chat(
            [{"role": "user", "content": "ping"}],
            max_tokens=4,
            provider=provider,
            effort="fast",
        )
        return True
    except Exception:
        return False
