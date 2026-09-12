"""Runtime settings from an optional checkmato.toml (fallbacks to defaults).

Keeps budgets/thresholds out of code so M1 can edit them without a redeploy.
Example checkmato.toml:
    max_search = 80
    fx_tolerance = 0.08
    whitelist = ["reuters.com", "gov.cn", "hkex.com.hk"]
    quote_verbatim_cut = 0.98
"""
import logging
import os

log = logging.getLogger("checkmato.config")

DEFAULTS = {
    "max_search": 60,
    "fx_tolerance": 0.10,
    "whitelist": [],
    "quote_verbatim_cut": 0.98,
    "quote_paraphrase_cut": 0.62,
    "llm_max_calls": 30,
    "llm_max_tokens": 60000,
    "llm_max_seconds": 270,
    "web_max_seconds": 240,
    "max_pages": 16,              # deep-read full-page fetches per run
    "searxng_url": "",            # e.g. http://127.0.0.1:8080 (or env SEARXNG_URL)
    "searxng_engines": "",        # optional: "google,bing,duckduckgo"
    # §9 free-first quotas — limits are budgets, never paywalls
    "quota_ip_per_day": 1,          # guest (no account): 1 doc/day/IP
    "max_words": 10_000,            # per document (guest tier cap)
    "max_words_per_day": 60_000,    # per IP/day aggregate
    "deep_max_claims": 16,          # LLM-planned deep web checks per run
    "brave_monthly_cap": 1000,      # Brave free credit; 0 left → skip the key
}


def load(path=None):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        try:
            import tomllib
            with open(path, "rb") as f:
                cfg.update({k: v for k, v in tomllib.load(f).items()
                            if k in DEFAULTS})
        except Exception as e:
            log.warning("could not parse %s — using defaults: %s", path, e)
    if not cfg.get("searxng_url"):
        cfg["searxng_url"] = os.environ.get("SEARXNG_URL", "")
    return cfg
