"""claume music — play music from a folder while you code.

A terminal music player built into the REPL (`/music`) and voice-controlled
through jarvis ("play some music", "next track", "what song is this").

* Windows: plays mp3/wav/wma/m4a through the built-in winmm MCI API — no
  dependencies needed.
* Linux/macOS: falls back to ffplay (ffmgeg) or afplay (macOS) if installed.
* Pure stdlib; the player runs on a daemon thread so coding never blocks.
"""
from __future__ import annotations

import ctypes
import random
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".wma", ".aac", ".opus"}
MUSIC_EXTS_RE = re.compile(r"\.(mp3|wav|flac|ogg|m4a|wma|aac|opus)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Library scanning
# ---------------------------------------------------------------------------
def scan_folder(folder: Path, recursive: bool = True) -> List[Path]:
    """Return audio files in *folder*, sorted by name."""
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        return []
    it = folder.rglob("*") if recursive else folder.glob("*")
    tracks = sorted(
        (p for p in it if p.is_file() and MUSIC_EXTS_RE.search(p.name)),
        key=lambda p: p.name.lower(),
    )
    return tracks


def _display_name(path: Path) -> str:
    """'01 - Midnight Drive.mp3' -> 'Midnight Drive' (best effort)."""
    stem = path.stem
    stem = re.sub(r"^\s*\d{1,3}\s*[-_.)\]]\s*", "", stem)  # strip leading numbers
    stem = re.sub(r"\s*[-_]\s*(official|audio|video|lyric[s]?).*", "", stem, flags=re.I)
    return stem.strip() or path.stem


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class _MciPlayer:
    """Windows winmm MCI — plays mp3/wav/wma/m4a without dependencies."""

    def __init__(self) -> None:
        self._winmm = ctypes.windll.winmm  # type: ignore[attr-defined]
        self._alias = "ccmusic"

    def _send(self, cmd: str) -> str:
        buf = ctypes.create_unicode_buffer(256)
        err = self._winmm.mciSendStringW(cmd, buf, 254, 0)
        return "" if err == 0 else buf.value

    def open(self, path: Path) -> None:
        self.close()
        p = str(path)
        ftype = "waveaudio" if path.suffix.lower() == ".wav" else "mpegvideo"
        self._send(f'open "{p}" type {ftype} alias {self._alias}')

    def play(self) -> None:
        self._send(f"play {self._alias}")

    def pause(self) -> None:
        self._send(f"pause {self._alias}")

    def resume(self) -> None:
        self._send(f"resume {self._alias}")

    def stop(self) -> None:
        self._send(f"stop {self._alias}")

    def close(self) -> None:
        self._send(f"close {self._alias}")

    def position_ms(self) -> int:
        buf = ctypes.create_unicode_buffer(64)
        self._winmm.mciSendStringW(f"status {self._alias} position", buf, 63, 0)
        try:
            return int(buf.value or 0)
        except ValueError:
            return 0

    def length_ms(self) -> int:
        buf = ctypes.create_unicode_buffer(64)
        self._winmm.mciSendStringW(f"status {self._alias} length", buf, 63, 0)
        try:
            return int(buf.value or 0)
        except ValueError:
            return 0

    def mode(self) -> str:
        buf = ctypes.create_unicode_buffer(64)
        self._winmm.mciSendStringW(f"status {self._alias} mode", buf, 63, 0)
        return (buf.value or "stopped").strip().lower()

    def volume(self, percent: int) -> None:
        vol = max(0, min(100, int(percent))) * 10  # MCI scale 0..1000
        self._send(f"setaudio {self._alias} volume to {vol}")


class _SubprocessPlayer:
    """ffplay/afplay fallback for Linux/macOS."""

    def __init__(self, cmd: List[str]) -> None:
        self._cmd = cmd
        self._proc: Optional[subprocess.Popen] = None
        self._started_at = 0.0
        self._paused = False
        self._pause_at = 0.0

    def open(self, path: Path) -> None:
        self.close()
        try:
            self._proc = subprocess.Popen(
                self._cmd + [str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            self._started_at = time.time()
            self._paused = False
            self._pause_at = 0.0
        except OSError:
            self._proc = None

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def play(self) -> None:
        if self._paused:
            self._started_at += time.time() - self._pause_at
            self._paused = False

    def pause(self) -> None:
        if self._alive() and not self._paused:
            self._paused = True
            self._pause_at = time.time()

    def resume(self) -> None:
        self.play()

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._proc = None

    close = stop

    def position_ms(self) -> int:
        if self._paused:
            return int((self._pause_at - self._started_at) * 1000)
        if self._alive():
            return int((time.time() - self._started_at) * 1000)
        return 0

    def length_ms(self) -> int:
        return 0  # unknown without ffprobe; watcher advances on process exit

    def mode(self) -> str:
        if self._paused:
            return "paused"
        return "playing" if self._alive() else "stopped"

    def volume(self, percent: int) -> None:
        pass  # not supported without extra tooling


def _make_backend():
    if subprocess.os.name == "nt":
        try:
            return _MciPlayer()
        except Exception:
            pass
    import shutil

    if shutil.which("ffplay"):
        return _SubprocessPlayer(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"])
    if shutil.which("afplay"):
        return _SubprocessPlayer(["afplay"])
    return None


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
def _fmt_ms(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60:02d}:{s % 60:02d}"


class MusicPlayer:
    """One shared player for the REPL and jarvis. Daemon-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.backend = _make_backend()
        self.folder: Optional[Path] = None
        self.tracks: List[Path] = []
        self.order: List[int] = []          # play order (indices into tracks)
        self.pos = 0                        # position within order
        self.playing = False
        self.paused = False
        self.shuffle = False
        self.loop = "all"                   # off | all | one
        self.volume = 70
        self._last_mode = "stopped"
        self._watcher: Optional[threading.Thread] = None
        self.on_track: List[Callable[[Path], None]] = []  # UI notifications

    # -- library ----------------------------------------------------------
    def load_folder(self, folder: Path) -> int:
        with self._lock:
            self.stop()
            self.folder = Path(folder).expanduser()
            self.tracks = scan_folder(self.folder)
            self.pos = 0
            self._reorder()
            return len(self.tracks)

    def _reorder(self) -> None:
        n = len(self.tracks)
        if self.shuffle:
            order = list(range(n))
            random.shuffle(order)
            # keep the currently-playing track first for continuity
            if order and self.order and self.pos < len(self.order):
                cur = self.order[self.pos]
                if cur in order:
                    order.remove(cur)
                    order.insert(0, cur)
            self.order = order
            self.pos = 0
        else:
            self.order = list(range(n))
            self.pos = min(self.pos, max(0, n - 1)) if n else 0

    # -- transport ----------------------------------------------------------
    def current(self) -> Optional[Path]:
        with self._lock:
            if not self.tracks or self.pos >= len(self.order):
                return None
            return self.tracks[self.order[self.pos]]

    def play_index(self, order_pos: Optional[int] = None) -> Optional[Path]:
        with self._lock:
            if not self.backend or not self.tracks:
                return None
            if order_pos is not None:
                self.pos = order_pos
            track = self.current()
            if track is None:
                return None
            self.backend.open(track)
            self.backend.volume(self.volume)
            self.backend.play()
            self.playing = True
            self.paused = False
            self._last_mode = "playing"
            self._ensure_watcher()
            for fn in self.on_track:
                try:
                    fn(track)
                except Exception:
                    pass
            return track

    def toggle(self) -> str:
        """play/pause toggle. Returns new state string."""
        with self._lock:
            if not self.playing:
                self.play_index()
                return "playing"
            if self.paused:
                self.backend.resume()
                self.paused = False
                return "playing"
            self.backend.pause()
            self.paused = True
            return "paused"

    def pause(self) -> None:
        with self._lock:
            if self.playing and not self.paused:
                self.backend.pause()
                self.paused = True

    def resume(self) -> None:
        with self._lock:
            if self.playing and self.paused:
                self.backend.resume()
                self.paused = False

    def stop(self) -> None:
        with self._lock:
            if self.backend is not None:
                try:
                    self.backend.stop()
                    self.backend.close()
                except Exception:
                    pass
            self.playing = False
            self.paused = False

    def next(self) -> Optional[Path]:
        with self._lock:
            if not self.tracks:
                return None
            if self.pos + 1 < len(self.order):
                self.pos += 1
            elif self.loop != "off":
                self.pos = 0
            else:
                self.stop()
                return None
            return self.play_index()

    def prev(self) -> Optional[Path]:
        with self._lock:
            if not self.tracks:
                return None
            # restart current if >3s in, else go to previous track
            if self.backend.position_ms() > 3000 and not self.paused:
                return self.play_index()
            self.pos = (self.pos - 1) % len(self.order)
            return self.play_index()

    def set_volume(self, percent: int) -> int:
        with self._lock:
            self.volume = max(0, min(100, int(percent)))
            if self.backend is not None:
                try:
                    self.backend.volume(self.volume)
                except Exception:
                    pass
            return self.volume

    def toggle_shuffle(self) -> bool:
        with self._lock:
            self.shuffle = not self.shuffle
            self._reorder()
            return self.shuffle

    def cycle_loop(self) -> str:
        with self._lock:
            self.loop = {"off": "all", "all": "one", "one": "off"}[self.loop]
            return self.loop

    def play_match(self, query: str) -> Optional[Path]:
        """Fuzzy-find a track/artist/album substring in the library."""
        with self._lock:
            if not self.tracks:
                return None
            q = query.lower().strip()
            if not q:
                return None
            words = [w for w in re.split(r"\s+", q) if w]
            best: Tuple[int, int] = (10**9, 10**9)  # (score, index)
            found: Optional[int] = None
            for i, t in enumerate(self.tracks):
                name = _display_name(t).lower()
                full = t.stem.lower()
                score = 0
                if q in name:
                    score = 0
                elif all(w in full for w in words):
                    score = 1
                elif any(w in full for w in words):
                    score = 2
                else:
                    continue
                if score < best[0]:
                    best = (score, i)
                    found = i
            if found is None:
                return None
            # map library index -> order position
            self.pos = self.order.index(found) if found in self.order else 0
            return self.play_index()

    # -- watcher: auto-advance --------------------------------------------
    def _ensure_watcher(self) -> None:
        if self._watcher is not None and self._watcher.is_alive():
            return
        self._watcher = threading.Thread(target=self._watch_loop, daemon=True,
                                         name="claume-music")
        self._watcher.start()

    def _watch_loop(self) -> None:
        while True:
            time.sleep(0.5)
            with self._lock:
                if not self.playing or self.paused:
                    continue
                mode = self.backend.mode()
                if mode == "stopped" and self._last_mode in ("playing", "paused"):
                    # track ended on its own
                    if self.loop == "one":
                        self.play_index()
                    else:
                        self.next()
                    continue
                self._last_mode = mode

    # -- status -------------------------------------------------------------
    def status(self) -> Dict[str, object]:
        with self._lock:
            cur = self.current()
            pos_ms = self.backend.position_ms() if (self.backend and self.playing) else 0
            len_ms = self.backend.length_ms() if (self.backend and self.playing) else 0
            return {
                "supported": self.backend is not None,
                "playing": self.playing and not self.paused,
                "paused": self.paused,
                "track": _display_name(cur) if cur else "",
                "path": str(cur) if cur else "",
                "index": (self.pos + 1) if self.tracks else 0,
                "count": len(self.tracks),
                "folder": str(self.folder) if self.folder else "",
                "position": _fmt_ms(pos_ms),
                "length": _fmt_ms(len_ms) if len_ms else "--:--",
                "pos_ms": pos_ms,
                "len_ms": len_ms,
                "volume": self.volume,
                "shuffle": self.shuffle,
                "loop": self.loop,
            }

    def now_playing(self) -> str:
        s = self.status()
        if s["paused"]:
            return f"⏸ {s['track']}"
        if s["playing"]:
            return f"▶ {s['track']} — {s['position']}/{s['length']}"
        return ""


# ---------------------------------------------------------------------------
# Shared singleton + voice intents (jarvis)
# ---------------------------------------------------------------------------
_shared: Optional[MusicPlayer] = None
_shared_lock = threading.Lock()


def get_player() -> MusicPlayer:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = MusicPlayer()
        return _shared


def _default_folder() -> Optional[Path]:
    """Last-used folder from config, else the user's Music folder."""
    from . import config as _config

    cfg = _config.Config()
    saved = cfg.get("music_folder")
    if saved and Path(saved).is_dir():
        return Path(saved)
    home = Path.home()
    for cand in (home / "Music", home / "music", home / "Downloads"):
        if cand.is_dir():
            return cand
    return None


_PLAY_RE = re.compile(r"^(?:play|put on|start)(?:\s+some)?\s+(.+)$", re.I)

def music_intent(text: str) -> Optional[str]:
    """Map a jarvis utterance to a music action.

    Returns an action string for the player router, or None when the
    utterance is not about music. Pure function — unit-testable.
    """
    t = (text or "").strip().lower().strip(".,!?")
    if not t:
        return None
    # drop wake word if present ("jarvis play music")
    t = re.sub(r"^(hey\s+|ok\s+)?(jarvis|claume)\s+", "", t)

    if re.search(r"\b(now playing|what song|which song|this song|what.s playing)\b", t):
        return "what"
    if re.search(r"\b(pause|hold)\b.*\b(music|song|track|player)\b|^(pause|hold)$", t):
        return "pause"
    if re.search(r"\b(resume|continue|unpause)\b", t) and re.search(r"\b(music|song|track|player|it)\b|^resume$", t):
        return "resume"
    if re.search(r"\b(stop|kill)\b.*\b(music|song|track|player)\b|^stop music$", t):
        return "stop"
    if re.search(r"\b(next|skip|another)\b.*\b(song|track|one)\b|^next$|^skip$", t):
        return "next"
    if re.search(r"\b(previous|last song|go back|rewind)\b", t) or re.search(r"\b(prev)\b.*\b(song|track)\b", t):
        return "prev"
    if re.search(r"\b(shuffle)\b", t):
        return "shuffle" if not re.search(r"\b(off)\b", t) else "shuffle-off"
    if re.search(r"\b(loop|repeat)\b", t):
        return "loop"
    m = re.search(r"\b(?:volume|vol)\b.*?(\d{1,3})\s*(?:percent|%|pc)?", t)
    if m:
        return f"volume {m.group(1)}"
    if re.search(r"\b(quiet|louder|loudest)\b", t):
        return "quiet" if "quiet" in t else "louder"
    if re.search(r"\b(music|songs?|playlist|tunes?|beats?)\b", t):
        # "play music" / "play some music" / bare "music"
        if re.match(r"^(play|put on|start)\b", t) or t in ("music", "songs", "playlist", "tunes", "beats"):
            m2 = _PLAY_RE.match(t)
            target = m2.group(1) if m2 else ""
            # strip filler words from "play some lofi music"
            target = re.sub(r"\b(some|the|my|music|song|songs|playlist|tunes?|beats?)\b", " ", target).strip()
            return f"play {target}".strip()
    # "play <name>" for a specific track
    m3 = re.match(r"^(?:play|put on|start)\s+(.+)$", t)
    if m3 and not re.search(r"\b(the|a|an)\b", m3.group(1)[:4]):
        return f"play {m3.group(1)}"
    return None


# ---------------------------------------------------------------------------
# Terminal UI rendering
# ---------------------------------------------------------------------------
def render_panel(out: Callable[[str], None], limit: int = 8) -> None:
    """Draw the now-playing panel (used by the /music command)."""
    from .ui import BOLD, DIM, GREY, GOLD, MINT, RESET  # lazy: theme-aware

    p = get_player()
    s = p.status()
    width = 52
    if not s["supported"]:
        out(f"{GOLD}⚠{RESET} {GREY}no audio backend — install ffmpeg (ffplay) for playback{RESET}")
        return
    if not s["folder"]:
        out(f"{MINT}♪{RESET} {GREY}no folder loaded — /music <folder> or /music open{RESET}")
        return

    # progress bar
    pos, length = int(s["pos_ms"]), int(s["len_ms"])
    if length > 0:
        frac = max(0.0, min(1.0, pos / length))
    else:
        frac = 0.0
    filled = int(round(frac * 24))
    bar = f"{MINT}{'━' * filled}{GREY}{'─' * (24 - filled)}{RESET}"
    state = "▶" if s["playing"] else ("⏸" if s["paused"] else "■")
    mode_bits = []
    if s["shuffle"]:
        mode_bits.append("shuffle")
    mode_bits.append(f"loop:{s['loop']}")

    out(f"{DIM}┌{'─' * width}┐{RESET}")
    out(f"{DIM}│{RESET} {MINT}♫{RESET} {BOLD}claume music{RESET} {GREY}· {s['index']}/{s['count']} tracks · {' · '.join(mode_bits)} · vol {s['volume']}%{RESET}")
    title = str(s["track"])[: width - 12]
    out(f"{DIM}│{RESET} {state} {BOLD}{title}{RESET}")
    out(f"{DIM}│{RESET} {bar} {s['position']}{GREY}/{s['length']}{RESET}")
    out(f"{DIM}│{RESET} {GREY}/music play|pause|next|prev|stop|vol N|shuffle|loop|list|open{RESET}")
    out(f"{DIM}└{'─' * width}┘{RESET}")


def render_playlist(out: Callable[[str], None], limit: int = 15) -> None:
    from .ui import BOLD, GREY, GREEN, RESET

    p = get_player()
    s = p.status()
    if not s["folder"]:
        out(f"{GREY}no folder loaded{RESET}")
        return
    out(f"{BOLD}playlist — {s['folder']}{RESET} {GREY}({s['count']} tracks){RESET}")
    with p._lock:
        for order_pos, idx in enumerate(p.order[:limit]):
            track = p.tracks[idx]
            mark = f"{GREEN}▸{RESET}" if order_pos == p.pos else " "
            out(f" {mark} {order_pos + 1:>2}. {_display_name(track)}")
        if len(p.order) > limit:
            out(f"   {GREY}… and {len(p.order) - limit} more{RESET}")
