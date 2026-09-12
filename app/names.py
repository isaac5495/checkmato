"""Alias/name equivalence maps (generalizes the KS translation-glossary idea).

A user-supplied file maps surface forms of the same entity across languages
and scripts:  CSV with >=2 columns ("Kingsoft Office,金山办公,note") or plain
lines ("Kingsoft Office = 金山办公"). Used to
  (1) expand claim subject tokens with cross-script aliases so an EN document
      finds evidence in a ZH book line (and vice versa),
  (2) extend web entity anchors to the mapped names,
  (3) detect name drift: the same event attributed to two names that are NOT
      aliases of one another.
"""
import re

from . import textproc as tp


class AliasMap:
    def __init__(self, groups=()):
        # each group: list of surface forms; token sets precomputed
        self.groups = [(g, [tp.tokens(f) for f in g]) for g in groups if len(g) >= 2]
        self.forms = {f for g, _ in self.groups for f in g}

    @classmethod
    def load(cls, path):
        if not path:
            return cls()
        import csv as _csv
        from pathlib import Path
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        groups = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line and "," not in line:
                parts = [x.strip() for x in line.split("=")]
                parts = [x for x in parts if len(x) >= 2 and not x.isdigit()]
            else:
                row = [x.strip() for x in next(_csv.reader([line]))]
                parts = [x for x in row[:2] if len(x) >= 2 and not x.isdigit()]
            if len(parts) >= 2:
                groups.append(parts)
        if groups and groups[0][0].lower() in ("en", "name", "english", "chinese"):
            groups.pop(0)  # header row
        return cls(groups)

    def expand_tokens(self, token_set):
        """Return token_set plus tokens of every alias group touching it."""
        if not self.groups:
            return token_set
        out = set(token_set)
        for _forms, toksets in self.groups:
            if any(ts & out for ts in toksets):
                for ts in toksets:
                    out |= ts
        return out

    def anchor_forms(self):
        out = set()
        for _forms, toksets in self.groups:
            for ts in toksets:
                out |= ts
        return out

    def are_aliases(self, name_a, name_b):
        ta, tb = tp.tokens(name_a), tp.tokens(name_b)
        for _forms, toksets in self.groups:
            hit_a = any(ts & ta for ts in toksets)
            hit_b = any(ts & tb for ts in toksets)
            if hit_a and hit_b:
                return True
        return False

    def add_group(self, forms):
        forms = [f for f in forms if f and len(f) >= 2]
        if len(forms) >= 2:
            self.groups.append((forms, [tp.tokens(f) for f in forms]))


_ZH_PERSON = re.compile(
    r"([\u4e00-\u9fff]{2,3})(?=说|称|表示|回忆|指出|创立|创办|加入|任职|宣布|领导)")
_ZH_ORG = re.compile(
    r"([\u4e00-\u9fff]{2,6}?(?:软件|办公|集团|公司|科技|云))(?=于|在|宣布|成立|完成|的)")


def extract_names(corpus_or_text, limit=40):
    """Candidate person/org names in source text (CJK patterns + EN entities),
    used to auto-match aliases against the document's names."""
    if hasattr(corpus_or_text, "lines"):
        text = "\n".join(row[2] for row in corpus_or_text.lines[:4000])
    else:
        text = str(corpus_or_text)
    names = []
    for rx in (_ZH_PERSON, _ZH_ORG):
        for m in rx.finditer(text):
            if m.group(1) not in names:
                names.append(m.group(1))
    import re as _re
    for m in _re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", text):
        cand = m.group(1)
        if cand.lower() not in tp.STOP and cand not in names:
            names.append(cand)
    return names[:limit]
