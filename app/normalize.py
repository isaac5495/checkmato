"""Query normalisation for retrieval: atomic spans, pronouns, aliases.

The claim shown to the user never changes. These helpers build a better QUERY
for retrieval, so a pronoun or a compound sentence does not hide the subject.
"""
import re

_SPLIT = re.compile(r"(?:;\s+|,\s+(?:and|but|while|yet)\s+)", re.I)
_PRONOUN = re.compile(
    r"^(it|they|he|she|the company|the firm|this company|the group)\b",
    re.I)


def split_compound(sentence):
    """[(part, start, end)] — spans refer to the ORIGINAL sentence."""
    parts, last = [], 0
    for m in _SPLIT.finditer(sentence or ""):
        piece = sentence[last:m.start()].strip()
        if len(piece.split()) >= 3:
            parts.append((piece, last, m.start()))
        last = m.end()
    tail = (sentence or "")[last:].strip()
    if tail:
        parts.append((tail, last, len(sentence or "")))
    if len(parts) > 1:
        return parts
    return [(sentence or "", 0, len(sentence or ""))]


def resolve_pronoun(sentence, subject):
    """Replace a leading anaphor with the paragraph subject (query only)."""
    if not subject:
        return sentence or ""
    return _PRONOUN.sub(str(subject), sentence or "", count=1)


def query_text(sentence, subject="", alias_groups=()):
    """Retrieval query: pronoun-resolved sentence plus verified alias forms."""
    q = resolve_pronoun(sentence, subject)
    low = q.lower()
    for group in alias_groups or ():
        names = [str(n) for n in group if len(str(n)) > 2]
        if any(n.lower() in low for n in names):
            for n in names:
                if n.lower() not in low:
                    q += " " + n
    if subject and str(subject).lower() not in q.lower():
        q += " " + str(subject)
    return q.strip()
