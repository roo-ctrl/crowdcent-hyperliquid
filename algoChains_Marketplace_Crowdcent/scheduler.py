"""The bot loop: run pipeline.py every RUN_EVERY_DAYS days at RUN_AT_UTC.

The date of the last *successful* run lives in STATE_DIR/last_run.txt, so a
container restart never double-runs and never forgets where it was.

Environment:
    RUN_EVERY_DAYS   cadence in days               (default 10)
    RUN_AT_UTC       HH:MM earliest time of day    (default 15:00 — CrowdCent window is 14:00-18:00 UTC)
    RUN_ON_START     "1" = run right away if never run before (default 0)
    RUN_ONCE         "1" = run one pipeline now and exit (testing)
    CHECK_SECONDS    wake-up interval               (default 300)
Everything else (SUBMIT, SEND_SIGNALS, ...) is read by pipeline.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RUN_EVERY_DAYS = int(os.getenv("RUN_EVERY_DAYS", "10"))
RUN_AT_UTC = os.getenv("RUN_AT_UTC", "15:00").strip()
RUN_ON_START = os.getenv("RUN_ON_START", "0").strip() == "1"
RUN_ONCE = os.getenv("RUN_ONCE", "0").strip() == "1"
CHECK_SECONDS = int(os.getenv("CHECK_SECONDS", "300"))
STATE_FILE = Path(os.getenv("STATE_DIR", "state")) / "last_run.txt"
PIPELINE = Path(__file__).with_name("pipeline.py")


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] scheduler: {msg}", flush=True)


def last_run() -> date | None:
    try:
        return date.fromisoformat(STATE_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def mark_run(day: date) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(day.isoformat())


def run_pipeline(extra: list[str] | None = None) -> bool:
    log("starting pipeline.py")
    rc = subprocess.call([sys.executable, "-u", str(PIPELINE), *(extra or [])])
    log(f"pipeline.py exited with {rc}")
    return rc == 0


def due(now: datetime, last: date | None) -> bool:
    hh, mm = (int(x) for x in RUN_AT_UTC.split(":"))
    past_time_of_day = (now.hour, now.minute) >= (hh, mm)
    if last is None:
        return RUN_ON_START or past_time_of_day
    return (now.date() - last).days >= RUN_EVERY_DAYS and past_time_of_day


def main() -> int:
    if RUN_ONCE:
        return 0 if run_pipeline(sys.argv[1:]) else 1

    log(f"every {RUN_EVERY_DAYS} days at {RUN_AT_UTC} UTC · last run: {last_run()}")
    while True:
        now = datetime.now(timezone.utc)
        if due(now, last_run()):
            if run_pipeline():
                mark_run(now.date())
                log(f"next run on or after {now.date()} + {RUN_EVERY_DAYS} days at {RUN_AT_UTC} UTC")
            else:
                log("run failed — retrying at the next check")
        time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
