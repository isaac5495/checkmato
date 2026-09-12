"""Dual-version diff + alias/name layer tests (offline, deterministic)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.diff import compare  # noqa: E402
from app.extract import read_doc  # noqa: E402
from app.names import AliasMap  # noqa: E402

A = str(ROOT / "tests" / "ver_en.md")
B = str(ROOT / "tests" / "ver_zh.md")
NAMES = str(ROOT / "tests" / "ver_names.csv")


def raws(findings):
    return " || ".join(f["raw"] for f in findings)


def main():
    fails = []
    # 1) without aliases: the SAME person in two scripts is (wrongly) two names,
    #    and cross-script facts drift.
    fa, _ = compare(read_doc(A), read_doc(B))
    r = raws(fa)
    checks = [
        ("year near-miss 2010/2011", "2010" in r and "2011" in r and "differs" in r),
        ("amount near-miss 120m/150m", "differs" in r and "120" in r and "150" in r),
        ("URL only in A", "URL only in A" in r),
        ("Series C 60m NOT flagged (identical)", "60" not in r.replace("60 million, led", "60million")),
    ]
    # 2) with aliases: Ada Chen == 陳艾達 collapses; 'company' name reconciles
    alias = AliasMap.load(NAMES)
    fb, _ = compare(read_doc(A), read_doc(B), alias)
    rb = raws(fb)
    checks += [
        ("alias canonicalizes founder", "Ada Chen" not in rb or "only in" not in rb),
        ("amount+year drift still present (alias doesn't hide real drift)",
         "differs" in rb),
    ]
    # 3) alias map unit behaviour
    amap = AliasMap.load(NAMES)
    exp = amap.expand_tokens({"ada", "chen"})
    checks += [
        ("expand_tokens reaches ZH form tokens", any(not t.isascii() for t in exp)),
        ("are_aliases(Ada Chen, 陳艾達)", amap.are_aliases("Ada Chen", "陳艾達")),
        ("names not falsely aliased", not amap.are_aliases("Ada Chen", "Bo Liu")),
    ]
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            fails.append(name)
    print("DIFF/ALIAS:", "PASS" if not fails else f"FAIL {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
