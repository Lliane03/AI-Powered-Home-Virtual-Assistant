"""
home_simulator.py
Tkinter-based GUI dashboard + state machine for the simulated smart home.
Consumes DeviceAction objects (from ai_engine.py) and updates both the
in-memory state and the visual dashboard.
"""

import logging
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

COLOR_ON = "#FFD54A"
COLOR_OFF = "#3A3A3A"
COLOR_BG = "#1E1E1E"
COLOR_CARD = "#2A2A2A"
COLOR_TEXT = "#EAEAEA"
COLOR_LOCKED = "#4CAF50"
COLOR_UNLOCKED = "#E53935"


class HomeSimulator:
    """Owns the device state and the Tkinter dashboard rendering it."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.state = dict(DEFAULT_STATE)
        self.widgets = {}  # device_key -> {"canvas"/"label" widgets to update}

        self.root.title("Simulated Smart Home Dashboard")
        self.root.configure(bg=COLOR_BG)
        self.root.geometry("640x420")

        self._build_ui()
        self.refresh_all()

    # -- UI construction ----------------------------------------------------
    def _build_ui(self):
        title_font = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        card_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        value_font = tkfont.Font(family="Segoe UI", size=20, weight="bold")

        header = tk.Label(
            self.root, text="Home Assistant Dashboard", font=title_font,
            bg=COLOR_BG, fg=COLOR_TEXT, pady=12,
        )
        header.pack(fill="x")

        grid = tk.Frame(self.root, bg=COLOR_BG)
        grid.pack(fill="both", expand=True, padx=16, pady=8)

        for i in range(3):
            grid.columnconfigure(i, weight=1)

        devices = list(DEVICE_LABELS.keys())
        for idx, device in enumerate(devices):
            row, col = divmod(idx, 3)
            card = tk.Frame(grid, bg=COLOR_CARD, padx=10, pady=14)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

            name_label = tk.Label(
                card, text=DEVICE_LABELS[device], font=card_font,
                bg=COLOR_CARD, fg=COLOR_TEXT,
            )
            name_label.pack()

            value_label = tk.Label(
                card, text="", font=value_font, bg=COLOR_CARD, fg=COLOR_TEXT,
            )
            value_label.pack(pady=(10, 0))

            self.widgets[device] = {"card": card, "value_label": value_label}

        # Status / last-response bar at the bottom
        self.status_var = tk.StringVar(value="Ready. Say a command...")
        status_bar = tk.Label(
            self.root, textvariable=self.status_var, bg=COLOR_BG, fg="#9BE28C",
            font=("Segoe UI", 10), anchor="w", padx=16, pady=10,
        )
        status_bar.pack(fill="x", side="bottom")

    # -- Rendering ------------------------------------------------------------
    def refresh_all(self):
        for device in self.widgets:
            self._render_device(device)

    def _render_device(self, device: str):
        widgets = self.widgets[device]
        value = self.state[device]

        if device in LIGHT_DEVICES:
            is_on = bool(value)
            widgets["card"].configure(bg=COLOR_ON if is_on else COLOR_CARD)
            widgets["value_label"].configure(
                text="ON" if is_on else "OFF",
                bg=COLOR_ON if is_on else COLOR_CARD,
                fg="#1E1E1E" if is_on else COLOR_TEXT,
            )
        elif device == "thermostat":
            widgets["value_label"].configure(text=f"{value:.0f}°C", bg=COLOR_CARD, fg=COLOR_TEXT)
        elif device == "front_door_lock":
            locked = bool(value)
            widgets["card"].configure(bg=COLOR_LOCKED if locked else COLOR_UNLOCKED)
            widgets["value_label"].configure(
                text="LOCKED" if locked else "UNLOCKED",
                bg=COLOR_LOCKED if locked else COLOR_UNLOCKED,
                fg="white",
            )
        elif device == "tv":
            is_on = bool(value)
            widgets["card"].configure(bg=COLOR_ON if is_on else COLOR_CARD)
            widgets["value_label"].configure(
                text="ON" if is_on else "OFF",
                bg=COLOR_ON if is_on else COLOR_CARD,
                fg="#1E1E1E" if is_on else COLOR_TEXT,
            )

    def set_status(self, text: str):
        self.status_var.set(text)

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