"""
Scheduler - runs bot at times from .env
SCHEDULE_TIMES=09:00,13:00,17:00,20:00
SCHEDULE_DAYS=mon,tue,wed,thu,fri,sat,sun

Uses a simple 30-second polling loop instead of APScheduler.
"""

import os
import threading
import logging
from datetime import datetime
from dotenv import load_dotenv
from meesho_bot import log

# Will be set by app.py to run_bg so state["running"]/last_run work correctly
_run_func = None

# Track which (date, time) slots have already been fired to avoid double-runs
_fired = set()
_stop_event = threading.Event()
_thread = None


def _get_times():
    load_dotenv(override=True)
    raw = os.getenv("SCHEDULE_TIMES", "")
    return [t.strip() for t in raw.split(",") if ":" in t.strip()]


def _get_days():
    load_dotenv(override=True)
    raw = os.getenv("SCHEDULE_DAYS", "").strip().lower()
    valid = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if not raw or raw in ("all", "everyday", "daily", "*"):
        return valid
    days = [d.strip() for d in raw.split(",") if d.strip() in valid]
    return days if days else valid


def _tick():
    """Called every 30 seconds. Fires run_func if current time matches schedule."""
    now = datetime.now()
    today_name = now.strftime("%a").lower()  # e.g. 'mon'
    today_date = now.strftime("%Y-%m-%d")
    current_hhmm = now.strftime("%H:%M")

    days = _get_days()
    if today_name not in days:
        return

    times = _get_times()
    for t in times:
        key = f"{today_date}_{t}"
        if t == current_hhmm and key not in _fired:
            _fired.add(key)
            log.info(f"[Scheduler] Triggering scheduled run at {t}")
            if _run_func is not None:
                try:
                    _run_func()
                except Exception as e:
                    log.error(f"[Scheduler] Error in run_func: {e}")
            else:
                from meesho_bot import run_all
                try:
                    run_all()
                except Exception as e:
                    log.error(f"[Scheduler] Error in run_all: {e}")

    # Clean up old fired keys (keep only today's)
    to_remove = [k for k in _fired if not k.startswith(today_date)]
    for k in to_remove:
        _fired.discard(k)


def _loop():
    log.info("[Scheduler] Background scheduler started.")
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception as e:
            log.error(f"[Scheduler] Tick error: {e}")
        _stop_event.wait(30)  # sleep 30s, but wake immediately if stopped
    log.info("[Scheduler] Scheduler stopped.")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="SchedulerThread")
    _thread.start()


def stop():
    _stop_event.set()


def get_active_times():
    return _get_times()


def get_active_days():
    return _get_days()


# When run directly as standalone
if __name__ == "__main__":
    import time
    start()
    log.info(f"Scheduler running. Times: {_get_times()} Days: {_get_days()}")
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        stop()
        log.info("Stopped.")