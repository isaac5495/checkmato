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
    # §9 free-first quotas — limits are budgets, never paywalls
    # These per-day counters guard ONE thing: strangers sharing a hosted
    # instance, so a single visitor cannot burn the operator's shared free-tier
    # keys. They are meaningless for the packaged desktop app, where the user
    # owns the machine, the IP and the keys -- there is nobody to protect the
    # quota from, so the cap is pure friction. Set enforce_ip_quota = false in
    # a desktop build; the per-document max_words sanity cap still applies,
    # because refusing a 10MB file is about the machine, not the quota.
    "enforce_ip_quota": True,        # False = desktop/app build: no per-day caps
    "quota_ip_per_day": 1,          # guest (no account): 1 doc/day/IP
    "max_words": 10_000,            # per document (guest tier cap)
    "max_words_per_day": 60_000,    # per IP/day aggregate
    "deep_max_claims": 16,          # LLM-planned deep web checks per run
    "brave_monthly_cap": 1000,      # Brave free credit; 0 left → skip the key
    # Persistent SERP cache: the same query is never paid for twice. Stores
    # search results only, never verdicts. Empty = per-user data dir; hosted
    # multi-tenant deployments should set a tenant-specific path.
    "search_cache": True,
    "search_cache_days": 14,
    "search_cache_path": "",
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
    return cfg
