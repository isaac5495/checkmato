"""Live LLM-assist demo: Kingsoft fixture with Agnes, NO alias file provided.
Shows: subject inference -> auto-built cross-script aliases -> cross-language
evidence the deterministic engine alone could never connect."""
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


def main():
    findings, meta = run(ROOT / "tests" / "case_ks_en.md",
                         ROOT / "tests" / "corpus_ks",
                         ROOT / "reports" / "ks_llm", use_llm=True)
    print("inferred subject :", (meta.get("context") or {}).get("subject"))
    print("people         :", (meta.get("context") or {}).get("people"))
    print("alias groups   :", meta["alias_groups"], "| llm calls:", meta["llm_calls"])
    for grp in meta.get("alias_map", []):
        print("   ", " = ".join(grp))
    print()
    for x in findings:
        if x.get("para") is None:
            continue
        evs = ", ".join(e["ref"][:60] for e in x.get("evidence", []))
        print(f"  {x['id']} {x['type']:8} {x['raw'][:50]!r:54} -> {x['verdict']:11} {evs[:90]}")


if __name__ == "__main__":
    main()
