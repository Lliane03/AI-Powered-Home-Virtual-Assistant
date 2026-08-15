"""
main.py
Entry point. Launches the GUI and runs the voice interaction loop on a
background thread so Tkinter's mainloop stays responsive.
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


def voice_loop(simulator: HomeSimulator, pipeline: VoicePipeline):
    """
    Runs on a background thread: listen -> parse -> apply to GUI -> speak.
    Uses root.after(...) to safely push GUI updates back onto the main thread.
    """
    simulator.root.after(0, simulator.set_status, "Ready. Say a command...")

    while True:
        try:
            start = time.time()
            transcribed = pipeline.listen()
            simulator.root.after(0, simulator.set_status, f'Heard: "{transcribed}"')

            result = parse_command(transcribed)
            elapsed = time.time() - start
            logger.info("End-to-end latency: %.2fs", elapsed)

            # Push state + GUI updates onto the main thread
            simulator.root.after(0, simulator.apply_actions, result.actions)
            simulator.root.after(0, simulator.set_status, result.response_text)

            pipeline.speak(result.response_text)

        except Exception as exc:
            # Broad catch is intentional here: STT timeouts, unrecognized speech,
            # and malformed model output should never crash the assistant loop.
            logger.error("Voice loop error: %s", exc)
            simulator.root.after(0, simulator.set_status, "Sorry, I didn't catch that. Try again.")
            continue


def main():
    logger.info("=== Assistant session started: %s ===", datetime.now().isoformat())

    root = tk.Tk()
    simulator = HomeSimulator(root)

    pipeline = VoicePipeline()

    worker = threading.Thread(target=voice_loop, args=(simulator, pipeline), daemon=True)
    worker.start()

    root.mainloop()


if __name__ == "__main__":
    main()