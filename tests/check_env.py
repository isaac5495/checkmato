from pathlib import Path

p = Path(__file__).resolve().parents[1] / ".env"
print("exists:", p.exists())
if p.exists():
    ok = False
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        if v:
            ok = True
            print(f"  {k}: set ({len(v)} chars, prefix {v[:4]}...)")
        else:
            print(f"  {k}: EMPTY")
    print("ready" if ok else "key still empty")
