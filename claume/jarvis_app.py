"""claume jarvis_app — the human-like desktop window for the Jarvis plugin.

Zero-dependency tkinter UI in the spirit of 21st.dev / reactbits motion
pieces and the top jarvis repos on GitHub:

* an **animated core** — a layered arc-reactor orb that breathes when
  idle, ripples while listening, spins a ring while thinking and glows
  amber while speaking (canvas arcs, eased with an after() loop);
* a **typewriter status line** and a compact transcript;
* state-driven colors — cyan listening, violet thinking, amber speaking,
  calm blue idle — on a near-black glass panel;
* drag-anywhere frameless window, always-on-top, click core to talk
  (push-to-talk), mic button, Esc or ✕ to close.

Runs standalone (`python -m claume.jarvis_app`) or inside claume via
`/jarvis`. The engine (jarvis.Jarvis) does wake word + STT + LLM + TTS;
this file only renders and feeds it.
"""
from __future__ import annotations

import math
import queue
import sys
import threading
import tkinter as tk
from typing import Any, Dict, Optional

from . import config
from .jarvis import Jarvis, capability_report

# Palette (echoes claume studio: near-black glass, one accent per state)
BG = "#0a0e14"
PANEL = "#0f1520"
TEXT = "#c8d3de"
MUTED = "#5c6b7a"

STATE_COLORS = {
    "idle": ("#3d7dff", "#0e5bd8"),       # calm blue core
    "listening": ("#22d3ee", "#0891b2"),  # cyan ripple
    "thinking": ("#a78bfa", "#7c3aed"),   # violet ring
    "speaking": ("#fbbf24", "#d97706"),   # amber glow
}

STATE_LINES = {
    "idle": "Say “Jarvis” — or click the core to talk",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
}


class JarvisApp:
    def __init__(self) -> None:
        self.cfg = config.Config()
        self.jarvis = Jarvis(speak_replies=bool(self.cfg.get("jarvis_speak_replies", True)))
        self.q: "queue.Queue[Dict[str, str]]" = queue.Queue()
        self._t = 0.0
        self._ripples: list = []
        self._typing_after: Optional[str] = None
        self._drag = {"x": 0, "y": 0}

        self.root = tk.Tk()
        self.root.title("jarvis — claume")
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)  # frameless; drag anywhere
        self._center(360, 520)

        self._build()
        self.jarvis.on_state(self._on_state)
        self._animate()
        self.root.after(50, self._pump)
        self.root.bind("<Escape>", lambda e: self._close())

    # -- layout -------------------------------------------------------------
    def _center(self, w: int, h: int) -> None:
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"{w}x{h}+{sw - w - 60}+80")

    def _build(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(header, text="J A R V I S", font=("Segoe UI", 11, "bold"),
                 fg=TEXT, bg=BG).pack(side="left")
        tk.Label(header, text="· claume", font=("Segoe UI", 9),
                 fg=MUTED, bg=BG).pack(side="left", padx=6)
        close = tk.Label(header, text="✕", font=("Segoe UI", 11), fg=MUTED, bg=BG, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self._close())

        # the orb
        self.canvas = tk.Canvas(self.root, width=300, height=300, bg=PANEL,
                                highlightthickness=0, bd=0)
        self.canvas.pack(pady=(18, 6))
        self.core = self.canvas.create_oval(0, 0, 0, 0, width=0)
        self.core_glow = self.canvas.create_oval(0, 0, 0, 0, width=0)
        self.ring = self.canvas.create_arc(0, 0, 0, 0, start=0, extent=270,
                                           style="arc", width=3, outline=STATE_COLORS["idle"][0])
        self.canvas.tag_bind(self.core, "<Button-1>", lambda e: self._push_to_talk())
        for w in (self.canvas,):
            w.bind("<ButtonPress-1>", self._drag_start, add="+")
            w.bind("<B1-Motion>", self._drag_move, add="+")

        self.status = tk.Label(self.root, text=STATE_LINES["idle"], font=("Segoe UI", 10),
                               fg=TEXT, bg=PANEL, wraplength=300, justify="center")
        self.status.pack(pady=(2, 8))

        self.transcript = tk.Label(self.root, text="", font=("Segoe UI", 9, "italic"),
                                   fg=MUTED, bg=PANEL, wraplength=310, justify="left")
        self.transcript.pack(padx=20, pady=(0, 10), fill="x")

        bar = tk.Frame(self.root, bg=PANEL)
        bar.pack(fill="x", side="bottom", pady=(0, 14), padx=18)
        self.mic_btn = tk.Label(bar, text="🎙  talk", font=("Segoe UI", 10), fg=TEXT,
                                bg="#16202e", padx=14, pady=6, cursor="hand2")
        self.mic_btn.pack(side="left")
        self.mic_btn.bind("<Button-1>", lambda e: self._push_to_talk())
        caps = capability_report()
        tk.Label(bar, text=caps["wake_word"].split(" (")[0], font=("Segoe UI", 8),
                 fg=MUTED, bg=PANEL).pack(side="right")

    # -- drag ---------------------------------------------------------------
    def _drag_start(self, e: Any) -> None:
        self._drag = {"x": e.x, "y": e.y}

    def _drag_move(self, e: Any) -> None:
        x = self.root.winfo_x() - self._drag["x"] + e.x
        y = self.root.winfo_y() - self._drag["y"] + e.y
        self.root.geometry(f"+{x}+{y}")

    # -- animation -----------------------------------------------------------
    def _animate(self) -> None:
        self._t += 0.035
        t = self._t
        cx, cy, base_r = 150, 150, 62
        state = self.jarvis.state
        c1, c2 = STATE_COLORS.get(state, STATE_COLORS["idle"])

        if state == "idle":
            r = base_r + math.sin(t * 1.6) * 3          # breathing
        elif state == "thinking":
            r = base_r - 3 + math.sin(t * 9) * 1.5      # shiver
        else:
            r = base_r + 2

        self.canvas.coords(self.core_glow, cx - r - 16, cy - r - 16, cx + r + 16, cy + r + 16)
        self.canvas.itemconfig(self.core_glow, fill=c2, outline="")
        self.canvas.coords(self.core, cx - r, cy - r, cx + r, cy + r)
        self.canvas.itemconfig(self.core, fill=c1, outline="")

        if state == "thinking":
            self.canvas.itemconfig(self.ring, state="normal", outline=c1)
            start = (t * 160) % 360
            self.canvas.itemconfig(self.ring, start=start, extent=260)
        elif state == "listening" and len(self._ripples) < 3 and randomish(t):
            self._ripples.append({"r": base_r + 8, "id": self.canvas.create_oval(
                cx - base_r - 8, cy - base_r - 8, cx + base_r + 8, cy + base_r + 8,
                outline=c1, width=2)})
        for rp in list(self._ripples):
            rp["r"] += 2.2
            pad = rp["r"]
            self.canvas.coords(rp["id"], cx - pad, cy - pad, cx + pad, cy + pad)
            self.canvas.itemconfig(rp["id"], outline=c1)
            if rp["r"] > 140:
                self.canvas.delete(rp["id"])
                self._ripples.remove(rp)
        if state != "thinking" and state != "listening":
            self.canvas.itemconfig(self.ring, state="hidden")

        # color lerp on the status label
        self.status.config(fg={"idle": TEXT, "listening": c1, "thinking": c1, "speaking": c1}[state])
        self.root.after(33, self._animate)

    # -- engine events (thread-safe via queue) --------------------------------
    def _on_state(self, state: str, detail: str) -> None:
        self.q.put({"state": state, "detail": detail})

    def _pump(self) -> None:
        try:
            while True:
                ev = self.q.get_nowait()
                st, detail = ev["state"], ev["detail"]
                self.status.config(text=STATE_LINES.get(st, st))
                if st == "listening" and detail and detail != "wake word detected":
                    self._typewriter(f"you: {detail}")
                elif st == "speaking" and detail:
                    self._typewriter(f"jarvis: {detail}")
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    def _typewriter(self, line: str) -> None:
        if self._typing_after:
            try:
                self.root.after_cancel(self._typing_after)
            except Exception:
                pass
        shown = {"n": 0}

        def step() -> None:
            shown["n"] += 2
            self.transcript.config(text=line[: shown["n"]])
            if shown["n"] < len(line):
                self._typing_after = self.root.after(18, step)

        step()

    # -- actions --------------------------------------------------------------
    def _push_to_talk(self) -> None:
        def work() -> None:
            heard = self.jarvis.speech.listen_once()
            if heard:
                self.jarvis.ask(heard)
            else:
                self.q.put({"state": "idle", "detail": ""})
                self.q.put({"state": "idle", "detail": ""})
        threading.Thread(target=work, daemon=True).start()

    def run_background_listener(self) -> None:
        """Wake-word loop on a thread so the window stays responsive."""
        threading.Thread(
            target=self.jarvis.run_forever,
            kwargs={"on_reply": lambda heard, reply: None},
            daemon=True,
        ).start()

    def _close(self) -> None:
        self.jarvis.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self.run_background_listener()
        self.root.mainloop()


def randomish(t: float) -> bool:
    """Deterministic-ish ripple gate so listening ripples feel organic."""
    return int(t * 10) % 7 == 0


def main() -> int:
    app = JarvisApp()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
