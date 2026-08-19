"""
home_simulator.py
Tkinter-based GUI dashboard + state machine for the simulated smart home.
Consumes DeviceAction objects (from ai_engine.py) and updates both the
in-memory state and the visual dashboard.

Visual theme: a dark holographic HUD (heads-up display), inspired by
sci-fi "AI operating system" interfaces — cyan glow, radial gauges,
corner-bracket panels, tracked/uppercase typography, and a rotating
reactor-style status core.

Layout:
  - A reactor-style "core" animation sits centered at the top of the main
    column, with a live LISTENING / PAUSED / IDLE readout directly beneath
    it, and the Pause/Resume control beneath that.
  - Below the core, a responsive device grid (living room, kitchen, etc.)
    that reflows and rescales as the window is resized.
  - A fixed-width command log sits as a full-height "menu bar" on the
    right edge of the window.
  - A status bar spans the bottom.

Public API is unchanged from the previous version, so main.py does not
need any changes:
    HomeSimulator(root, on_toggle_pause=None)
    .root                          -> the Tk root, for root.after(...)
    .set_status(text)
    .set_listening_active(bool)
    .add_history_entry(heard, response)
    .apply_action(action) / .apply_actions(actions)
"""

import logging
import math
import tkinter as tk
from tkinter import font as tkfont

from ai_engine import DeviceAction

logger = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------
DEFAULT_STATE = {
    "living_room_light": False,
    "kitchen_light": False,
    "bedroom_light": False,
    "thermostat": 20,  # degrees C
    "front_door_lock": True,  # True = locked
    "tv": False,
}

LIGHT_DEVICES = {"living_room_light", "kitchen_light", "bedroom_light"}

DEVICE_LABELS = {
    "living_room_light": "LIVING ROOM",
    "kitchen_light": "KITCHEN",
    "bedroom_light": "BEDROOM",
    "thermostat": "CLIMATE",
    "front_door_lock": "FRONT DOOR",
    "tv": "ENTERTAINMENT",
}

DEVICE_ORDER = list(DEVICE_LABELS.keys())
DEVICE_GRID_COLS = 3

# -- HUD Palette --------------------------------------------------------------
COLOR_BG = "#03080B"            # window background (near-black)
COLOR_PANEL = "#060F14"         # card / sidebar background
COLOR_PANEL_EDGE = "#0E2530"    # faint card border, inactive
COLOR_GRID = "#0A1B22"          # faint grid/scan lines
COLOR_TEXT = "#DFFBFF"          # primary HUD text (near-white cyan)
COLOR_MUTED = "#4E7C8A"         # secondary / label text
COLOR_CYAN = "#3CE8FF"          # core accent - "on" / active / energized
COLOR_CYAN_DIM = "#0F4C5C"      # dim cyan for inactive glyph strokes
COLOR_CYAN_GLOW = "#123943"     # soft glow fill behind an active icon
COLOR_AMBER = "#FFB13C"         # paused / warning accent
COLOR_RED = "#FF4B4B"           # alert accent (unlocked door)
COLOR_OFF = "#2B4149"           # inactive device stroke color

FONT_FAMILY = "Consolas"        # monospace reads as "instrument panel"
FONT_FAMILY_UI = "Segoe UI"

# Fallback size only, used before the window/canvas is first mapped by the
# geometry manager (winfo_width()/height() report 1 until then). Once the
# canvas has a real size, rendering always uses that real size instead -
# never a floor larger than the actual pixels available, or content clips.
FALLBACK_CARD_W, FALLBACK_CARD_H = 210, 170


def _tracked(text: str, gap: str = " ") -> str:
    """Return text with letters loosely spaced, for a tracked HUD label look."""
    return gap.join(text.upper())


class HomeSimulator:
    """Owns the device state and the Tkinter HUD dashboard rendering it."""

    def __init__(self, root: tk.Tk, on_toggle_pause=None):
        self.root = root
        self.state = dict(DEFAULT_STATE)
        self.widgets = {}  # device_key -> {"canvas": Canvas}
        self.on_toggle_pause = on_toggle_pause  # callback(bool is_paused) wired by main.py
        self.is_paused = False
        self._pulse_phase = 0
        self._core_angle = 0
        self._listening_active = False

        self.root.title("H.O.M.E. — Holographic Operations & Monitoring Engine")
        self.root.configure(bg=COLOR_BG)
        self.root.geometry("980x680")
        # Lowered from 760x560 - that floor was taller/wider than the
        # available space when running next to an editor window on a
        # laptop screen, pushing part of the window off-screen with no
        # way to reach it. This still keeps things legible while letting
        # the window actually shrink to fit smaller/split screens.
        self.root.minsize(620, 460)
        self.root.resizable(True, True)

        self._build_ui()
        self.refresh_all()
        self._animate_core()

    # -- UI construction ------------------------------------------------------
    def _build_ui(self):
        title_font = tkfont.Font(family=FONT_FAMILY, size=17, weight="bold")
        subtitle_font = tkfont.Font(family=FONT_FAMILY_UI, size=9)
        listen_font = tkfont.Font(family=FONT_FAMILY, size=13, weight="bold")
        self.card_name_font = tkfont.Font(family=FONT_FAMILY, size=10, weight="bold")
        self.card_status_font = tkfont.Font(family=FONT_FAMILY, size=10)

        # Root uses a 2-column grid: main column (flexible) + log sidebar
        # (fixed-ish width), with a header spanning both and a status bar
        # spanning both, so everything reflows together on resize.
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=0, minsize=120)
        self.root.rowconfigure(1, weight=1)

        # -- Header (spans full width) --------------------------------------
        header = tk.Frame(self.root, bg=COLOR_BG)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(16, 6))
        tk.Label(
            header, text=_tracked("Home OS"), font=title_font,
            bg=COLOR_BG, fg=COLOR_CYAN,
        ).pack(anchor="w")
        tk.Label(
            header, text=_tracked("Voice-Controlled Environment"),
            font=subtitle_font, bg=COLOR_BG, fg=COLOR_MUTED,
        ).pack(anchor="w")
        tk.Frame(self.root, bg=COLOR_PANEL_EDGE, height=1).grid(
            row=0, column=0, columnspan=2, sticky="sew", padx=18
        )

        # -- Main column (row 1, col 0) --------------------------------------
        main_col = tk.Frame(self.root, bg=COLOR_BG)
        main_col.grid(row=1, column=0, sticky="nsew")
        main_col.columnconfigure(0, weight=1)
        main_col.rowconfigure(1, weight=1)  # device grid area expands

        # -- Core: reactor animation, "LISTENING" readout, pause button ------
        core_block = tk.Frame(main_col, bg=COLOR_BG)
        core_block.grid(row=0, column=0, pady=(14, 6))

        self.core_canvas = tk.Canvas(
            core_block, width=180, height=180, bg=COLOR_BG, highlightthickness=0
        )
        self.core_canvas.pack()

        self.listen_var = tk.StringVar(value=_tracked("Idle"))
        self.listen_label = tk.Label(
            core_block, textvariable=self.listen_var, font=listen_font,
            bg=COLOR_BG, fg=COLOR_MUTED,
        )
        self.listen_label.pack(pady=(6, 10))

        self.pause_button = tk.Button(
            core_block, text=_tracked("Pause Listening"),
            font=(FONT_FAMILY_UI, 9, "bold"),
            bg=COLOR_BG, fg=COLOR_CYAN, activebackground=COLOR_CYAN_GLOW,
            activeforeground=COLOR_CYAN, relief="flat", bd=0,
            highlightbackground=COLOR_CYAN_DIM, highlightthickness=1,
            padx=14, pady=7, cursor="hand2",
            command=self._handle_pause_toggle,
        )
        self.pause_button.pack()

        # -- Device grid (responsive - reflows/rescales with the window) ----
        grid_wrap = tk.Frame(main_col, bg=COLOR_BG)
        grid_wrap.grid(row=1, column=0, sticky="nsew", padx=14, pady=(8, 10))
        grid_wrap.columnconfigure(0, weight=1)
        grid_wrap.rowconfigure(0, weight=1)

        grid = tk.Frame(grid_wrap, bg=COLOR_BG)
        grid.grid(row=0, column=0, sticky="nsew")
        n_rows = math.ceil(len(DEVICE_ORDER) / DEVICE_GRID_COLS)
        for i in range(DEVICE_GRID_COLS):
            grid.columnconfigure(i, weight=1, uniform="devcol")
        for i in range(n_rows):
            grid.rowconfigure(i, weight=1, uniform="devrow")

        for idx, device in enumerate(DEVICE_ORDER):
            row, col = divmod(idx, DEVICE_GRID_COLS)
            card_canvas = tk.Canvas(
                grid, width=FALLBACK_CARD_W, height=FALLBACK_CARD_H,
                bg=COLOR_BG, highlightthickness=0,
            )
            card_canvas.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            card_canvas.bind("<Configure>", lambda e, d=device: self._render_device(d))
            self.widgets[device] = {"canvas": card_canvas}

        # -- Right sidebar: command log, full height "menu bar" -------------
        # Width lowered from 160 -> 130 to match the smaller minsize floor.
        sidebar = tk.Frame(self.root, bg=COLOR_PANEL, width=130)
        sidebar.grid(row=1, column=1, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)
        tk.Frame(sidebar, bg=COLOR_CYAN_DIM, width=1).place(x=0, y=0, relheight=1)

        tk.Label(
            sidebar, text=_tracked("Command Log", gap=""), font=(FONT_FAMILY, 9, "bold"),
            bg=COLOR_PANEL, fg=COLOR_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(14, 6))

        log_area = tk.Frame(sidebar, bg=COLOR_PANEL)
        log_area.grid(row=1, column=0, sticky="nsew", padx=(6, 2), pady=(0, 10))
        log_area.columnconfigure(0, weight=1)
        log_area.rowconfigure(0, weight=1)

        scrollbar = tk.Scrollbar(log_area, orient="vertical",
                                  troughcolor=COLOR_PANEL, bg=COLOR_PANEL_EDGE)
        # A Text widget wraps long commands onto multiple lines instead of
        # clipping them the way a Listbox would at a narrow sidebar width.
        self.history_text = tk.Text(
            log_area, width=18, bg=COLOR_PANEL, fg=COLOR_TEXT, wrap="word",
            borderwidth=0, highlightthickness=0, padx=0, pady=0,
            font=(FONT_FAMILY, 8), spacing1=2, spacing3=8, cursor="arrow",
            yscrollcommand=scrollbar.set,
        )
        self.history_text.tag_configure("heard", foreground=COLOR_TEXT,
                                         font=(FONT_FAMILY, 8, "bold"))
        self.history_text.tag_configure("resp", foreground=COLOR_CYAN,
                                         font=(FONT_FAMILY, 8))
        self.history_text.tag_configure("sep", foreground=COLOR_MUTED)
        self.history_text.configure(state="disabled")
        scrollbar.configure(command=self.history_text.yview)
        self.history_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._history_entries = []  # most-recent-first list of (heard, response)

        # -- Status bar (spans full width) -----------------------------------
        status_bar = tk.Frame(self.root, bg=COLOR_PANEL)
        status_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        tk.Frame(status_bar, bg=COLOR_CYAN_DIM, height=1).pack(fill="x")
        self.status_var = tk.StringVar(value="SYSTEM READY. AWAITING VOICE COMMAND...")
        tk.Label(
            status_bar, textvariable=self.status_var, bg=COLOR_PANEL, fg=COLOR_CYAN,
            font=(FONT_FAMILY, 10), anchor="w", padx=18, pady=10,
        ).pack(fill="x")

    # -- Card chrome (shared panel frame + corner brackets) --------------------
    def _draw_card_frame(self, canvas: tk.Canvas, w: int, h: int, active: bool, alert: bool = False):
        edge = COLOR_RED if alert else (COLOR_CYAN if active else COLOR_PANEL_EDGE)

        canvas.create_rectangle(1, 1, w - 1, h - 1, fill=COLOR_PANEL, outline="")

        for y in range(10, h - 10, 10):
            canvas.create_line(6, y, w - 6, y, fill=COLOR_GRID)

        canvas.create_rectangle(2, 2, w - 2, h - 2, outline=edge, width=1)

        bl = max(8, min(18, int(min(w, h) * 0.12)))  # bracket leg length, scaled
        pts = [
            (4, 4 + bl, 4, 4, 4 + bl, 4),
            (w - 4 - bl, 4, w - 4, 4, w - 4, 4 + bl),
            (4, h - 4 - bl, 4, h - 4, 4 + bl, h - 4),
            (w - 4 - bl, h - 4, w - 4, h - 4, w - 4, h - 4 - bl),
        ]
        for x1, y1, x2, y2, x3, y3 in pts:
            canvas.create_line(x1, y1, x2, y2, x3, y3, fill=edge, width=2)

    # -- Icon drawing (all icons are strokes on the HUD-cyan palette) ----------
    def _draw_bulb(self, canvas: tk.Canvas, cx, cy, r, is_on: bool):
        stroke = COLOR_CYAN if is_on else COLOR_OFF
        if is_on:
            canvas.create_oval(cx - r - r * 0.5, cy - r - r * 0.5, cx + r + r * 0.5, cy + r + r * 0.5,
                                fill=COLOR_CYAN_GLOW, outline="")
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=stroke, width=2,
                            fill=COLOR_PANEL if not is_on else "")
        if is_on:
            for ang in range(0, 360, 45):
                rad = math.radians(ang)
                x1, y1 = cx + math.cos(rad) * (r * 0.7), cy + math.sin(rad) * (r * 0.7)
                x2, y2 = cx + math.cos(rad) * (r * 1.25), cy + math.sin(rad) * (r * 1.25)
                canvas.create_line(x1, y1, x2, y2, fill=COLOR_CYAN, width=1)
        canvas.create_rectangle(cx - r * 0.35, cy + r - 2, cx + r * 0.35, cy + r + r * 0.5,
                                 outline=stroke, width=1)

    def _draw_lock(self, canvas: tk.Canvas, cx, cy, r, is_locked: bool):
        stroke = COLOR_CYAN if is_locked else COLOR_RED
        glow = COLOR_CYAN_GLOW if is_locked else "#3A1414"
        top = cy - r * 0.7
        canvas.create_oval(cx - r * 1.3, top - r * 0.3, cx + r * 1.3, top + r * 2,
                            fill=glow, outline="")
        if is_locked:
            canvas.create_arc(cx - r * 0.7, top - r * 0.4, cx + r * 0.7, top + r,
                               start=0, extent=180, style="arc", outline=stroke, width=3)
        else:
            canvas.create_arc(cx - r * 0.7, top - r * 0.6, cx + r * 0.7, top + r * 0.7,
                               start=25, extent=180, style="arc", outline=stroke, width=3)
        canvas.create_rectangle(cx - r * 0.85, top + r * 0.7, cx + r * 0.85, top + r * 2,
                                 outline=stroke, width=2, fill=COLOR_PANEL)
        canvas.create_oval(cx - r * 0.15, top + r * 1.1, cx + r * 0.15, top + r * 1.4,
                            fill=stroke, outline="")

    def _draw_thermostat(self, canvas: tk.Canvas, cx, cy, r, temp: float):
        canvas.create_oval(cx - r * 1.25, cy - r * 1.25, cx + r * 1.25, cy + r * 1.25,
                            fill=COLOR_CYAN_GLOW, outline="")
        for ang in range(225, -46, -27):
            rad = math.radians(ang)
            x1, y1 = cx + math.cos(rad) * (r - 4), cy - math.sin(rad) * (r - 4)
            x2, y2 = cx + math.cos(rad) * (r + 2), cy - math.sin(rad) * (r + 2)
            canvas.create_line(x1, y1, x2, y2, fill=COLOR_CYAN_DIM, width=1)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=COLOR_PANEL_EDGE, width=2)
        # Range matches ai_engine.py's set_temperature validator (7-35C) -
        # keep these two in sync if the range ever changes again.
        clamped = max(7, min(35, temp))
        pct = (clamped - 7) / 28.0
        extent = 270 * pct
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=225, extent=-extent,
                           style="arc", outline=COLOR_CYAN, width=4)
        font_size = max(9, int(r * 0.45))
        canvas.create_text(cx, cy, text=f"{temp:.0f}°", fill=COLOR_TEXT,
                            font=(FONT_FAMILY, font_size, "bold"))

    def _draw_tv(self, canvas: tk.Canvas, cx, cy, r, is_on: bool):
        stroke = COLOR_CYAN if is_on else COLOR_OFF
        glow = COLOR_CYAN_GLOW if is_on else COLOR_PANEL
        w, h = r * 1.7, r
        canvas.create_rectangle(cx - w, cy - h, cx + w, cy + h, fill=glow, outline=stroke, width=2)
        canvas.create_rectangle(cx - w * 0.25, cy + h + 2, cx + w * 0.25, cy + h + h * 0.3,
                                 outline=stroke, width=1)
        if is_on:
            for i, frac in enumerate((-0.4, 0, 0.4)):
                lw = w * (1 - abs(frac))
                y = cy + h * frac
                canvas.create_line(cx - lw, y, cx + lw, y, fill=COLOR_CYAN, width=1)
        else:
            canvas.create_line(cx - w * 0.4, cy - h * 0.4, cx + w * 0.4, cy + h * 0.4, fill=stroke)
            canvas.create_line(cx - w * 0.4, cy + h * 0.4, cx + w * 0.4, cy - h * 0.4, fill=stroke)

    # -- Rendering --------------------------------------------------------------
    def refresh_all(self):
        for device in self.widgets:
            self._render_device(device)

    def _render_device(self, device: str):
        canvas = self.widgets[device]["canvas"]
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1 or h <= 1:
            # Not yet mapped/sized by the geometry manager - use the
            # configured starting size just for this first draw.
            w, h = FALLBACK_CARD_W, FALLBACK_CARD_H
        # No further floor here: once the canvas is mapped, we always draw
        # at its *real* current size. Forcing a larger minimum than the
        # actual canvas is what caused content to be drawn past the visible
        # area (clipped/cut off) whenever the window was shrunk.

        canvas.delete("all")
        value = self.state[device]
        cx, cy = w / 2, h * 0.42
        r = max(10, min(w, h) * 0.16)

        if device in LIGHT_DEVICES:
            is_on = bool(value)
            self._draw_card_frame(canvas, w, h, active=is_on)
            self._draw_bulb(canvas, cx, cy, r, is_on)
            status_text, status_color = ("ONLINE", COLOR_CYAN) if is_on else ("STANDBY", COLOR_MUTED)
        elif device == "thermostat":
            self._draw_card_frame(canvas, w, h, active=True)
            self._draw_thermostat(canvas, cx, cy, r, float(value))
            status_text, status_color = (f"TARGET {value:.0f}°C", COLOR_CYAN)
        elif device == "front_door_lock":
            locked = bool(value)
            self._draw_card_frame(canvas, w, h, active=locked, alert=not locked)
            self._draw_lock(canvas, cx, cy, r, locked)
            status_text, status_color = ("SECURED", COLOR_CYAN) if locked else ("UNLOCKED", COLOR_RED)
        elif device == "tv":
            is_on = bool(value)
            self._draw_card_frame(canvas, w, h, active=is_on)
            self._draw_tv(canvas, cx, cy, r, is_on)
            status_text, status_color = ("ONLINE", COLOR_CYAN) if is_on else ("STANDBY", COLOR_MUTED)
        else:
            return

        name_size = max(7, min(10, int(w * 0.05)))
        canvas.create_text(w / 2, h * 0.8, text=_tracked(DEVICE_LABELS[device]),
                            fill=COLOR_TEXT, font=(FONT_FAMILY, name_size, "bold"))
        canvas.create_text(w / 2, h * 0.92, text=_tracked(status_text),
                            fill=status_color, font=(FONT_FAMILY, name_size))

    def set_status(self, text: str):
        self.status_var.set(text.upper())

    def add_history_entry(self, heard_text: str, response_text: str):
        self._history_entries.insert(0, (heard_text, response_text))
        self._history_entries = self._history_entries[:40]  # cap growth over a long session
        self._render_history()

    def _render_history(self):
        text = self.history_text
        text.configure(state="normal")
        text.delete("1.0", "end")
        for i, (heard, response) in enumerate(self._history_entries):
            text.insert("end", f'» "{heard}"\n', "heard")
            text.insert("end", f'  → {response}\n', "resp")
            if i < len(self._history_entries) - 1:
                text.insert("end", "─" * 12 + "\n", "sep")
        text.configure(state="disabled")

    # -- Reactor-style listening indicator (the "loading" effect) ---------------
    def set_listening_active(self, active: bool):
        self._listening_active = active

    def _animate_core(self):
        c = self.core_canvas
        c.delete("all")
        cx, cy, r_outer, r_inner = 90, 90, 78, 35

        r_mid = (r_outer + r_inner) / 2

        if self.is_paused:
            color, glow = COLOR_AMBER, "#3A2A0E"
            c.create_oval(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                          outline=color, width=3)
            c.create_oval(cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid,
                          outline=COLOR_CYAN_DIM, width=1)
            c.create_oval(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                          fill=glow, outline=color, width=2)
            self.listen_var.set(_tracked("Paused"))
            self.listen_label.configure(fg=COLOR_AMBER)
        elif self._listening_active:
            color, glow = COLOR_CYAN, COLOR_CYAN_GLOW
            self._pulse_phase = (self._pulse_phase + 1) % 40
            brightness = 0.55 + 0.45 * abs(math.sin(self._pulse_phase / 40 * math.pi))
            core_fill = f"#{int(0x3C*brightness):02x}{int(0xE8*brightness):02x}{int(0xFF*brightness):02x}"
            self._core_angle = (self._core_angle + 9) % 360
            c.create_oval(cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid,
                          outline=COLOR_CYAN_DIM, width=1)
            for i in range(4):
                start = self._core_angle + i * 90
                c.create_arc(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                             start=start, extent=55, style="arc", outline=color, width=5)
            for i in range(4):
                start = -self._core_angle + i * 90
                c.create_arc(cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid,
                             start=start, extent=30, style="arc", outline=color, width=2)
            c.create_oval(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                          fill=core_fill, outline="")
            self.listen_var.set(_tracked("Listening"))
            self.listen_label.configure(fg=COLOR_CYAN)
        else:
            color = COLOR_MUTED
            c.create_oval(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                          outline=COLOR_PANEL_EDGE, width=3)
            c.create_oval(cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid,
                          outline=COLOR_PANEL_EDGE, width=1)
            c.create_oval(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                          fill=COLOR_PANEL, outline=color, width=2)
            self.listen_var.set(_tracked("Idle"))
            self.listen_label.configure(fg=COLOR_MUTED)

        self.root.after(80, self._animate_core)

    # -- Pause/Resume -------------------------------------------------------------
    def _handle_pause_toggle(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.pause_button.configure(text=_tracked("Resume Listening"), fg=COLOR_AMBER,
                                         highlightbackground=COLOR_AMBER)
            self.set_status("Paused. Click Resume to continue.")
        else:
            self.pause_button.configure(text=_tracked("Pause Listening"), fg=COLOR_CYAN,
                                         highlightbackground=COLOR_CYAN_DIM)
            self.set_status("System ready. Awaiting voice command...")
        if self.on_toggle_pause:
            self.on_toggle_pause(self.is_paused)

    # -- State machine --------------------------------------------------------------
    def apply_action(self, action: DeviceAction):
        """Mutate state based on a single DeviceAction, then re-render that card."""
        target = action.target
        act = action.action

        if act == "turn_on":
            self.state[target] = True
        elif act == "turn_off":
            self.state[target] = False
        elif act == "lock":
            self.state[target] = True
        elif act == "unlock":
            self.state[target] = False
        elif act == "set_temperature" and action.value is not None:
            self.state[target] = action.value
        elif act == "increase_temp" and action.value is not None:
            self.state[target] = self.state.get(target, 20) + action.value
        elif act == "decrease_temp" and action.value is not None:
            self.state[target] = self.state.get(target, 20) - action.value
        else:
            logger.warning("Unhandled action/value combo: %s", action)
            return

        logger.info("State updated: %s -> %s", target, self.state[target])
        self._render_device(target)

    def apply_actions(self, actions):
        for action in actions:
            self.apply_action(action)