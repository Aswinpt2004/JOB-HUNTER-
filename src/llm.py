import hashlib
import json
import logging
import time
from typing import Optional
from src.config import settings
from src.db import (
    get_cached_llm_response,
    set_cached_llm_response,
    record_llm_usage,
    get_today_llm_usage,
    log_event
)

logger = logging.getLogger("jobpilot.llm")

# Global pacing state to guarantee we never exceed 15 requests per minute
_last_live_call_timestamp: float = 0.0


def _compute_hash(text: str, json_mode: bool) -> str:
    key = f"{text.strip()}__json={json_mode}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    """Heuristic estimate of tokens for English text (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def generate(prompt: str, json_mode: bool = False, max_retries: int = 2, backoff_base: float = 2.0) -> str:
    """
    Single unified function for all LLM calls with strict anti-waste guardrails:
    1. Caches responses by SHA-256 hash in SQLite (never calls LLM twice for same prompt).
    2. Enforces daily request and token budgets from config.yaml to prevent quota exhaustion.
    3. Paces requests with a minimum interval between calls to keep strictly within RPM limits.
    4. Truncates overly long prompt input text to eliminate wasted tokens.
    5. Tracks daily token consumption in SQLite for full visibility.
    6. Fail-fast error handling: stops immediately if credentials, files, or quotas fail.
    """
    global _last_live_call_timestamp

    # Guardrail 0: Truncate input if excessive to eliminate wasted tokens
    max_chars = settings.llm_max_input_characters
    if len(prompt) > max_chars + 1000:
        logger.info("Prompt exceeded %d chars; trimming boilerplate to conserve tokens.", max_chars)
        prompt = prompt[:max_chars] + "\n[...trimmed remainder to conserve token quota...]"

    prompt_hash = _compute_hash(prompt, json_mode)

    # Guardrail 1: Check SQLite Cache (Zero Token Consumption)
    cached = get_cached_llm_response(prompt_hash)
    if cached is not None:
        logger.debug("LLM cache hit (0 tokens used) for hash: %s", prompt_hash[:10])
        return cached

    # Guardrail 2: Check API Key presence - Fail Fast
    api_key = settings.gemini_api_key.strip()
    if not api_key or api_key.startswith("your_"):
        raise RuntimeError("GEMINI_API_KEY is missing or invalid in .env. LLM generation requires a valid Gemini API key.")

    # Guardrail 3: Check Daily Token & Request Quota - Fail Fast
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

    # Guardrail 4: Pacing Rate Limiter (enforces minimum seconds between calls to prevent 429)
    min_interval = settings.llm_min_seconds_between_calls
    elapsed_since_last = time.time() - _last_live_call_timestamp
    if elapsed_since_last < min_interval:
        sleep_needed = min_interval - elapsed_since_last
        logger.debug("Pacing LLM call: pausing %.2fs to keep strictly within free tier RPM limits...", sleep_needed)
        time.sleep(sleep_needed)

    # 5. Invoke Gemini with candidate models and automatic fallback on quota exhaustion
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

        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config if json_mode else None
            )

            for attempt in range(max_retries):
                try:
                    _last_live_call_timestamp = time.time()
                    response = model.generate_content(prompt)
                    text = (response.text or "").strip()

                    # Clean markdown formatting in JSON mode
                    if json_mode:
                        if text.startswith("```json"):
                            text = text[7:]
                        elif text.startswith("```"):
                            text = text[3:]
                        if text.endswith("```"):
                            text = text[:-3]
                        text = text.strip()

                    # Record estimated token consumption to SQLite
                    p_tokens = _estimate_tokens(prompt)
                    c_tokens = _estimate_tokens(text)
                    record_llm_usage(prompt_tokens=p_tokens, completion_tokens=c_tokens)

                    # Cache successful response so it is NEVER called again
                    set_cached_llm_response(prompt_hash, text)
                    log_event("llm", f"Generated content ({p_tokens + c_tokens} est. tokens) via model '{model_name}'")
                    return text

                except (exceptions.ResourceExhausted, exceptions.TooManyRequests) as e:
                    last_error = e
                    logger.warning("Gemini 429 quota on '%s'. Trying next candidate model...", model_name)
                    break  # Break inner retry loop to try next candidate model

                except Exception as e:
                    logger.error("LLM call failed with '%s': %s", model_name, e)
                    last_error = e
                    break

        except Exception as e:
            last_error = e
            continue

    # Fail-fast if live generation failed across all models
    log_event("llm", f"LLM generation failed after retries: {last_error}", level="ERROR")
    logger.error("LLM generation failed across all candidate models: %s", last_error)
    raise RuntimeError(f"Gemini LLM generation failed across all candidate models: {last_error}")
