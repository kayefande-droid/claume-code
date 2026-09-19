"""claume jarvis — desktop voice assistant engine (v3).

Jarvis is a bundled PLUGIN (see skills/PLUGINS.md): a wake-word voice
assistant that answers through the SAME provider/key as claume (NVIDIA NIM
by default — vault key NVIDIA_API_KEY), speaks replies aloud, and ships
a human-like desktop UI (jarvis_app.py).

Voice behavior is transposed from the leaked Claude voice-mode system
prompt (skills/system-prompts-leaks/Anthropic/claude-voice-mode.md):
* replies go through TTS → produce only TTS-friendly text: full spoken
  sentences, no code blocks, no bullets, no tables, no markdown.
* ≤ 2 sentences / ≤ 50 words unless the user asks for depth.
* spell-out pronunciation control for words TTS mangles.

Degradation ladder (stdlib-first, everything optional):
    openWakeWord  → true neural wake word ("jarvis" model auto-downloaded)
    SpeechRecognition + pyaudio → mic STT (voice commands)
    neither       → push-to-talk typed input; TTS still speaks replies

The human-like UI (tkinter, zero deps) lives in jarvis_app.py; this module
is the engine so both the desktop window and the `claume jarvis` terminal
loop share one brain.
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from . import config, llm
from .version import __version__

# ---------------------------------------------------------------------------
# Voice-mode reply shaping (transposed from claude-voice-mode.md)
# ---------------------------------------------------------------------------
VOICE_SYSTEM_EXTRA = """
You are jarvis, the voice assistant built into claume-code v{version}.
Your replies are passed through text-to-speech before reaching the user,
so you only produce responses a TTS engine can speak naturally:

* Reply in full spoken sentences. NEVER output code, code blocks, bullets,
  numbered lists, tables, diagrams or markdown — you are talking, not
  writing. If a structured answer is essential, say you'll show it in the
  claume terminal and keep the spoken version verbal.
* Usually no more than two sentences and fifty words, unless the user
  asks you to go in depth.
* Control pronunciation: for words TTS may misread, write them as they
  sound (capitals to stress syllables, dashes to separate, apostrophes).
* Your name is jarvis. You run inside claume (never Claude, never
  ChatGPT). Address the user naturally and keep a calm, confident tone.
"""

WAKE_WORD_DEFAULT = "jarvis"


def voice_system_prompt() -> str:
    # Fable-5 reasoning is ALWAYS ACTIVE on every claume surface — the
    # voice loop composes the same core protocol the main agent uses.
    from . import prompts

    fable = ""
    try:
        fable = "In your reasoning, follow this permanent protocol:\n\n" + prompts.FABLE_CORE
    except Exception:
        fable = ""
    return VOICE_SYSTEM_EXTRA.format(version=__version__) + ("\n" + fable if fable else "")


# ---------------------------------------------------------------------------
# STT engines
# ---------------------------------------------------------------------------
class Speech:
    """Microphone speech-to-text with a graceful degradation ladder."""

    def __init__(self) -> None:
        self.recognizer = None
        self.microphone = None
        self._error = ""
        try:
            import speech_recognition as sr  # type: ignore

            self.recognizer = sr.Recognizer()
            self.microphone = sr.Microphone()
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.6)
        except Exception as exc:  # no mic stack — fall back to typing
            self._error = str(exc)[:120]

    @property
    def available(self) -> bool:
        return self.recognizer is not None and self.microphone is not None

    def listen_once(self, timeout: float = 6.0, phrase_limit: float = 12.0) -> str:
        """One utterance → text. Empty string on silence/failure."""
        if not self.available:
            return ""
        try:
            import speech_recognition as sr  # type: ignore

            with self.microphone as source:
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_limit
                )
            try:
                return self.recognizer.recognize_google(audio).strip()
            except sr.UnknownValueError:
                return ""
            except sr.RequestError:
                # offline fallback (pocket-sphinx if installed, else nothing)
                try:
                    return self.recognizer.recognize_sphinx(audio).strip()
                except Exception:
                    return ""
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Wake-word engines
# ---------------------------------------------------------------------------
class WakeWord:
    """'jarvis' spotting: openWakeWord when installed, else keyword fallback.

    The fallback path uses SpeechRecognition's free Google STT and fires
    when the transcript contains the wake word — lighter but requires the
    mic stack; if even that is missing, the caller falls back to
    push-to-talk.
    """

    def __init__(self, keyword: str = WAKE_WORD_DEFAULT) -> None:
        self.keyword = (keyword or WAKE_WORD_DEFAULT).lower()
        self.model = None
        self.mode = "none"
        try:
            from openwakeword.model import Model  # type: ignore

            # 'jarvis' ships as a pre-trained model in openwakeword.
            self.model = Model(wakeword_models=[self.keyword])
            self.model.predict(b"\x00" * 1280)  # warm-up frame
            self.mode = "openwakeword"
        except Exception:
            self.model = None

    @property
    def available(self) -> bool:
        return self.model is not None or self.mode == "keyword"

    def feed(self, chunk: bytes) -> float:
        """Feed 16kHz mono int16 PCM bytes; returns detection score 0..1."""
        if self.model is None:
            return 0.0
        try:
            scores = self.model.predict(chunk)
            return float(max(scores.values())) if scores else 0.0
        except Exception:
            return 0.0


def _tts_speak(text: str, accent: str, block: bool = False) -> None:
    """Speak via claume's voice stack — speak_now bypasses the /voice gate
    (jarvis is a voice assistant; it always talks)."""
    try:
        from . import voice

        voice.speak_now(text, accent_pref=accent, block=block)
    except Exception:
        pass


def tts_available() -> bool:
    try:
        from . import voice

        return voice.tts_ok() if hasattr(voice, "tts_ok") else True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The brain — one shared LLM conversation through claume's provider
# ---------------------------------------------------------------------------
class Jarvis:
    """Wake-word voice assistant sharing claume's provider, vault and voice.

    Jarvis uses ONLY the NVIDIA NIM API (via the local free-claume proxy).
    On startup the proxy is auto-started if needed, so jarvis can activate
    as a bot even when the user only opened `claume jarvis`.
    """

    def __init__(self, keyword: Optional[str] = None, speak_replies: bool = True) -> None:
        cfg = config.Config()
        self.keyword = (keyword or cfg.get("jarvis_wake_word") or WAKE_WORD_DEFAULT).lower()
        self.speak_replies = speak_replies
        self.speech = Speech()
        self.wake = WakeWord(self.keyword)
        self.history: List[Dict[str, str]] = []
        self.state = "idle"  # idle | listening | thinking | speaking
        self._stop = threading.Event()
        self._listeners: List[Callable[[str, str], None]] = []
        self._tts_lock = threading.Lock()
        self._recording = False
        self._last_gesture: Optional[str] = None

    # -- observer hooks: fn(state, detail) for UIs -------------------------
    def on_state(self, fn: Callable[[str, str], None]) -> None:
        self._listeners.append(fn)

    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        for fn in self._listeners:
            try:
                fn(state, detail)
            except Exception:
                pass

    # -- conversation ------------------------------------------------------
    _SCREEN_TRIGGERS = ("look at", "screenshot", "my screen", "the screen",
                        "what do you see", "check my screen", "read the error")

    def ask(self, text: str) -> str:
        """Send one utterance to the LLM through the nvidia proxy (NIM only)
        and shape the reply for speech."""
        text = (text or "").strip()
        if not text:
            return ""
        low = text.lower()
        if any(t in low for t in self._SCREEN_TRIGGERS):
            return self._ask_with_screen(text)
        self._set_state("thinking", text)
        self.history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": voice_system_prompt()}] + self.history[-10:]
        try:
            reply = llm.stream_chat(messages, provider="nvidia", effort="fast")
        except llm.LLMError as exc:
            reply = f"Connection problem. {str(exc)[:80]}"
        reply = _spoken_shape(reply)
        self.history.append({"role": "assistant", "content": reply})
        if self.speak_replies:
            self._set_state("speaking", reply)
            with self._tts_lock:
                _tts_speak(reply, str(config.Config().get("jarvis_voice_accent", "female-british")))
        self._set_state("idle", reply)
        return reply

    def _ask_with_screen(self, text: str) -> str:
        """Capture the screen and answer with vision (nvidia proxy / NIM)."""
        from . import screen as screenmod

        self._set_state("thinking", text)
        shot = screenmod.capture()
        if not shot.get("data_url"):
            reply = "I could not capture the screen on this machine."
            if self.speak_replies:
                self._set_state("speaking", reply)
                with self._tts_lock:
                    _tts_speak(reply, str(config.Config().get("jarvis_voice_accent", "female-british")))
            self._set_state("idle", reply)
            return reply
        content = [
            {"type": "text", "text": (
                f"The user asked (spoken): {text}\n\nThis is a screenshot of "
                "their screen. Reply ONLY with what you would SAY aloud: "
                "read visible errors, name the app/window, state the fix. "
                "Two spoken sentences unless asked for depth."
            )},
            {"type": "image_url", "image_url": {"url": shot["data_url"]}},
        ]
        try:
            from . import llm

            reply = llm.stream_chat(
                [{"role": "system", "content": voice_system_prompt()},
                 {"role": "user", "content": content}],
                provider="nvidia", effort="balanced",
            )
        except Exception as exc:
            reply = f"Vision failed. {str(exc)[:80]}"
        reply = _spoken_shape(reply)
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": reply})
        if self.speak_replies:
            self._set_state("speaking", reply)
            with self._tts_lock:
                _tts_speak(reply, str(config.Config().get("jarvis_voice_accent", "female-british")))
        self._set_state("idle", reply)
        return reply

    # -- gesture / always-listening / recording hooks ---------------------
    def set_gesture(self, gesture: str) -> None:
        """Feed an observed gesture / pointer gesture to jarvis so it can
        react (e.g. 'pointed at top-right', 'wave', 'tapped screen')."""
        self._last_gesture = gesture
        if not gesture:
            return
        self.history.append({"role": "user", "content": f"[gesture observed]: {gesture}"})
        self._set_state("thinking", f"gesture: {gesture}")
        messages = [{"role": "system", "content": voice_system_prompt()}] + self.history[-10:]
        try:
            reply = llm.stream_chat(messages, provider="nvidia", effort="fast")
        except Exception as exc:
            reply = ""
        reply = _spoken_shape(reply)
        if reply:
            self.history.append({"role": "assistant", "content": reply})
            if self.speak_replies:
                self._set_state("speaking", reply)
                with self._tts_lock:
                    _tts_speak(reply, str(config.Config().get("jarvis_voice_accent", "female-british")))
            self._set_state("idle", reply)

    def set_recording(self, on: bool) -> None:
        """When the user says 'record me' / 'start recording', jarvis enters
        an always-listening + gesture-follow + record mode."""
        self._recording = on
        if on:
            self._set_state("listening", "always-listening + recording mode on")
        else:
            self._set_state("idle", "recording off")

    def live_observe(self, observation: str) -> None:
        """In recording mode, feed a live observation (speech chunk / gesture
        / screen frame caption) so jarvis keeps context across the session."""
        if not self._recording or not observation:
            return
        self.history.append({"role": "user", "content": f"[live]: {observation}"})
        if len(self.history) > 24:
            self.history = self.history[-12:]

    # -- wake-word loop ----------------------------------------------------
    def run_forever(self, on_reply: Optional[Callable[[str, str], None]] = None) -> None:
        """Blocking loop: wake word → listen → ask. Ctrl+C exits."""
        if self.speech.available and self.wake.mode == "openwakeword":
            self._loop_openwakeword(on_reply)
        elif self.speech.available:
            self._loop_keyword(on_reply)
        else:
            self._loop_push_to_talk(on_reply)

    def _loop_openwakeword(self, on_reply: Optional[Callable[[str, str], None]]) -> None:
        try:
            import pyaudio  # type: ignore

            CHUNK = 1280  # 80ms @ 16kHz
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16, channels=1, rate=16000,
                input=True, frames_per_buffer=CHUNK,
            )
        except Exception:
            self._loop_keyword(on_reply)
            return
        self._set_state("idle", f"say '{self.keyword}'")
        try:
            while not self._stop.is_set():
                data = stream.read(CHUNK, exception_on_overflow=False)
                if self.wake.feed(data) > 0.5:
                    self._set_state("listening", "wake word detected")
                    heard = self.speech.listen_once()
                    if heard:
                        reply = self.ask(heard)
                        if on_reply:
                            on_reply(heard, reply)
                    self._set_state("idle", "listening for wake word")
        finally:
            try:
                stream.stop_stream()
                stream.close()
                pa.terminate()
            except Exception:
                pass

    def _loop_keyword(self, on_reply: Optional[Callable[[str, str], None]]) -> None:
        """Fallback wake mode: STT transcripts containing the keyword fire."""
        self._set_state("idle", f"say '{self.keyword}' (keyword spotting)")
        while not self._stop.is_set():
            heard = self.speech.listen_once(timeout=8)
            if heard and self.keyword in heard.lower():
                heard = _strip_wake(heard, self.keyword)
                if heard:
                    reply = self.ask(heard)
                    if on_reply:
                        on_reply(heard, reply)
                else:
                    _tts_speak("Yes?", str(config.Config().get("jarvis_voice_accent", "female-british")))
            self._set_state("idle", "listening for wake word")

    def _loop_push_to_talk(self, on_reply: Optional[Callable[[str, str], None]]) -> None:
        """No mic stack: read typed lines; TTS still speaks replies."""
        self._set_state("idle", "push-to-talk mode — type to jarvis")
        while not self._stop.is_set():
            try:
                line = input("jarvis ❯ ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.lower() in ("exit", "quit", "bye"):
                break
            if line:
                self.ask(line)
                if on_reply:
                    on_reply(line, self.history[-1]["content"] if self.history else "")

    def stop(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _spoken_shape(text: str) -> str:
    """Strip anything TTS should not read: code fences, bullets, tables,
    markdown emphasis. Enforce the two-sentence/fifty-word style only for
    long outputs (keep depth when the model chose it)."""
    t = text or ""
    t = re.sub(r"```.*?```", " I'll show that in the terminal. ", t, flags=re.S)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+[.)]\s+", "", t, flags=re.M)
    t = re.sub(r"\|.*\|", "", t)  # table rows
    t = re.sub(r"[*_#]{1,3}", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)  # links → text
    t = re.sub(r"\n{2,}", ". ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _strip_wake(heard: str, keyword: str) -> str:
    """Remove a leading/trailing wake word from a transcript.

    “jarvis what time is it” → “what time is it”; a bare greeting after the
    wake word (“hey jarvis”) means nothing actionable — return empty so the
    caller answers with a short prompt instead of parroting “hey”.
    """
    pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.I)
    m = pattern.search(heard)
    if not m:
        return heard
    before = heard[: m.start()].strip(" ,.!")
    after = heard[m.end():].strip(" ,.!")
    result = (after or before or "").strip()
    if result.lower() in ("hey", "hi", "hello", "ok", "okay", "yo", "please"):
        return ""
    return result


def capability_report() -> Dict[str, str]:
    """What this machine can do right now — shown by /jarvis and the app."""
    jarvis = Jarvis.__new__(Jarvis)  # probe without starting threads
    jarvis.speech = Speech()
    jarvis.wake = WakeWord()
    return {
        "wake_word": f"openWakeWord ('{jarvis.keyword}' neural model)" if jarvis.wake.mode == "openwakeword"
        else "keyword spotting (say the word 'jarvis')" if jarvis.speech.available
        else "push-to-talk (mic stack missing)",
        "stt": "SpeechRecognition + pyaudio" if jarvis.speech.available else "typed input only",
        "tts": "SAPI5 via claume voice stack",
        "install_hint": "pip install SpeechRecognition pyaudio openwakeword  ← full wake-word experience",
    }
