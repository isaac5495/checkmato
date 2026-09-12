"""LIVE demo of sentence/content-level checking — uses your exact paragraph.
Needs: .env key (Agnes/Gemini/Groq) + internet. Not part of run_all (no network).
Run: .venv\\Scripts\\python.exe -X utf8 tests/demo_deep_web.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        if v.strip():
            os.environ.setdefault(k.strip(), v.strip())

from app.cli import run  # noqa: E402

TEXT = (
    "More than four hundred days later, in September 1989, WPS 1.0 emerged from "
    "room 501: 122,000 lines of code, the first Chinese-language word processor "
    "of its kind. Every time it started, Qiu Bojun's name appeared on the screen, "
    "making him something close to a folk hero; in 1990 alone it sold 30,000 "
    "copies, generating RMB 66 million in revenue (about US$13.8 million).\n\n"
    "The team of 2,000 employees finished the remake in 1994."
)


def main():
    work = ROOT / "reports" / "deepweb"
    work.mkdir(parents=True, exist_ok=True)
    doc = work / "passage.md"
    doc.write_text(TEXT, encoding="utf-8")
    findings, meta = run(doc, None, work / "out", use_web=True, use_llm=True)
    ctx = meta.get("context") or {}
    print("subject        :", ctx.get("subject"))
    print("origin_language:", ctx.get("origin_language"))
    print("web searches   :", meta["web_searches_used"], "| llm calls:", meta["llm_calls"])
    print()
    zh_queries = 0
    for x in findings:
        if x.get("para") is None:
            continue
        for e in x.get("evidence", []):
            if e.get("kind") == "web" and any(not ch.isascii() for ch in e.get("quote", "")):
                zh_queries += 1
        evs = "; ".join(f"[{e['kind'].upper()}] {e['ref'][:58]}"
                        for e in x.get("evidence", [])[:3])
        print(f"  {x['id']} {x['type']:9} {x['raw'][:44]!r:48} -> {x['verdict']:12} {evs[:92]}")
    print("\nsnippets carrying Chinese source text:", zh_queries)


if __name__ == "__main__":
    main()
