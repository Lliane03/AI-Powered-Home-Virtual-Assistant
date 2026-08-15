"""
home_simulator.py
Tkinter-based GUI dashboard + state machine for the simulated smart home.
Consumes DeviceAction objects (from ai_engine.py) and updates both the
in-memory state and the visual dashboard.

Visual theme: a dark holographic HUD (heads-up display), inspired by
sci-fi "AI operating system" interfaces — cyan glow, radial gauges,
corner-bracket panels, tracked/uppercase typography, and a rotating
reactor-style status core instead of a plain dot indicator.

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

# -- HUD Palette --------------------------------------------------------------
# Near-black chassis with a cyan "reactor glow" accent, an amber accent
# reserved for paused/alert states, and a red accent reserved for an
# unlocked door. Kept deliberately narrow so the whole dashboard reads as
# one coherent instrument panel rather than a scattered set of colors.
COLOR_BG = "#03080B"            # window background (near-black)
COLOR_PANEL = "#060F14"         # card background
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
        self.root.geometry("760x600")
        self.root.minsize(700, 560)

        self._build_ui()
        self.refresh_all()
        self._animate_core()

    # -- UI construction ------------------------------------------------------
    def _build_ui(self):
        title_font = tkfont.Font(family=FONT_FAMILY, size=17, weight="bold")
        subtitle_font = tkfont.Font(family=FONT_FAMILY_UI, size=9)
        self.card_name_font = tkfont.Font(family=FONT_FAMILY, size=10, weight="bold")
        self.card_status_font = tkfont.Font(family=FONT_FAMILY, size=10)

        # -- Header -------------------------------------------------------
        header = tk.Frame(self.root, bg=COLOR_BG)
        header.pack(fill="x", padx=18, pady=(16, 6))

        title_block = tk.Frame(header, bg=COLOR_BG)
        title_block.pack(side="left")
        tk.Label(
            title_block, text=_tracked("Home OS", gap=" "), font=title_font,
            bg=COLOR_BG, fg=COLOR_CYAN,
        ).pack(anchor="w")
        tk.Label(
            title_block, text=_tracked("Voice-Controlled Environment", gap=" "),
            font=subtitle_font, bg=COLOR_BG, fg=COLOR_MUTED,
        ).pack(anchor="w")

        # Reactor-style status core + pause/resume control, top-right
        controls = tk.Frame(header, bg=COLOR_BG)
        controls.pack(side="right")

        self.core_canvas = tk.Canvas(
            controls, width=46, height=46, bg=COLOR_BG, highlightthickness=0
        )
        self.core_canvas.pack(side="left", padx=(0, 14))

        button_block = tk.Frame(controls, bg=COLOR_BG)
        button_block.pack(side="left")
        self.pause_button = tk.Button(
            button_block, text=_tracked("Pause Listening"),
            font=(FONT_FAMILY_UI, 9, "bold"),
            bg=COLOR_BG, fg=COLOR_CYAN, activebackground=COLOR_CYAN_GLOW,
            activeforeground=COLOR_CYAN, relief="flat", bd=0,
            highlightbackground=COLOR_CYAN_DIM, highlightthickness=1,
            padx=14, pady=8, cursor="hand2",
            command=self._handle_pause_toggle,
        )
        self.pause_button.pack()

        # thin separator line under the header
        tk.Frame(self.root, bg=COLOR_PANEL_EDGE, height=1).pack(fill="x", padx=18)

        # -- Device grid ----------------------------------------------------
        grid = tk.Frame(self.root, bg=COLOR_BG)
        grid.pack(fill="both", expand=True, padx=14, pady=10)
        for i in range(3):
            grid.columnconfigure(i, weight=1)
        for i in range(2):
            grid.rowconfigure(i, weight=1)

        for idx, device in enumerate(DEVICE_ORDER):
            row, col = divmod(idx, 3)
            card_canvas = tk.Canvas(
                grid, width=210, height=190, bg=COLOR_BG, highlightthickness=0
            )
            card_canvas.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            self.widgets[device] = {"canvas": card_canvas}

        # -- Command history panel ------------------------------------------
        history_frame = tk.Frame(self.root, bg=COLOR_BG)
        history_frame.pack(fill="both", padx=18, pady=(2, 6))
        tk.Label(
            history_frame, text=_tracked("Command Log"), font=(FONT_FAMILY, 9, "bold"),
            bg=COLOR_BG, fg=COLOR_MUTED, anchor="w",
        ).pack(fill="x")
        tk.Frame(history_frame, bg=COLOR_PANEL_EDGE, height=1).pack(fill="x", pady=(2, 4))
        self.history_list = tk.Listbox(
            history_frame, height=4, bg=COLOR_PANEL, fg=COLOR_TEXT,
            borderwidth=0, highlightthickness=1, highlightbackground=COLOR_PANEL_EDGE,
            font=(FONT_FAMILY, 9), selectbackground=COLOR_CYAN_GLOW,
            selectforeground=COLOR_CYAN,
        )
        self.history_list.pack(fill="x")

        # -- Status bar -------------------------------------------------------
        status_bar = tk.Frame(self.root, bg=COLOR_PANEL)
        status_bar.pack(fill="x", side="bottom")
        tk.Frame(status_bar, bg=COLOR_CYAN_DIM, height=1).pack(fill="x")
        self.status_var = tk.StringVar(value="SYSTEM READY. AWAITING VOICE COMMAND...")
        tk.Label(
            status_bar, textvariable=self.status_var, bg=COLOR_PANEL, fg=COLOR_CYAN,
            font=(FONT_FAMILY, 10), anchor="w", padx=18, pady=10,
        ).pack(fill="x")

    # -- Card chrome (shared panel frame + corner brackets) --------------------
    def _draw_card_frame(self, canvas: tk.Canvas, active: bool, alert: bool = False):
        w = int(canvas["width"])
        h = int(canvas["height"])
        edge = COLOR_RED if alert else (COLOR_CYAN if active else COLOR_PANEL_EDGE)

        canvas.create_rectangle(1, 1, w - 1, h - 1, fill=COLOR_PANEL, outline="")

        # faint scan lines for texture
        for y in range(10, h - 10, 10):
            canvas.create_line(6, y, w - 6, y, fill=COLOR_GRID)

        # panel border
        canvas.create_rectangle(2, 2, w - 2, h - 2, outline=edge, width=1)

        # corner brackets - the classic HUD-panel accent
        bl = 14  # bracket leg length
        pts = [
            (4, 4 + bl, 4, 4, 4 + bl, 4),                     # top-left
            (w - 4 - bl, 4, w - 4, 4, w - 4, 4 + bl),         # top-right
            (4, h - 4 - bl, 4, h - 4, 4 + bl, h - 4),         # bottom-left
            (w - 4 - bl, h - 4, w - 4, h - 4, w - 4, h - 4 - bl),  # bottom-right
        ]
        for x1, y1, x2, y2, x3, y3 in pts:
            canvas.create_line(x1, y1, x2, y2, x3, y3, fill=edge, width=2)

    # -- Icon drawing (all icons are strokes on the HUD-cyan palette) ----------
    def _draw_bulb(self, canvas: tk.Canvas, cx: int, cy: int, is_on: bool):
        r = 20
        stroke = COLOR_CYAN if is_on else COLOR_OFF
        if is_on:
            canvas.create_oval(cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10,
                                fill=COLOR_CYAN_GLOW, outline="")
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=stroke, width=2,
                            fill=COLOR_PANEL if not is_on else "")
        if is_on:
            for ang in range(0, 360, 45):
                rad = math.radians(ang)
                x1, y1 = cx + math.cos(rad) * (r - 6), cy + math.sin(rad) * (r - 6)
                x2, y2 = cx + math.cos(rad) * (r + 5), cy + math.sin(rad) * (r + 5)
                canvas.create_line(x1, y1, x2, y2, fill=COLOR_CYAN, width=1)
        canvas.create_rectangle(cx - 7, cy + r - 2, cx + 7, cy + r + 8,
                                 outline=stroke, width=1)
        for i in range(2):
            y = cy + r + 10 + i * 4
            canvas.create_line(cx - 7, y, cx + 7, y, fill=stroke, width=1)

    def _draw_lock(self, canvas: tk.Canvas, cx: int, cy: int, is_locked: bool):
        top = cy - 22
        stroke = COLOR_CYAN if is_locked else COLOR_RED
        glow = COLOR_CYAN_GLOW if is_locked else "#3A1414"
        canvas.create_oval(cx - 26, top - 6, cx + 26, top + 40, fill=glow, outline="")
        if is_locked:
            canvas.create_arc(cx - 14, top - 8, cx + 14, top + 20, start=0, extent=180,
                               style="arc", outline=stroke, width=3)
        else:
            canvas.create_arc(cx - 14, top - 12, cx + 14, top + 14, start=25, extent=180,
                               style="arc", outline=stroke, width=3)
        canvas.create_rectangle(cx - 17, top + 14, cx + 17, top + 40, outline=stroke,
                                 width=2, fill=COLOR_PANEL)
        canvas.create_oval(cx - 3, top + 22, cx + 3, top + 28, fill=stroke, outline="")
        canvas.create_line(cx, top + 25, cx, top + 32, fill=stroke, width=2)

    def _draw_thermostat(self, canvas: tk.Canvas, cx: int, cy: int, temp: float):
        r = 30
        canvas.create_oval(cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8,
                            fill=COLOR_CYAN_GLOW, outline="")
        for ang in range(225, -46, -27):  # tick marks across the 270deg sweep
            rad = math.radians(ang)
            x1, y1 = cx + math.cos(rad) * (r - 4), cy - math.sin(rad) * (r - 4)
            x2, y2 = cx + math.cos(rad) * (r + 2), cy - math.sin(rad) * (r + 2)
            canvas.create_line(x1, y1, x2, y2, fill=COLOR_CYAN_DIM, width=1)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=COLOR_PANEL_EDGE, width=2)
        clamped = max(10, min(30, temp))
        pct = (clamped - 10) / 20.0
        extent = 270 * pct
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=225, extent=-extent,
                           style="arc", outline=COLOR_CYAN, width=4)
        canvas.create_text(cx, cy, text=f"{temp:.0f}°", fill=COLOR_TEXT,
                            font=(FONT_FAMILY, 14, "bold"))
        canvas.create_text(cx, cy + 16, text="C", fill=COLOR_MUTED, font=(FONT_FAMILY, 7))

    def _draw_tv(self, canvas: tk.Canvas, cx: int, cy: int, is_on: bool):
        stroke = COLOR_CYAN if is_on else COLOR_OFF
        glow = COLOR_CYAN_GLOW if is_on else COLOR_PANEL
        canvas.create_rectangle(cx - 30, cy - 18, cx + 30, cy + 18, fill=glow,
                                 outline=stroke, width=2)
        canvas.create_rectangle(cx - 8, cy + 20, cx + 8, cy + 26, outline=stroke, width=1)
        canvas.create_line(cx - 18, cy + 28, cx + 18, cy + 28, fill=stroke, width=2)
        if is_on:
            for i, y in enumerate((cy - 8, cy, cy + 8)):
                w = 40 - i * 12
                canvas.create_line(cx - w / 2, y, cx + w / 2, y, fill=COLOR_CYAN, width=1)
        else:
            canvas.create_line(cx - 12, cy - 8, cx + 12, cy + 8, fill=stroke, width=1)
            canvas.create_line(cx - 12, cy + 8, cx + 12, cy - 8, fill=stroke, width=1)

    # -- Rendering --------------------------------------------------------------
    def refresh_all(self):
        for device in self.widgets:
            self._render_device(device)

    def _render_device(self, device: str):
        canvas = self.widgets[device]["canvas"]
        canvas.delete("all")
        value = self.state[device]
        cx, cy = 105, 78

        if device in LIGHT_DEVICES:
            is_on = bool(value)
            self._draw_card_frame(canvas, active=is_on)
            self._draw_bulb(canvas, cx, cy, is_on)
            status_text, status_color = ("ONLINE", COLOR_CYAN) if is_on else ("STANDBY", COLOR_MUTED)
        elif device == "thermostat":
            self._draw_card_frame(canvas, active=True)
            self._draw_thermostat(canvas, cx, cy, float(value))
            status_text, status_color = (f"TARGET {value:.0f}°C", COLOR_CYAN)
        elif device == "front_door_lock":
            locked = bool(value)
            self._draw_card_frame(canvas, active=locked, alert=not locked)
            self._draw_lock(canvas, cx, cy, locked)
            status_text, status_color = ("SECURED", COLOR_CYAN) if locked else ("UNLOCKED", COLOR_RED)
        elif device == "tv":
            is_on = bool(value)
            self._draw_card_frame(canvas, active=is_on)
            self._draw_tv(canvas, cx, cy, is_on)
            status_text, status_color = ("ONLINE", COLOR_CYAN) if is_on else ("STANDBY", COLOR_MUTED)
        else:
            return

        canvas.create_text(105, 148, text=_tracked(DEVICE_LABELS[device]),
                            fill=COLOR_TEXT, font=self.card_name_font)
        canvas.create_text(105, 168, text=_tracked(status_text),
                            fill=status_color, font=self.card_status_font)

    def set_status(self, text: str):
        self.status_var.set(text.upper())

    def add_history_entry(self, heard_text: str, response_text: str):
        entry = f'» "{heard_text}"  →  {response_text}'
        self.history_list.insert(0, entry)
        if self.history_list.size() > 5:
            self.history_list.delete(5, tk.END)

    # -- Reactor-style listening indicator ---------------------------------------
    def set_listening_active(self, active: bool):
        self._listening_active = active

    def _animate_core(self):
        c = self.core_canvas
        c.delete("all")
        cx, cy, r_outer, r_inner = 23, 23, 20, 9

        if self.is_paused:
            color, glow = COLOR_AMBER, "#3A2A0E"
            c.create_oval(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                          outline=color, width=2)
            c.create_oval(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                          fill=glow, outline=color, width=1)
        elif self._listening_active:
            color, glow = COLOR_CYAN, COLOR_CYAN_GLOW
            self._pulse_phase = (self._pulse_phase + 1) % 40
            brightness = 0.55 + 0.45 * abs(math.sin(self._pulse_phase / 40 * math.pi))
            core_fill = f"#{int(0x3C*brightness):02x}{int(0xE8*brightness):02x}{int(0xFF*brightness):02x}"
            self._core_angle = (self._core_angle + 9) % 360
            for i in range(4):
                start = self._core_angle + i * 90
                c.create_arc(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                             start=start, extent=55, style="arc", outline=color, width=2)
            c.create_oval(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                          fill=core_fill, outline="")
        else:
            color = COLOR_MUTED
            c.create_oval(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                          outline=COLOR_PANEL_EDGE, width=2)
            c.create_oval(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                          fill=COLOR_PANEL, outline=color, width=1)

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
