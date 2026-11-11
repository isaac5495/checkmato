"""Persistent SERP cache: the same query must never be paid for twice.

Design rules (quality first):
- Store search RESULTS only (title/href/body). Never verdicts: a judge change
  must not replay an old decision.
- Cache only non-empty SERPs. An empty result may be a transient backend miss;
  caching it would silently keep a claim unverified for the TTL.
- Key by backend + normalized query + result count. A miss sends the ORIGINAL
  query unchanged — normalization never rewrites what the search engine sees.
- Per-install file by default. Hosted multi-tenant deployments that need
  isolation should point `search_cache_path` at a tenant-specific file.
"""
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path

log = logging.getLogger("checkmato.searchcache")

DEFAULT_DAYS = 14


def normalize_query(query):
    """Key-only normalization: case, width, and whitespace.

    Punctuation is deliberately kept: `"exact phrase"` and `exact phrase` are
    different searches, and merging them would change the evidence seen.
    """
    q = unicodedata.normalize("NFKC", str(query or ""))
    return " ".join(q.split()).casefold()


def default_path():
    root = os.environ.get("CHECKMATO_CACHE_DIR")
    if root:
        return str(Path(root) / "search_cache.sqlite")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return str(Path(base) / "CheckMato" / "search_cache.sqlite")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return str(Path(base) / "checkmato" / "search_cache.sqlite")


class SearchCache:
    def __init__(self, path=None, days=DEFAULT_DAYS, enabled=True):
        self.path = str(path or default_path())
        self.days = max(0.0, float(days or 0))
        self.enabled = bool(enabled)
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self._lock = threading.Lock()
        self._conn = None

    def _connect(self):
        if self._conn is not None:
            return self._conn
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS serp_cache ("
            " key TEXT PRIMARY KEY,"
            " backend TEXT NOT NULL,"
            " max_results INTEGER NOT NULL,"
            " results TEXT NOT NULL,"
            " created_at REAL NOT NULL)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_serp_created "
            "ON serp_cache(created_at)")
        conn.commit()
        self._conn = conn
        return conn

    def _key(self, backend, query, max_results):
        raw = (f"{backend}\x1f{normalize_query(query)}\x1f"
               f"{int(max_results)}")
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, backend, query, max_results):
        if not self.enabled:
            return None
        key = self._key(backend, query, max_results)
        try:
            with self._lock:
                conn = self._connect()
                row = conn.execute(
                    "SELECT results, created_at FROM serp_cache WHERE key=?",
                    (key,)).fetchone()
                if not row:
                    self.misses += 1
                    return None
                blob, created = row
                if self.days and time.time() - float(created) > self.days * 86400:
                    conn.execute("DELETE FROM serp_cache WHERE key=?", (key,))
                    conn.commit()
                    self.misses += 1
                    return None
                self.hits += 1
                return json.loads(blob)
        except Exception as e:  # a cache failure must never break a run
            log.warning("search cache read failed (ignored): %s", e)
            with self._lock:
                self.misses += 1
            return None

    def put(self, backend, query, max_results, results):
        if not self.enabled or not results:
            return
        key = self._key(backend, query, max_results)
        try:
            blob = json.dumps(results, ensure_ascii=False)
            with self._lock:
                conn = self._connect()
                conn.execute(
                    "INSERT OR REPLACE INTO serp_cache"
                    "(key, backend, max_results, results, created_at) "
                    "VALUES(?,?,?,?,?)",
                    (key, backend, int(max_results), blob, time.time()))
                conn.commit()
                self.writes += 1
        except Exception as e:
            log.warning("search cache write failed (ignored): %s", e)

    def stats(self):
        return {"hits": self.hits, "misses": self.misses,
                "writes": self.writes, "path": self.path}

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None
