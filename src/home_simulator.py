"""
home_simulator.py
Tkinter-based GUI dashboard + state machine for the simulated smart home.
Consumes DeviceAction objects (from ai_engine.py) and updates both the
in-memory state and the visual dashboard.

Enhancements over the base version:
- Canvas-drawn device icons (bulb, lock, thermostat dial, TV) instead of
  flat color cards.
- Pulsing "listening" indicator that reflects the voice pipeline's state.
- Pause/Resume button that toggles a threading.Event checked by main.py's
  voice loop, so the mic can be paused without closing the app.
- Small command history panel showing the last few heard commands.
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
    "living_room_light": "Living Room Light",
    "kitchen_light": "Kitchen Light",
    "bedroom_light": "Bedroom Light",
    "thermostat": "Thermostat",
    "front_door_lock": "Front Door Lock",
    "tv": "TV / Entertainment",
}

DEVICE_ORDER = list(DEVICE_LABELS.keys())

# -- Palette -----------------------------------------------------------------
COLOR_BG = "#15181C"
COLOR_CARD = "#20242A"
COLOR_CARD_BORDER = "#2E333A"
COLOR_TEXT = "#EAEAEA"
COLOR_MUTED = "#8A8F98"
COLOR_ON = "#FFD54A"
COLOR_ON_GLOW = "#FFF3C4"
COLOR_OFF_ICON = "#4A4F58"
COLOR_LOCKED = "#4CAF50"
COLOR_UNLOCKED = "#E53935"
COLOR_ACCENT = "#5DA9FF"
COLOR_LISTEN_ACTIVE = "#5DE58A"
COLOR_LISTEN_PAUSED = "#E5A25D"


class HomeSimulator:
    """Owns the device state and the Tkinter dashboard rendering it."""

    def __init__(self, root: tk.Tk, on_toggle_pause=None):
        self.root = root
        self.state = dict(DEFAULT_STATE)
        self.widgets = {}  # device_key -> dict of canvas/label refs
        self.on_toggle_pause = on_toggle_pause  # callback(bool is_paused) wired by main.py
        self.is_paused = False
        self._pulse_phase = 0
        self._listening_active = False

        self.root.title("Simulated Smart Home Dashboard")
        self.root.configure(bg=COLOR_BG)
        self.root.geometry("700x520")

        self._build_ui()
        self.refresh_all()
        self._animate_listening_indicator()

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        title_font = tkfont.Font(family="Segoe UI", size=17, weight="bold")
        card_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        header = tk.Frame(self.root, bg=COLOR_BG)
        header.pack(fill="x", padx=16, pady=(14, 4))

        tk.Label(
            header, text="Home Assistant Dashboard", font=title_font,
            bg=COLOR_BG, fg=COLOR_TEXT,
        ).pack(side="left")

        # Listening indicator + pause/resume button, top-right
        controls = tk.Frame(header, bg=COLOR_BG)
        controls.pack(side="right")

        self.indicator_canvas = tk.Canvas(
            controls, width=18, height=18, bg=COLOR_BG, highlightthickness=0
        )
        self.indicator_canvas.pack(side="left", padx=(0, 8))
        self._indicator_dot = self.indicator_canvas.create_oval(
            3, 3, 15, 15, fill=COLOR_LISTEN_ACTIVE, outline=""
        )

        self.pause_button = tk.Button(
            controls, text="Pause Listening", font=("Segoe UI", 10, "bold"),
            bg=COLOR_ACCENT, fg="#0C1116", activebackground="#4C8FE0",
            relief="flat", padx=12, pady=6, cursor="hand2",
            command=self._handle_pause_toggle,
        )
        self.pause_button.pack(side="left")

        # Device grid
        grid = tk.Frame(self.root, bg=COLOR_BG)
        grid.pack(fill="both", expand=True, padx=16, pady=8)
        for i in range(3):
            grid.columnconfigure(i, weight=1)

        for idx, device in enumerate(DEVICE_ORDER):
            row, col = divmod(idx, 3)
            card = tk.Frame(
                grid, bg=COLOR_CARD, padx=10, pady=12,
                highlightbackground=COLOR_CARD_BORDER, highlightthickness=1,
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

            canvas = tk.Canvas(card, width=100, height=90, bg=COLOR_CARD, highlightthickness=0)
            canvas.pack()

            name_label = tk.Label(
                card, text=DEVICE_LABELS[device], font=card_font,
                bg=COLOR_CARD, fg=COLOR_TEXT,
            )
            name_label.pack(pady=(6, 0))

            status_label = tk.Label(
                card, text="", font=("Segoe UI", 11), bg=COLOR_CARD, fg=COLOR_MUTED,
            )
            status_label.pack()

            self.widgets[device] = {"canvas": canvas, "status_label": status_label}

        # Command history panel
        history_frame = tk.Frame(self.root, bg=COLOR_BG)
        history_frame.pack(fill="both", padx=16, pady=(0, 4))
        tk.Label(
            history_frame, text="Recent commands", font=("Segoe UI", 10, "bold"),
            bg=COLOR_BG, fg=COLOR_MUTED, anchor="w",
        ).pack(fill="x")
        self.history_list = tk.Listbox(
            history_frame, height=4, bg=COLOR_CARD, fg=COLOR_TEXT,
            borderwidth=0, highlightthickness=0, font=("Segoe UI", 10),
            selectbackground=COLOR_CARD,
        )
        self.history_list.pack(fill="x")

        # Status bar
        self.status_var = tk.StringVar(value="Ready. Say a command...")
        tk.Label(
            self.root, textvariable=self.status_var, bg=COLOR_BG, fg=COLOR_LISTEN_ACTIVE,
            font=("Segoe UI", 10), anchor="w", padx=16, pady=10,
        ).pack(fill="x", side="bottom")

    # -- Icon drawing ---------------------------------------------------------
    def _draw_bulb(self, canvas: tk.Canvas, is_on: bool):
        canvas.delete("all")
        cx, cy, r = 50, 34, 22
        glow_color = COLOR_ON_GLOW if is_on else COLOR_CARD
        bulb_color = COLOR_ON if is_on else COLOR_OFF_ICON
        if is_on:
            canvas.create_oval(cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6, fill=glow_color, outline="")
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=bulb_color, outline="")
        # base
        canvas.create_rectangle(cx - 8, cy + r - 4, cx + 8, cy + r + 10, fill="#B0AFA8", outline="")
        for i in range(3):
            y = cy + r + 12 + i * 4
            canvas.create_line(cx - 8, y, cx + 8, y, fill="#8A8880", width=1.5)

    def _draw_lock(self, canvas: tk.Canvas, is_locked: bool):
        canvas.delete("all")
        color = COLOR_LOCKED if is_locked else COLOR_UNLOCKED
        cx, top = 50, 30
        # shackle: closed = full arc over body, unlocked = shifted open arc
        if is_locked:
            canvas.create_arc(cx - 16, top - 10, cx + 16, top + 22, start=0, extent=180,
                               style="arc", outline=color, width=4)
        else:
            canvas.create_arc(cx - 16, top - 16, cx + 16, top + 16, start=20, extent=180,
                               style="arc", outline=color, width=4)
        # body
        canvas.create_rectangle(cx - 20, top + 16, cx + 20, top + 52, fill=color, outline="")
        canvas.create_oval(cx - 4, top + 28, cx + 4, top + 36, fill="#15181C", outline="")

    def _draw_thermostat(self, canvas: tk.Canvas, temp: float):
        canvas.delete("all")
        cx, cy, r = 50, 42, 30
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#4A4F58", width=3)
        # map 10-30C -> 0-270 degree sweep, starting at -225 (bottom-left) going clockwise
        clamped = max(10, min(30, temp))
        pct = (clamped - 10) / 20.0
        extent = 270 * pct
        canvas.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=225, extent=-extent, style="arc", outline=COLOR_ACCENT, width=5,
        )
        canvas.create_text(cx, cy, text=f"{temp:.0f}°", fill=COLOR_TEXT, font=("Segoe UI", 13, "bold"))

    def _draw_tv(self, canvas: tk.Canvas, is_on: bool):
        canvas.delete("all")
        color = COLOR_ON if is_on else COLOR_OFF_ICON
        glow = COLOR_ON_GLOW if is_on else COLOR_CARD
        canvas.create_rectangle(20, 16, 80, 52, fill=glow, outline=color, width=2)
        canvas.create_rectangle(40, 54, 60, 60, fill="#8A8880", outline="")
        canvas.create_rectangle(28, 60, 72, 64, fill="#B0AFA8", outline="")
        if is_on:
            canvas.create_line(28, 30, 72, 30, fill=color, width=2)
            canvas.create_line(28, 38, 60, 38, fill=color, width=2)

    # -- Rendering ------------------------------------------------------------
    def refresh_all(self):
        for device in self.widgets:
            self._render_device(device)

    def _render_device(self, device: str):
        widgets = self.widgets[device]
        canvas = widgets["canvas"]
        value = self.state[device]

        if device in LIGHT_DEVICES:
            is_on = bool(value)
            self._draw_bulb(canvas, is_on)
            widgets["status_label"].configure(text="ON" if is_on else "OFF",
                                               fg=COLOR_ON if is_on else COLOR_MUTED)
        elif device == "thermostat":
            self._draw_thermostat(canvas, float(value))
            widgets["status_label"].configure(text=f"{value:.0f}°C target", fg=COLOR_MUTED)
        elif device == "front_door_lock":
            locked = bool(value)
            self._draw_lock(canvas, locked)
            widgets["status_label"].configure(text="LOCKED" if locked else "UNLOCKED",
                                               fg=COLOR_LOCKED if locked else COLOR_UNLOCKED)
        elif device == "tv":
            is_on = bool(value)
            self._draw_tv(canvas, is_on)
            widgets["status_label"].configure(text="ON" if is_on else "OFF",
                                               fg=COLOR_ON if is_on else COLOR_MUTED)

    def set_status(self, text: str):
        self.status_var.set(text)

    def add_history_entry(self, heard_text: str, response_text: str):
        entry = f'"{heard_text}"  ->  {response_text}'
        self.history_list.insert(0, entry)
        if self.history_list.size() > 5:
            self.history_list.delete(5, tk.END)

    # -- Listening indicator ---------------------------------------------------
    def set_listening_active(self, active: bool):
        self._listening_active = active

    def _animate_listening_indicator(self):
        if self.is_paused:
            color = COLOR_LISTEN_PAUSED
            self.indicator_canvas.itemconfig(self._indicator_dot, fill=color)
        elif self._listening_active:
            # simple pulse between two brightness levels
            self._pulse_phase = (self._pulse_phase + 1) % 20
            brightness = 0.6 + 0.4 * abs(math.sin(self._pulse_phase / 20 * math.pi))
            color = f"#{int(0x5D*brightness):02x}{int(0xE5*brightness):02x}{int(0x8A*brightness):02x}"
            self.indicator_canvas.itemconfig(self._indicator_dot, fill=color)
        else:
            self.indicator_canvas.itemconfig(self._indicator_dot, fill=COLOR_MUTED)
        self.root.after(80, self._animate_listening_indicator)

    # -- Pause/Resume -----------------------------------------------------------
    def _handle_pause_toggle(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.pause_button.configure(text="Resume Listening", bg=COLOR_LISTEN_PAUSED)
            self.set_status("Paused. Click Resume to continue.")
        else:
            self.pause_button.configure(text="Pause Listening", bg=COLOR_ACCENT)
            self.set_status("Ready. Say a command...")
        if self.on_toggle_pause:
            self.on_toggle_pause(self.is_paused)

    # -- State machine --------------------------------------------------------
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