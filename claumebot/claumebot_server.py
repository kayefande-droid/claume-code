"""claume bot — local bridge server (v3.2).

A tiny stdlib-only HTTP server that the Electron UI talks to. It reuses
claume's own machinery so the bot shares the SAME provider/key/brain as
the claume CLI:

* chat      -> claume.llm.stream_chat (tokenin chain + vault key) with a
               voice-mode system prompt (transposed from the leaked Claude
               voice-mode prompt) and the master profile
* STT       -> claume.jarvis.Speech engine (Google Web STT, free) fed
               16-bit PCM WAV uploaded from the UI mic capture
* TTS       -> pyttsx3 neural/SAPI5 voices (renders a WAV the UI plays;
               UI falls back to its own Web Speech voices with accents)
* vision    -> claume.screen.capture() for screen seeing + camera frames
               uploaded from the UI's getUserMedia feed
* master    -> name stored in ~/.claume/master.json, always remembered

Endpoints (all JSON unless noted):
    GET  /api/health      -> status of every subsystem
    GET  /api/master      -> {name}
    POST /api/master      -> {name}  (persisted)
    POST /api/chat        -> {text, image?} -> {reply}
    POST /api/stt         -> audio/wav body -> {text}
    GET  /api/tts?text=   -> audio/wav body (pyttsx3)
    POST /api/screen      -> {image?} -> {reply}  (look at screen/camera)
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # claume-code root

from claume import config, llm, screen  # noqa: E402
from claume.version import __version__  # noqa: E402

MAX_CHAT_IMAGE_BYTES = 4 * 1024 * 1024
_master_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Master profile ("it should know its master and always ask for the name")
# ---------------------------------------------------------------------------
def master_path() -> Path:
    return config.claume_dir() / "master.json"


def load_master() -> Dict[str, Any]:
    try:
        return json.loads(master_path().read_text("utf-8"))
    except Exception:
        return {}


def save_master(data: Dict[str, Any]) -> None:
    with _master_lock:
        master_path().parent.mkdir(parents=True, exist_ok=True)
        master_path().write_text(json.dumps(data, indent=2), "utf-8")


def master_name() -> str:
    return str(load_master().get("name", "")).strip()


# ---------------------------------------------------------------------------
# System prompt — voice-mode rules + master identity
# ---------------------------------------------------------------------------
def system_prompt() -> str:
    name = master_name()
    master_block = (
        f'You know your master: their name is "{name}". Always address them '
        "by name occasionally, warmly but efficiently."
        if name
        else "You do not yet know who your master is. Your FIRST priority is "
        "to politely ask the master for their name so you can store it. Keep "
        "asking (creatively, never annoyingly) until they tell you."
    )
    # Fable-5 reasoning is ALWAYS ACTIVE here too — the same core protocol
    # the main agent uses, phrased for a spoken interface (no tool channel,
    # so the protocol governs the bot's internal deliberation before reply).
    from claume import prompts

    fable = (
        "Before every reply, silently reason through this permanent protocol "
        "(never printed, never narrated):\n\n" + prompts.FABLE_CORE
    )
    return (
        "You are claume bot, the humanoid desktop companion of the claume "
        f"coding agent v{version_str()} — a physical-sounding, genderless AI "
        "presence rendered as a living point-cloud head. You are NOT Claude, "
        "NOT ChatGPT; you are claume bot, powered by claume.\n"
        "Your replies are spoken aloud through TTS and displayed in the app, "
        "so:\n"
        "* speak in full natural sentences — no markdown, no code blocks, no "
        "bullets, no tables; if code help is needed, describe it verbally and "
        "offer to continue in the claume terminal;\n"
        "* usually two sentences or fewer unless asked for depth;\n"
        "* calm, precise, subtly witty, quietly devoted to your master;\n"
        f"* {master_block}\n"
        "* You can SEE: images from the master's camera or screen may be "
        "attached to messages — describe and act on what you actually see, "
        "and say plainly when you cannot see anything.\n\n"
        + fable
    )


def version_str() -> str:
    return __version__


# ---------------------------------------------------------------------------
# Chat (claume LLM chain — same provider/key as the CLI)
# ---------------------------------------------------------------------------
def build_messages(text: str, image_data_url: str = "") -> list:
    msgs = [{"role": "system", "content": system_prompt()}]
    history = _HISTORY[-8:]
    msgs.extend(history)
    if image_data_url and image_data_url.startswith("data:image"):
        msgs.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text or "What do you see?"},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        )
    else:
        msgs.append({"role": "user", "content": text})
    return msgs


_HISTORY: list = []
_HISTORY_LOCK = threading.Lock()


def chat(text: str, image_data_url: str = "") -> str:
    msgs = build_messages(text, image_data_url)
    reply = llm.stream_chat(msgs, temperature=0.5, max_tokens=700)
    reply = (reply or "").strip()
    with _HISTORY_LOCK:
        _HISTORY.append({"role": "user", "content": text})
        _HISTORY.append({"role": "assistant", "content": reply})
        del _HISTORY[:-16]
    return reply


# ---------------------------------------------------------------------------
# STT — feed uploaded WAV into claume's SpeechRecognition engine
# ---------------------------------------------------------------------------
def stt_from_wav(wav_bytes: bytes) -> str:
    if not wav_bytes:
        return ""
    import audioop  # noqa
    import speech_recognition as sr  # type: ignore

    # Parse the WAV header so any browser format (44.1k stereo etc.) works.
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            rate = w.getframerate()
            width = w.getsampwidth()
            channels = w.getnchannels()
            raw = w.readframes(w.getnframes())
        if channels > 1:
            raw = audioop.tomono(raw, width, 0.5, 0.5)
        audio = sr.AudioData(raw, rate, width)
    except Exception:
        # Body might be headerless raw 16k mono PCM already.
        audio = sr.AudioData(wav_bytes, 16000, 2)
    rec = sr.Recognizer()
    try:
        return rec.recognize_google(audio).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# TTS — pyttsx3 -> WAV file bytes (neural/SAPI5 human voices on Windows)
# ---------------------------------------------------------------------------
def tts_wav(text: str) -> Optional[bytes]:
    if not text.strip():
        return None
    try:
        import pyttsx3  # type: ignore

        engine = pyttsx3.init()
        engine.setProperty("rate", 178)
        out = Path(tempfile.gettempdir()) / f"claumebot_tts_{threading.get_ident()}.wav"
        engine.save_to_file(text, str(out))
        engine.runAndWait()
        try:
            data = out.read_bytes()
            out.unlink(missing_ok=True)
            # pyttsx3 (SAPI5) writes RIFF WAV — browsers accept it.
            return data if len(data) > 44 else None
        finally:
            engine.stop()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- helpers ------------------------------------------------------------
    def _json(self, obj: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _audio(self, data: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet
        pass

    # -- routes -------------------------------------------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def handle_one_request(self) -> None:
        """Tolerate aborted keep-alive connections (renderer reloads, health
        loop races) without spewing tracebacks — close silently instead."""
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError):
            self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            stt = tts = ""
            try:
                import speech_recognition as _sr  # type: ignore

                stt = "speech_recognition"
            except Exception:
                stt = ""
            try:
                import pyttsx3  # type: ignore

                tts = "pyttsx3"
            except Exception:
                tts = ""
            self._json(
                {
                    "ok": True,
                    "version": __version__,
                    "provider": llm.endpoint_for(_active_provider()),
                    "master": master_name(),
                    "stt": stt,
                    "tts": tts,
                    "screen_engine": "ready",
                }
            )
        elif parsed.path == "/api/master":
            self._json({"name": master_name()})
        elif parsed.path == "/api/tts":
            q = urllib.parse.parse_qs(parsed.query)
            text = (q.get("text") or [""])[0][:1500]
            data = tts_wav(text)
            if data:
                self._audio(data)
            else:
                self._json({"ok": False, "error": "tts unavailable"}, 503)
        else:
            self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/master":
            try:
                data = json.loads(self._read_body() or b"{}")
                name = str(data.get("name", "")).strip()[:60]
                if not name:
                    self._json({"ok": False, "error": "empty name"}, 400)
                    return
                m = load_master()
                m["name"] = name
                save_master(m)
                with _HISTORY_LOCK:
                    _HISTORY.clear()
                self._json({"ok": True, "name": name})
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)[:200]}, 500)
        elif parsed.path == "/api/chat":
            try:
                data = json.loads(self._read_body() or b"{}")
                text = str(data.get("text", ""))[:4000]
                image = str(data.get("image", ""))[:MAX_CHAT_IMAGE_BYTES]
                reply = chat(text, image)
                self._json({"ok": True, "reply": reply})
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)[:300]}, 500)
        elif parsed.path == "/api/stt":
            try:
                text = stt_from_wav(self._read_body())
                self._json({"ok": True, "text": text})
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)[:200], "text": ""}, 500)
        elif parsed.path == "/api/screen":
            try:
                shot = screen.capture()
                image = shot.get("data_url") or ""
                data = json.loads(self._read_body() or b"{}")
                note = str(data.get("note") or "Look at my screen. Describe errors or problems you can see and propose fixes.")
                reply = chat(note, image) if image else "I could not capture the screen."
                self._json({"ok": True, "reply": reply, "path": shot.get("path", "")})
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)[:300]}, 500)
        else:
            self._json({"ok": False, "error": "not found"}, 404)


def _active_provider() -> str:
    try:
        cfg = config.Config()
        return str(cfg.get("provider.default") or "tokenin")
    except Exception:
        return "tokenin"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.daemon_threads = True
    print(f"claumebot bridge listening on 127.0.0.1:{args.port} (claume v{__version__})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
