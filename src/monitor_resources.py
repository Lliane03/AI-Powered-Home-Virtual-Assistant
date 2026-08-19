"""
monitor_resources.py — capture real peak CPU% and RAM during a voice command.

v2: self-tracking. The previous version required grabbing a PID from a
second terminal (`tasklist | findstr python`) and sampling it externally.
On Windows, `venv\\Scripts\\python.exe` can behave as a thin launcher, so
that approach risked sampling an idle stub process instead of the real
interpreter running main.py — which is the most likely explanation for the
flat 0.0% CPU / 4.1 MB RAM readings in the original resource_log.csv.

This version fixes that by sampling the CURRENT process from inside it,
via `psutil.Process()` with no arguments. There's no PID to find and no
second terminal needed. Call ResourceTracker.start() right before a command
begins processing and .stop(label) right after it finishes, and it will
background-sample CPU/RAM the whole time and append a correctly-labeled row
to resource_log.csv automatically. See main.py's voice_loop for the
integration point.

Standalone CLI usage (only needed if you want to test this file directly,
not the full app):
    python monitor_resources.py <PID> --label "some command" --duration 10
"""
import argparse
import csv
import os
import threading
import time
import psutil


class ResourceTracker:
    """
    Samples the CURRENT process's CPU% and RSS memory on a background
    thread between .start() and .stop(label). Self-referential -
    psutil.Process() with no args always means "this process", so there's
    no PID lookup involved and no risk of sampling the wrong one.
    """

    def __init__(self, sample_interval: float = 0.2, log_path: str = None):
        self.sample_interval = sample_interval
        self.log_path = log_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "resource_log.csv"
        )
        self._proc = psutil.Process()  # self-lookup, no PID needed
        self._thread = None
        self._stop_flag = threading.Event()
        self._peak_cpu = 0.0
        self._peak_rss_mb = 0.0
        self._start_time = None

    def _sample_loop(self):
        # Prime cpu_percent() - the first call after creating the Process
        # object (or after a prior call) returns 0.0/garbage; it needs one
        # throwaway call to establish a baseline before readings mean anything.
        self._proc.cpu_percent(interval=None)
        while not self._stop_flag.is_set():
            time.sleep(self.sample_interval)
            cpu = self._proc.cpu_percent(interval=None)
            rss_mb = self._proc.memory_info().rss / (1024 * 1024)
            self._peak_cpu = max(self._peak_cpu, cpu)
            self._peak_rss_mb = max(self._peak_rss_mb, rss_mb)

    def start(self):
        self._peak_cpu = 0.0
        self._peak_rss_mb = 0.0
        self._stop_flag.clear()
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def cancel(self):
        """Stop sampling without writing a row - use when a command failed
        (STT timeout, unrecognized speech, parse error) so resource_log.csv
        only ever contains real, completed commands."""
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=self.sample_interval * 2)

    def stop(self, label: str) -> dict:
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=self.sample_interval * 2)
        duration = time.time() - self._start_time

        row = {
            "label": label,
            "peak_cpu_percent": round(self._peak_cpu, 1),
            "peak_ram_mb": round(self._peak_rss_mb, 1),
            "duration_s": round(duration, 1),
        }
        self._append_row(row)
        return row

    def _append_row(self, row: dict):
        write_header = not os.path.exists(self.log_path)
        with open(self.log_path, "a", newline="") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["label", "peak_cpu_percent", "peak_ram_mb", "duration_s"])
            w.writerow([row["label"], row["peak_cpu_percent"], row["peak_ram_mb"], row["duration_s"]])


# ---------------------------------------------------------------------------
# Standalone CLI (legacy path) - kept only for ad-hoc testing of THIS file's
# own process. For real end-to-end command measurements, use ResourceTracker
# from inside main.py's voice_loop instead (see integration there), since
# that's the only way to guarantee you're sampling the actual worker process.
# ---------------------------------------------------------------------------
def track_external_pid(pid: int, label: str, duration: float, sample_interval: float = 0.2):
    proc = psutil.Process(pid)
    proc.cpu_percent(interval=None)  # prime
    peak_cpu = 0.0
    peak_rss_mb = 0.0
    start = time.time()
    print(f"Sampling PID {pid} ({label!r}) for {duration:.1f}s...")
    while time.time() - start < duration:
        time.sleep(sample_interval)
        cpu = proc.cpu_percent(interval=None)
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        peak_cpu = max(peak_cpu, cpu)
        peak_rss_mb = max(peak_rss_mb, rss_mb)
        print(f"\r  cpu={cpu:5.1f}%  rss={rss_mb:6.1f} MB", end="", flush=True)

    elapsed = time.time() - start
    print(f"\n\nPeak CPU: {peak_cpu:.1f}%   Peak RAM: {peak_rss_mb:.1f} MB   Duration: {elapsed:.1f}s")

    tracker = ResourceTracker()
    tracker._peak_cpu = peak_cpu
    tracker._peak_rss_mb = peak_rss_mb
    tracker._start_time = start
    tracker.stop(label)
    print(f"Logged to {tracker.log_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Legacy external-PID sampling. Prefer ResourceTracker inside main.py instead."
    )
    ap.add_argument("pid", type=int, help="PID to sample (NOTE: prefer self-tracking via main.py)")
    ap.add_argument("--label", default="command", help="Name of the voice command being tested")
    ap.add_argument("--duration", type=float, default=10.0, help="How long to sample, in seconds")
    ap.add_argument("--interval", type=float, default=0.2, help="Sampling interval in seconds")
    args = ap.parse_args()
    track_external_pid(args.pid, args.label, args.duration, args.interval)