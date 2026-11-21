import hashlib
import json
import logging
import time
from typing import Optional
from jobpilot.core.config import settings
from jobpilot.core.db import (
    get_cached_llm_response,
    set_cached_llm_response,
    record_llm_usage,
    get_today_llm_usage,
    log_event
)

logger = logging.getLogger("jobpilot.llm")

# Global pacing state to guarantee we never exceed 15 RPM
_last_live_call_timestamp: float = 0.0


def _compute_hash(text: str, json_mode: bool) -> str:
    key = f"{text.strip()}__json={json_mode}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def generate(prompt: str, json_mode: bool = False, max_retries: int = 2, backoff_base: float = 2.0) -> str:
    """
    Unified LLM call with strict anti-waste guardrails:
    1. Caches responses by SHA-256 in SQLite.
    2. Enforces daily request and token budgets.
    3. Paces requests with min_seconds_between_calls.
    4. Truncates overly long prompt input.
    5. Tracks daily token consumption in SQLite.
    6. Automatic fallback between flash models.
    """
    global _last_live_call_timestamp

    max_chars = settings.llm_max_input_characters
    if len(prompt) > max_chars + 1000:
        logger.info("Prompt exceeded %d chars; trimming boilerplate to conserve tokens.", max_chars)
        prompt = prompt[:max_chars] + "\n[...trimmed remainder to conserve token quota...]"

    prompt_hash = _compute_hash(prompt, json_mode)

    # 1. SQLite Cache (Zero token cost)
    cached = get_cached_llm_response(prompt_hash)
    if cached is not None:
        logger.debug("LLM cache hit for hash: %s", prompt_hash[:10])
        return cached

    # 2. Check API Key
    api_key = settings.gemini_api_key.strip()
    if not api_key or api_key.startswith("your_"):
        raise RuntimeError("GEMINI_API_KEY is missing or invalid in .env. LLM generation requires a valid Gemini API key.")

    # 3. Check Daily Token & Request Quota
    usage = get_today_llm_usage()
    if usage["request_count"] >= settings.llm_max_requests_per_day:
        msg = f"[QUOTA GUARD] Daily request limit ({settings.llm_max_requests_per_day}) reached for today."
        logger.error(msg)
        log_event("llm_guard", msg, level="ERROR")
        raise RuntimeError(msg)

    if usage["total_tokens"] >= settings.llm_max_tokens_per_day:
        msg = f"[QUOTA GUARD] Daily token ceiling ({settings.llm_max_tokens_per_day}) reached for today."
        logger.error(msg)
        log_event("llm_guard", msg, level="ERROR")
        raise RuntimeError(msg)

    # 4. Pacing Rate Limiter
    min_interval = settings.llm_min_seconds_between_calls
    elapsed_since_last = time.time() - _last_live_call_timestamp
    if elapsed_since_last < min_interval:
        sleep_needed = min_interval - elapsed_since_last
        logger.debug("Pacing LLM call: pausing %.2fs...", sleep_needed)
        time.sleep(sleep_needed)

    # 5. Gemini API invocation
    import google.generativeai as genai
    from google.api_core import exceptions

    genai.configure(api_key=api_key)
    primary_model = settings.gemini_model or "gemini-3.5-flash-lite"
    candidate_models = []
    for m in [primary_model, "gemini-3.5-flash-lite", "gemini-3.8-flash"]:
        if m and m not in candidate_models:
            candidate_models.append(m)

    last_error: Optional[Exception] = None

    for model_name in candidate_models:
        generation_config = {}
        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        for attempt in range(max_retries + 1):
            try:
                _last_live_call_timestamp = time.time()
                model = genai.GenerativeModel(model_name=model_name, generation_config=generation_config)
                response = model.generate_content(prompt)

                text = response.text.strip()
                if not text:
                    raise ValueError(f"Gemini returned an empty response from model {model_name}")

                # Record tokens
                est_tokens = _estimate_tokens(prompt) + _estimate_tokens(text)
                record_llm_usage(call_type="generate", tokens_used=est_tokens)

                # Cache
                set_cached_llm_response(prompt_hash, text)
                return text

            except (exceptions.ResourceExhausted, exceptions.TooManyRequests) as e:
                last_error = e
                wait_sec = backoff_base ** (attempt + 1)
                logger.warning("Quota exhausted on %s (attempt %d). Waiting %.1fs...", model_name, attempt + 1, wait_sec)
                time.sleep(wait_sec)
            except Exception as e:
                last_error = e
                logger.error("LLM generation error on %s: %s", model_name, str(e))
                break

    raise RuntimeError(f"All candidate Gemini models failed. Last error: {last_error}")

