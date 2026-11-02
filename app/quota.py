"""Persistent guest quotas (IP/day) and Brave monthly search cap.

Brave free credit is ~1,000 queries/month. Spending it on every ladder rung
was the silent quality cliff: once the key is empty, a chain still tried Brave
first and paid 429s. Counts live in `.quota.json` so a restart cannot forget
a spent month or a spent day.
"""
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("checkmato.quota")

_DEFAULT = Path(__file__).resolve().parents[1] / ".quota.json"
_LOCK = threading.Lock()

IP = {}
_brave = {"month": "", "used": 0}


def _path():
    return Path(os.environ.get("CHECKMATO_QUOTA_PATH") or _DEFAULT)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _month():
    return datetime.now().strftime("%Y-%m")


def _read():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("quota store unreadable: %s", e)
        return {}


def _write():
    try:
        p = _path()
        p.write_text(json.dumps({"ip": IP, "brave": _brave}), encoding="utf-8")
    except Exception as e:
        log.warning("could not persist quota: %s", e)


def _roll_brave():
    m = _month()
    if _brave.get("month") != m:
        _brave["month"] = m
        _brave["used"] = 0


def load():
    d = _read()
    IP.clear()
    IP.update(d.get("ip") or {})
    b = d.get("brave") or {}
    _brave["month"] = str(b.get("month") or "")
    _brave["used"] = int(b.get("used") or 0)
    _roll_brave()


def brave_cap():
    try:
        from . import config
        return int(config.load("checkmato.toml").get("brave_monthly_cap") or 1000)
    except Exception:
        return 1000


def brave_left(cap=None):
    cap = brave_cap() if cap is None else int(cap)
    with _LOCK:
        _roll_brave()
        return max(0, cap - int(_brave.get("used") or 0))


def brave_spend(n=1, cap=None):
    cap = brave_cap() if cap is None else int(cap)
    with _LOCK:
        _roll_brave()
        _brave["used"] = int(_brave.get("used") or 0) + max(0, int(n))
        _write()
        return max(0, cap - _brave["used"])


def check_ip(ip, words, cfg):
    day = IP.setdefault(f"{ip}:{_today()}", {"runs": 0, "words": 0})
    # Per-document sanity cap: kept even when the per-day abuse counters are
    # off, because it protects the machine (don't process a 10MB file) rather
    # than a shared quota.
    if words > cfg["max_words"]:
        return False, f"document exceeds the {cfg['max_words']}-word cap"
    if not cfg.get("enforce_ip_quota", True):
        return True, ""      # desktop/app build: the user owns the keys
    if day["runs"] >= cfg["quota_ip_per_day"]:
        return False, "daily quota reached for this network — please try tomorrow"
    if day["words"] + words > cfg["max_words_per_day"]:
        return False, "today's word budget is spent — please try tomorrow"
    return True, ""


def charge_ip(ip, words):
    with _LOCK:
        day = IP.setdefault(f"{ip}:{_today()}", {"runs": 0, "words": 0})
        day["runs"] += 1
        day["words"] += words
        _write()


def snapshot(ip, cfg):
    day = IP.get(f"{ip}:{_today()}") or {"runs": 0, "words": 0}
    cap = int(cfg.get("brave_monthly_cap") or brave_cap())
    with _LOCK:
        _roll_brave()
        used = int(_brave.get("used") or 0)
    # When the per-day counters are switched off they must not be REPORTED as
    # exhausted: a desktop build with runs_left = 0 renders in the UI as
    # "0 runs left today", which is both false and the exact signal that makes
    # a user think they are blocked when they are not. Say so plainly instead.
    enforced = bool(cfg.get("enforce_ip_quota", True))
    return {
        "enforced": enforced,
        "runs_per_day": cfg["quota_ip_per_day"] if enforced else 0,
        "words_per_doc": cfg["max_words"],
        "words_per_day": cfg["max_words_per_day"] if enforced else 0,
        "runs_left": (max(0, cfg["quota_ip_per_day"] - day["runs"])
                      if enforced else None),
        "words_left": (max(0, cfg["max_words_per_day"] - day["words"])
                       if enforced else None),
        "runs_used": day["runs"],
        "brave_cap": cap,
        "brave_used": used,
        "brave_left": max(0, cap - used),
    }


load()
