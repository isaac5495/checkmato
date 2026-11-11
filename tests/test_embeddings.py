"""Optional W2 semantic retrieval: adapter, cache, and off-by-default gate.

Offline; a fake embedding model keeps the base gate independent of fastembed
and model downloads. The real model is exercised by the manual gold harness.
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeModel:
    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        for t in texts:
            self.calls += 1
            s = str(t)
            if "alpha" in s:
                yield np.array([1.0, 0.0, 0.0], dtype="float32")
            elif "beta" in s:
                yield np.array([0.0, 1.0, 0.0], dtype="float32")
            else:
                yield np.array([0.0, 0.0, 1.0], dtype="float32")


def main():
    from app.corpus import Corpus
    from app.embeddings import SemanticIndex, detect_lang, get_index

    n = 0

    def ok(cond, msg):
        nonlocal n
        assert cond, f"EMBEDDING FAIL: {msg}"
        n += 1

    ok(detect_lang("金山科技的营业收入") == "zh", "Chinese is detected")
    ok(detect_lang("Acme revenue grew") == "en", "English is detected")

    passages = [
        {"fname": "a.md", "start": 1, "text": "alpha passage"},
        {"fname": "b.md", "start": 2, "text": "beta passage"},
        {"fname": "c.md", "start": 3, "text": "gamma passage"},
    ]
    old_model = os.environ.get("CHECKMATO_EMBED_MODEL")
    os.environ["CHECKMATO_EMBED_MODEL"] = "fake/model"
    try:
        override = get_index(passages, text="alpha")
        ok(override.model_name == "fake/model", "model override is honored")
    finally:
        if old_model is None:
            os.environ.pop("CHECKMATO_EMBED_MODEL", None)
        else:
            os.environ["CHECKMATO_EMBED_MODEL"] = old_model
    with tempfile.TemporaryDirectory() as td:
        fake = FakeModel()
        idx = SemanticIndex(passages, model=fake, cache_dir=td,
                            model_name="fake-model")
        hits = idx.search("alpha", top=2)
        ok(hits and hits[0][1]["text"] == "alpha passage",
           f"nearest passage is alpha ({hits})")
        ok(hits[0][0] > hits[1][0], "scores are ordered")

        # Cache: a second index with the same corpus must not re-embed passages
        # (only the query is embedded).
        fake2 = FakeModel()
        idx2 = SemanticIndex(passages, model=fake2, cache_dir=td,
                             model_name="fake-model")
        idx2.search("beta", top=1)
        ok(fake2.calls == 1, f"cached vectors reuse (calls={fake2.calls})")

    # Base install / default: semantic lane is off and returns no evidence.
    with tempfile.TemporaryDirectory() as td:
        Path(td, "s.md").write_text("alpha passage\n", encoding="utf-8")
        old = os.environ.pop("CHECKMATO_SEMANTIC", None)
        try:
            corpus = Corpus(td)
            ok(corpus.semantic_search("alpha") == [],
               "semantic lane is off by default")
        finally:
            if old is not None:
                os.environ["CHECKMATO_SEMANTIC"] = old

    print(f"EMBEDDING TESTS: PASS ({n} assertions)")


if __name__ == "__main__":
    main()
