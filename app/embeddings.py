"""Optional local semantic retrieval for BYOS passages (W2, decision A).

Base install stays unchanged: this module is imported only when
`CHECKMATO_SEMANTIC=1` and `fastembed` is installed. If the extra is missing,
the caller falls back to the existing lexical lanes and never downloads a
model at import time.

Model choice is language-aware and small enough for CPU:
- Chinese: BAAI/bge-small-zh-v1.5
- English: BAAI/bge-small-en-v1.5
Override with CHECKMATO_EMBED_MODEL. Embeddings are cached on disk by a
corpus fingerprint, so a 6k-line library is embedded once.
"""
import hashlib
import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger("checkmato.embeddings")

DEFAULT_ZH = "BAAI/bge-small-zh-v1.5"
DEFAULT_EN = "BAAI/bge-small-en-v1.5"


def detect_lang(text):
    s = str(text or "")
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return "zh" if cjk and cjk >= max(4, len(s) * 0.03) else "en"


def _cache_dir():
    explicit = os.environ.get("CHECKMATO_EMBED_CACHE")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "CheckMato" / "embeddings"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "checkmato" / "embeddings"


def _fingerprint(model_name, passages):
    h = hashlib.sha256(model_name.encode("utf-8"))
    h.update(str(len(passages)).encode())
    for p in passages:
        h.update(f"{p.get('fname')}:{p.get('start')}:".encode("utf-8"))
        text = (p.get("text") or "").encode("utf-8")
        h.update(str(len(text)).encode())
        # Content, not just length: an edit that keeps the character count
        # must not reuse stale vectors.
        h.update(hashlib.sha256(text).digest()[:8])
    return h.hexdigest()[:24]


class SemanticIndex:
    def __init__(self, passages, model_name=None, lang="zh", model=None,
                 cache_dir=None):
        self.passages = list(passages or [])
        self.lang = lang
        self.model_name = model_name or (
            DEFAULT_ZH if lang == "zh" else DEFAULT_EN)
        self._model = model
        self._vectors = None
        self._ready = model is not None
        self._failed = False
        self._cache_dir = Path(cache_dir) if cache_dir else _cache_dir()

    def _ensure_model(self):
        if self._ready:
            return True
        if self._failed:
            return False
        try:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.model_name,
                                        cache_dir=str(self._cache_dir))
            self._ready = True
            return True
        except Exception as e:
            log.warning("semantic model unavailable (%s): %s",
                        self.model_name, e)
            self._failed = True
            self._ready = False
            return False

    def _cache_paths(self):
        fp = _fingerprint(self.model_name, self.passages)
        base = self._cache_dir / f"{self.model_name.replace('/', '_')}_{fp}"
        # model names contain dots (bge-small-zh-v1.5); with_suffix would
        # replace the fingerprint after the last dot and collide corpora.
        return Path(str(base) + ".npy"), Path(str(base) + ".json")

    def build(self):
        if not self._ensure_model():
            return False
        if self._vectors is not None:
            return True
        npy, meta = self._cache_paths()
        try:
            if npy.exists() and meta.exists():
                self._vectors = np.load(npy)
                if self._vectors.shape[0] == len(self.passages):
                    return True
        except Exception:
            pass
        texts = [(p.get("text") or "")[:2000] for p in self.passages]
        if not texts:
            return False
        try:
            vectors = np.asarray(list(self._model.embed(texts)),
                                 dtype="float32")
        except Exception as e:
            log.warning("semantic embedding failed: %s", e)
            return False
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            return False
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-9)
        self._vectors = vectors
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            np.save(npy, vectors)
            meta.write_text("{}", encoding="utf-8")
        except Exception as e:
            log.warning("semantic cache write failed: %s", e)
        return True

    def search(self, query, top=8):
        if not self.build() or self._vectors is None:
            return []
        try:
            # BGE retrieval models are trained with an asymmetric query
            # instruction; fastembed adds it in query_embed(). A fake/other
            # model without that method still works through plain embed().
            embed_query = (getattr(self._model, "query_embed", None)
                           or self._model.embed)
            q = np.asarray(next(iter(embed_query([query]))), dtype="float32")
        except Exception as e:
            log.warning("semantic query failed: %s", e)
            return []
        q = q / max(float(np.linalg.norm(q)), 1e-9)
        scores = self._vectors @ q
        idx = np.argsort(-scores, kind="stable")[:max(1, int(top))]
        return [(float(scores[i]), self.passages[int(i)]) for i in idx]

    @property
    def ready(self):
        return self._ready


def get_index(passages, text="", cache_dir=None, lang=None):
    if not passages:
        return None
    lang = lang or detect_lang(text or " ".join(
        (p.get("text") or "")[:200] for p in passages[:20]))
    model_name = os.environ.get("CHECKMATO_EMBED_MODEL") or None
    return SemanticIndex(passages, model_name=model_name, lang=lang,
                         cache_dir=cache_dir)
