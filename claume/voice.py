"""Voice I/O for claume — speak the final answers, hear voice commands.

Design goals:
* **Zero required dependencies.** Windows SAPI5 (British voices if installed:
  `Microsoft George`/`Microsoft Hazel`/`Microsoft Sonia`) is driven through
  PowerShell's System.Speech — no packages needed. If `pyttsx3` is installed
  it is preferred (richer voice enumeration). macOS `say` and Linux
  `espeak-ng` are supported too.
* **Voice input (optional):** needs `SpeechRecognition` + `pyaudio`
  (`pip install SpeechRecognition pyaudio`). Without them, voice commands
  print a clear one-line hint instead of crashing.
* Non-blocking: `speak()` returns immediately, a daemon thread talks while
  you keep typing. `wait_until_done()` joins it before program exit.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Config helpers (late imports keep startup snappy and tests hermetic)
# ---------------------------------------------------------------------------

_VOICE_THREAD: Optional[threading.Thread] = None


def _cfg() -> Any:
    from . import config

    return config.Config()


def enabled() -> bool:
    try:
        return bool(_cfg().get("voice_enabled", False))
    except Exception:
        return False


def accent() -> str:
    """Accent preference: male-british | female-british | male | female."""
    try:
        return str(_cfg().get("voice_accent", "male-british"))
    except Exception:
        return "male-british"


# ---------------------------------------------------------------------------
# Text → speech
# ---------------------------------------------------------------------------

# British SAPI voice name fragments (checked case-insensitively).
_BRITISH_VOICE_FRAGMENTS = (
    "george",   # Microsoft George (en-GB, male)
    "hazel",    # Microsoft Hazel (en-GB, female)
    "sonia",    # Microsoft Sonia (en-GB, female; some builds spell Sonial)
    "sonial",
    "libby",    # en-GB online voices
    "ryan",     # en-GB male online voice
    "en-gb",
)

_FEMALE_FRAGMENTS = (
    "female", "zira", "hazel", "sonia", "sonial", "susan",
    "kate", "serena", "libby", "eva", "aria", "jenny", "michelle",
)


def _voice_gender(name: str) -> str:
    low = (name or "").lower()
    return "female" if any(f in low for f in _FEMALE_FRAGMENTS) else "male"


def _voice_is_british(name: str) -> bool:
    low = (name or "").lower()
    return any(f in low for f in _BRITISH_VOICE_FRAGMENTS)


def _pick_voice_from_names(names: List[str], accent_pref: str) -> Optional[str]:
    """Choose the best voice name for the accent preference.

    Pass 1: British + gender match · Pass 2: gender match · Pass 3: British.
    """
    want_british = accent_pref.endswith("british")
    want_female = accent_pref.startswith("female")
    wanted_gender = "female" if want_female else "male"
    for name in names:
        if (not want_british or _voice_is_british(name)) and _voice_gender(name) == wanted_gender:
            return name
    for name in names:
        if _voice_gender(name) == wanted_gender:
            return name
    if want_british:
        for name in names:
            if _voice_is_british(name):
                return name
    return names[0] if names else None


def _pyttsx3_engine() -> Any:
    try:
        import pyttsx3  # type: ignore

        return pyttsx3.init()
    except Exception:
        return None


def _sapi_voice_names() -> List[str]:
    """Enumerate installed SAPI voice names via PowerShell (no packages)."""
    ps = shutil.which("powershell")
    if not ps:
        return []
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.GetInstalledVoices() | ForEach-Object { Write-Output $_.VoiceInfo.Name }"
    )
    try:
        r = subprocess.run(
            [ps, "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    except Exception:
        return []


def _speak_windows(text: str, accent_pref: str, block: bool) -> bool:
    """PowerShell System.Speech — works with zero pip packages."""
    ps = shutil.which("powershell")
    if not ps:
        return False
    names = _sapi_voice_names() or ["Microsoft David", "Microsoft Zira"]
    chosen = _pick_voice_from_names(names, accent_pref)
    safe = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SelectVoice('{chosen.replace(chr(39), '')}'); "
        f"$s.Speak('{safe}')"
    )
    try:
        if block:
            subprocess.run(
                [ps, "-NoProfile", "-Command", script],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=120,
            )
        else:
            subprocess.Popen(
                [ps, "-NoProfile", "-Command", script],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return True
    except Exception:
        return False


def _speak_pyttsx3(text: str, accent_pref: str, block: bool) -> bool:
    eng = _pyttsx3_engine()
    if eng is None:
        return False

    def _run() -> None:
        try:
            names = []
            for v in eng.getProperty("voices"):
                names.append(getattr(v, "name", "") or "")
            chosen = _pick_voice_from_names(names, accent_pref)
            if chosen:
                for v in eng.getProperty("voices"):
                    if (getattr(v, "name", "") or "") == chosen:
                        eng.setProperty("voice", getattr(v, "id", chosen))
                        break
            eng.say(text)
            eng.runAndWait()
        except Exception:
            pass

    global _VOICE_THREAD
    _VOICE_THREAD = threading.Thread(target=_run, name="claume-voice", daemon=True)
    _VOICE_THREAD.start()
    if block:
        _VOICE_THREAD.join(timeout=120)
    return True


def _speak_unix(text: str, accent_pref: str, block: bool) -> bool:
    """macOS `say` / Linux `espeak-ng`."""
    exe = shutil.which("say") or shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        return False
    args = [exe]
    if "say" in os.path.basename(exe):
        args += ["-v", "Serena" if accent_pref.startswith("female") else "Daniel"]
    elif accent_pref.startswith("female"):
        args += ["-v", "f3"]
    args += [text[:1500]]
    try:
        if block:
            subprocess.run(args, timeout=120)
        else:
            subprocess.Popen(args)
        return True
    except Exception:
        return False


def _clean_for_speech(text: str) -> str:
    """Strip markdown/code noise so the voice reads naturally."""
    clean = re.sub(r"```.*?```", " … code block omitted … ", text, flags=re.DOTALL)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", clean)
    clean = re.sub(r"[*_#>|]", "", clean)
    return " ".join(clean.split())[:2000]


def speak(text: str, block: bool = False) -> bool:
    """Speak text (async by default). Returns True if an engine handled it.

    Silent no-op when voice is disabled (/voice off) — callers don't need to
    check `voice.enabled()` themselves.
    """
    if not text or not text.strip() or not enabled():
        return False
    clean = _clean_for_speech(text)
    if not clean:
        return False
    accent_pref = accent()
    if _speak_pyttsx3(clean, accent_pref, block):
        return True
    if os.name == "nt" and _speak_windows(clean, accent_pref, block):
        return True
    return _speak_unix(clean, accent_pref, block)


def speak_now(text: str, accent_pref: str = "", block: bool = False) -> bool:
    """Speak text UNCONDITIONALLY — bypasses the /voice on/off gate.

    Used by the jarvis plugin: a voice assistant always talks, regardless
    of whether claume's answer narration is enabled. Same engine ladder
    as speak(): pyttsx3 → SAPI5 via PowerShell → unix say/espeak.
    """
    if not text or not text.strip():
        return False
    clean = _clean_for_speech(text)
    if not clean:
        return False
    accent_pref = accent_pref or accent()
    if _speak_pyttsx3(clean, accent_pref, block):
        return True
    if os.name == "nt" and _speak_windows(clean, accent_pref, block):
        return True
    return _speak_unix(clean, accent_pref, block)


def wait_until_done(timeout: float = 15) -> None:
    """Join a running speech thread before program exit."""
    if _VOICE_THREAD and _VOICE_THREAD.is_alive():
        _VOICE_THREAD.join(timeout=timeout)


def list_voices() -> List[str]:
    """Human-readable list of installed voices for /voice voices."""
    names: List[str] = []
    eng = _pyttsx3_engine()
    if eng is not None:
        try:
            names = [getattr(v, "name", "?") or "?" for v in eng.getProperty("voices")]
        except Exception:
            names = []
    if not names:
        names = _sapi_voice_names()
    return names


# ---------------------------------------------------------------------------
# Speech → text (voice commands)
# ---------------------------------------------------------------------------

def listen(timeout: Optional[float] = None) -> str:
    """Listen to the mic and return transcribed text ('' on silence/error)."""
    try:
        import speech_recognition as sr  # type: ignore
    except ImportError:
        from .ui import RED, RESET

        print(f"{RED}✗ voice input needs: pip install SpeechRecognition pyaudio{RESET}")
        return ""
    cfg = _cfg()
    timeout = float(timeout or cfg.get("voice_listen_timeout", 6))
    r = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.4)
            audio = r.listen(source, timeout=timeout, phrase_time_limit=20)
    except Exception as exc:
        from .ui import RED, RESET

        print(f"{RED}✗ mic unavailable: {exc}{RESET}")
        return ""
    try:
        return r.recognize_google(audio, language=str(cfg.get("voice_lang", "en-GB")))
    except Exception:
        return ""


def hear_command() -> str:
    """Listen for one voice command; returns the transcribed text."""
    from .ui import ACCENT, MUTED, RESET

    print(f"{ACCENT}🎙 listening…{RESET} {MUTED}(speak now — /voice off to disable){RESET}")
    text = listen()
    if text:
        print(f"{MUTED}heard:{RESET} {text}")
    else:
        print(f"{MUTED}(nothing heard){RESET}")
    return text
