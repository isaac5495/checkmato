"""Local BM25 passage index (bm25s, MIT). No service, no network.

The index is optional: if bm25s is missing the corpus still works with the
inverted-token and value indexes. It is built over the same passage objects the
judge already uses, so evidence locators do not change.
"""
import logging

log = logging.getLogger("checkmato.retrieval")

try:
    import bm25s
except Exception as e:  # optional dependency: degrade, never fail a run
    bm25s = None
    log.warning("bm25s unavailable; BM25 ranking disabled (%s)", e)


class BM25Index:
    def __init__(self, passages):
        self.passages = list(passages or [])
        self.ok = False
        if bm25s is None or not self.passages:
            return
        try:
            self._retriever = bm25s.BM25()
            self._tokens = bm25s.tokenize([p["text"] for p in self.passages])
            self._retriever.index(self._tokens)
            self.ok = True
        except Exception as e:
            log.warning("bm25s index build failed: %s", e)

    def search(self, query, top=8):
        if not self.ok or not query:
            return []
        try:
            q = bm25s.tokenize([query])
            ids, scores = self._retriever.retrieve(
                q, k=min(top, len(self.passages)))
        except Exception as e:
            log.warning("bm25s query failed: %s", e)
            return []
        out = []
        for i, s in zip(ids[0], scores[0]):
            if float(s) > 0:
                out.append((float(s), self.passages[int(i)]))
        return out

    @property
    def version(self):
        return getattr(bm25s, "__version__", "unknown") if bm25s else "none"
