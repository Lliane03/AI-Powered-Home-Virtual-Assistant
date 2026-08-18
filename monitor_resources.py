"""
monitor_resources.py — capture real peak CPU% and RAM during a voice command.

Usage:
    1. Start your assistant normally:  python src/main.py
    2. In a second terminal (same venv), find its PID:
         Windows:  tasklist | findstr python
       (or add psutil.Process() self-lookup — see NOTE below)
    3. Run this script with that PID, then speak your command:
         python monitor_resources.py <PID> --label "turn on the tv and kitchen"
    4. Speak the command, wait for it to complete, then press Ctrl+C to stop
       sampling. Peak CPU/RAM and elapsed time are printed and appended to
       resource_log.csv — copy those numbers into the report table.

NOTE: if it's easier, you can instead import `track()` directly inside
main.py around the point where a command starts/finishes processing, so
timing is exact rather than eyeballed from a second terminal.
"""
import argparse
import csv
import os
import time
import psutil


def track(pid: int, label: str, sample_interval: float = 0.2):
    proc = psutil.Process(pid)
    peak_cpu = 0.0
    peak_rss_mb = 0.0
    start = time.time()
    print(f"Sampling PID {pid} ({label!r}) — press Ctrl+C when the command finishes.")
    try:
        while True:
            cpu = proc.cpu_percent(interval=sample_interval)  # % of one core
            rss_mb = proc.memory_info().rss / (1024 * 1024)
            peak_cpu = max(peak_cpu, cpu)
            peak_rss_mb = max(peak_rss_mb, rss_mb)
            print(f"\r  cpu={cpu:5.1f}%  rss={rss_mb:6.1f} MB", end="", flush=True)
    except KeyboardInterrupt:
        pass
    except psutil.NoSuchProcess:
        print("\nProcess ended.")

    duration = time.time() - start
    print(f"\n\nPeak CPU: {peak_cpu:.1f}%   Peak RAM: {peak_rss_mb:.1f} MB   Duration: {duration:.1f}s")

    log_path = os.path.join(os.path.dirname(__file__), "resource_log.csv")
    write_header = not os.path.exists(log_path)
    with open(log_path, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["label", "peak_cpu_percent", "peak_ram_mb", "duration_s"])
        w.writerow([label, round(peak_cpu, 1), round(peak_rss_mb, 1), round(duration, 1)])
    print(f"Logged to {log_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int, help="PID of the running assistant process")
    ap.add_argument("--label", default="command", help="Name of the voice command being tested")
    ap.add_argument("--interval", type=float, default=0.2, help="Sampling interval in seconds")
    args = ap.parse_args()
    track(args.pid, args.label, args.interval)
