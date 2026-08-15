"""
main.py
Entry point. Launches the GUI and runs the voice interaction loop on a
background thread so Tkinter's mainloop stays responsive.

Wires up:
- A threading.Event used to pause/resume the mic from the GUI's button.
- Listening-indicator updates so the dashboard shows live pipeline state.
- Command history entries pushed to the GUI after each successful command.
"""

import logging
import os
import threading
import time
import tkinter as tk
from datetime import datetime

from ai_engine import parse_command
from home_simulator import HomeSimulator
from voice_pipeline import VoicePipeline

# ---------------------------------------------------------------------------
# Logging setup - writes to logs/assistant_execution.log per the deliverable spec
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "assistant_execution.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),  # also print to console
    ],
)
logger = logging.getLogger("assistant")


def voice_loop(simulator: HomeSimulator, pipeline: VoicePipeline, pause_event: threading.Event):
    """
    Runs on a background thread: listen -> parse -> apply to GUI -> speak.
    Uses root.after(...) to safely push GUI updates back onto the main thread.
    pause_event.is_set() == True means "paused" - the loop idles without
    touching the microphone until it's cleared again.
    """
    simulator.root.after(0, simulator.set_status, "Ready. Say a command...")

    while True:
        if pause_event.is_set():
            simulator.root.after(0, simulator.set_listening_active, False)
            time.sleep(0.2)
            continue

        try:
            simulator.root.after(0, simulator.set_listening_active, True)
            start = time.time()
            transcribed = pipeline.listen()
            simulator.root.after(0, simulator.set_status, f'Heard: "{transcribed}"')

            result = parse_command(transcribed)
            elapsed = time.time() - start
            logger.info("End-to-end latency: %.2fs", elapsed)

            # Push state + GUI updates onto the main thread
            simulator.root.after(0, simulator.apply_actions, result.actions)
            simulator.root.after(0, simulator.set_status, result.response_text)
            simulator.root.after(0, simulator.add_history_entry, transcribed, result.response_text)

            pipeline.speak(result.response_text)

        except Exception as exc:
            # Broad catch is intentional here: STT timeouts, unrecognized speech,
            # and malformed model output should never crash the assistant loop.
            logger.error("Voice loop error: %s", exc)
            simulator.root.after(0, simulator.set_status, "Sorry, I didn't catch that. Try again.")
            continue
        finally:
            simulator.root.after(0, simulator.set_listening_active, False)


def main():
    logger.info("=== Assistant session started: %s ===", datetime.now().isoformat())

    root = tk.Tk()
    pause_event = threading.Event()

    def handle_pause_toggle(is_paused: bool):
        if is_paused:
            pause_event.set()
            logger.info("Voice loop paused by user.")
        else:
            pause_event.clear()
            logger.info("Voice loop resumed by user.")

    simulator = HomeSimulator(root, on_toggle_pause=handle_pause_toggle)

    pipeline = VoicePipeline()

    worker = threading.Thread(target=voice_loop, args=(simulator, pipeline, pause_event), daemon=True)
    worker.start()

    root.mainloop()


if __name__ == "__main__":
    main()