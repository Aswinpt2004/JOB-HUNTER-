import pytest
from src.llm import generate, _estimate_tokens
from src.db import get_today_llm_usage, set_cached_llm_response, get_cached_llm_response

def test_token_estimation():
    text = "Hello world from JobPilot"
    est = _estimate_tokens(text)
    assert est > 0
    assert est == len(text) // 4


def test_cache_avoids_llm_call(monkeypatch):
    # If a prompt is cached, generate() must return immediately from cache
    test_prompt = "Unique test prompt for caching verification"
    test_hash = "unique_hash_123"

    # Pre-populate cache
    from src.llm import _compute_hash
    p_hash = _compute_hash(test_prompt, json_mode=False)
    set_cached_llm_response(p_hash, "Cached response value")

    res = generate(test_prompt, json_mode=False)
    assert res == "Cached response value"


def test_quota_guard_fallback(monkeypatch):
    from src.config import settings, Config
    # Set limit to 0 requests
    monkeypatch.setattr(Config, "llm_max_requests_per_day", property(lambda self: 0))

    # Any non-cached call should hit quota guard and return fallback without crashing
    res = generate("Brand new un-cached prompt that triggers quota guard", json_mode=False)
    assert res is not None
    assert "fallback" in res.lower() or "candidate" in res.lower() or "hiring" in res.lower()

