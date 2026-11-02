"""sources_only is a promise: no socket may be opened during a run.

Every outbound path is replaced with a counter that raises. The run must still
finish and produce a report. This is the gate that keeps "0 network" honest
when a future change adds a "harmless" lookup.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import socket
    import urllib.request

    from app.cli import run

    calls = {"n": 0}

    def _blocked(*_a, **_k):
        calls["n"] += 1
        raise OSError("network disabled by test_byos_offline")

    real_connect = socket.socket.connect
    real_create = socket.create_connection
    real_urlopen = urllib.request.urlopen
    socket.socket.connect = _blocked
    socket.create_connection = _blocked
    urllib.request.urlopen = _blocked
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            _findings, meta = run(
                str(ROOT / "tests" / "byos" / "book_only.docx"),
                out_dir=str(out), library=str(ROOT / "tests" / "byos" / "lib"),
                sources_only=True, footnotes=True)
            assert (out / "report.md").exists(), "report missing"
            assert meta["mode"] == "sources_only"
            assert meta["web_search_budget"] == 0, "web budget exists in sources_only"
    finally:
        socket.socket.connect = real_connect
        socket.create_connection = real_create
        urllib.request.urlopen = real_urlopen

    assert calls["n"] == 0, f"{calls['n']} network call(s) attempted"
    print(f"OFFLINE: PASS ({calls['n']} connections)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
