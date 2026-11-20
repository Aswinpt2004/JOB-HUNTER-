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


def _mock_generate(prompt: str, json_mode: bool = False) -> str:
    """Deterministic fallback mock generator for offline testing, missing keys, or budget ceiling.
    Dynamically derives data from master resume and config, with zero hardcoded personal data."""
    logger.info("Using mock/cached fallback generator.")
    prompt_lower = prompt.lower()

    # Dynamically read master resume if present
    master_info = {}
    try:
        if settings.master_resume_path and settings.master_resume_path.exists():
            with open(settings.master_resume_path, "r", encoding="utf-8") as f:
                master_info = json.load(f)
    except Exception:
        master_info = {}

    contact = master_info.get("contact", {})
    candidate_name = contact.get("name") or settings.candidate_name or "Candidate"
    candidate_phone = contact.get("phone") or ""
    candidate_location = contact.get("location") or "Remote"
    candidate_summary = master_info.get("summary") or "Experienced engineer with a strong track record of delivering high-quality software."

    # Extract real skills if present
    skills_dict = master_info.get("skills", {})
    all_skills = []
    for s_list in skills_dict.values():
        all_skills.extend(s_list)
    top_skills = all_skills[:6] if all_skills else ["Python", "Problem Solving", "Software Engineering"]

    # Extract first real experience bullets
    experiences = master_info.get("experience", [])
    bullets_by_company = {}
    if experiences:
        first_exp = experiences[0]
        company = first_exp.get("company", "Engineering Team")
        bullets_by_company[company] = first_exp.get("bullets", ["Contributed to software development and system architecture."])[:2]
    else:
        bullets_by_company["Engineering Team"] = ["Contributed to software development and system architecture."]

    target_title = settings.target_roles[0] if settings.target_roles else "Software Engineer"

    if json_mode:
        if "must_have_skills" in prompt_lower or "jd parsing" in prompt_lower or "seniority" in prompt_lower:
            return json.dumps({
                "role": target_title,
                "seniority": settings.user_profile.get("experience_level", "Mid-Level"),
                "must_have_skills": top_skills[:4],
                "nice_to_have_skills": top_skills[4:8] if len(top_skills) > 4 else ["Git", "Docker"],
                "keywords": top_skills,
                "responsibilities": [
                    "Design, implement, and maintain software modules and services",
                    "Collaborate with cross-functional teams to deliver production features",
                    "Participate in code reviews and engineering discussions"
                ],
                "location": candidate_location,
                "application_instructions": "Submit application via career portal or email"
            }, indent=2)

        if "match_score" in prompt_lower or "matcher" in prompt_lower:
            return json.dumps({
                "match_score": 80.0,
                "matched_skills": top_skills[:4],
                "missing_skills": [],
                "rationale": f"Candidate profile aligns with core required skills ({', '.join(top_skills[:3])})."
            }, indent=2)

        if "tailored" in prompt_lower or "tailored_title" in prompt_lower:
            return json.dumps({
                "targeted_title": target_title,
                "summary": candidate_summary,
                "highlighted_skills": skills_dict if skills_dict else {"Core Skills": top_skills},
                "selected_bullets_by_company": bullets_by_company
            }, indent=2)

        return json.dumps({"status": "success", "message": "Deterministic fallback response"})

    # Non-json text responses (e.g. Email generation)
    if "email" in prompt_lower or "cover" in prompt_lower:
        signoff = f"Best regards,\n{candidate_name}"
        if candidate_phone:
            signoff += f"\n{candidate_phone}"
        return (
            "Hi Hiring Team,\n\n"
            "I noticed your opening and wanted to reach out directly. "
            f"With hands-on experience in {', '.join(top_skills[:3])}, "
            "I have built scalable solutions that deliver measurable impact.\n\n"
            "I have attached my resume for your review and would welcome the chance to discuss how my background aligns with your team's goals.\n\n"
            "If this isn't the right contact, let me know and I won't follow up.\n\n"
            f"{signoff}"
        )

    return "Deterministic fallback response."


def generate(prompt: str, json_mode: bool = False, max_retries: int = 2, backoff_base: float = 2.0) -> str:
    """
    Single unified function for all LLM calls with strict anti-waste guardrails:
    1. Caches responses by SHA-256 hash in SQLite (never calls LLM twice for same prompt).
    2. Enforces daily request and token budgets from config.yaml to prevent quota exhaustion.
    3. Paces requests with a minimum 4.0s pause between calls (guarantees strictly under 15 RPM).
    4. Truncates overly long prompt input text to eliminate wasted tokens.
    5. Tracks daily token consumption in SQLite for full visibility.
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

    # Guardrail 2: Check API Key presence
    api_key = settings.gemini_api_key.strip()
    if not api_key or api_key.startswith("your_"):
        response_text = _mock_generate(prompt, json_mode=json_mode)
        set_cached_llm_response(prompt_hash, response_text)
        return response_text

    # Guardrail 3: Check Daily Token & Request Quota
    usage = get_today_llm_usage()
    if usage["request_count"] >= settings.llm_max_requests_per_day:
        msg = f"[QUOTA GUARD] Daily request limit ({settings.llm_max_requests_per_day}) reached for today. Switching to fallback to preserve free tier."
        logger.warning(msg)
        log_event("llm_guard", msg, level="WARNING")
        fallback = _mock_generate(prompt, json_mode=json_mode)
        set_cached_llm_response(prompt_hash, fallback)
        return fallback

    if usage["total_tokens"] >= settings.llm_max_tokens_per_day:
        msg = f"[QUOTA GUARD] Daily token ceiling ({settings.llm_max_tokens_per_day}) reached for today. Switching to fallback to preserve free tier."
        logger.warning(msg)
        log_event("llm_guard", msg, level="WARNING")
        fallback = _mock_generate(prompt, json_mode=json_mode)
        set_cached_llm_response(prompt_hash, fallback)
        return fallback

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
    for m in [primary_model, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.7-flash"]:
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

    # Fallback if live call failed
    log_event("llm", f"LLM generation failed after retries: {last_error}", level="ERROR")
    logger.warning("Falling back to deterministic mock generator.")
    fallback = _mock_generate(prompt, json_mode=json_mode)
    set_cached_llm_response(prompt_hash, fallback)
    return fallback
