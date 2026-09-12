"""Tiny persistent breaker store.

A fresh process currently FORGETS which backends were dead/slow, and re-pays
their full timeouts to relearn it (the 'restart makes it slow' effect). Only
STABLE conditions persist here (container down, geo-blocked key) — transient
rate-limits stay per-process so a healed endpoint is retried immediately.
"""
import json
import logging
import time
from pathlib import Path

log = logging.getLogger("checkmato.state")

_PATH = Path(__file__).resolve().parents[1] / ".breakers.json"
_TTL = 900  # seconds; a persisted-bad backend is retried after 15 min anyway


def _read():
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("breaker store unreadable (%s): %s", _PATH.name, e)
        return {}


def tripped(name):
    d = _read()
    entry = d.get(name)
    return bool(entry) and (time.time() - entry.get("ts", 0) < _TTL)


def trip(name):
    d = _read()
    d[name] = {"ts": time.time()}
    try:
        _PATH.write_text(json.dumps(d), encoding="utf-8")
    except Exception as e:
        log.warning("could not persist breaker trip (%s): %s", name, e)


def heal(name):
    d = _read()
    if d.pop(name, None) is not None:
        try:
            _PATH.write_text(json.dumps(d), encoding="utf-8")
        except Exception as e:
            log.warning("could not persist breaker heal (%s): %s", name, e)
