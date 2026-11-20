import json
import logging
from typing import Optional
from pydantic import ValidationError
from src.llm import generate
from src.models import JDParsed
from src.db import log_event
from src.config import settings

logger = logging.getLogger("jobpilot.jd_parser")


def parse_job_description(jd_text: str, max_retries: int = 1) -> Optional[JDParsed]:
    """
    Parses raw Job Description text into structured JDParsed model using LLM JSON mode.
    Retries once on malformed JSON or validation errors.
    """
    if not jd_text or len(jd_text.strip()) < 20:
        logger.warning("Job description too short to parse meaningfully.")
        return None

    # Truncate overly long JDs to avoid burning free-tier token quota on company disclaimers
    clean_jd = jd_text.strip()
    max_len = settings.llm_max_input_characters
    if len(clean_jd) > max_len:
        clean_jd = clean_jd[:max_len] + "\n[...trimmed remainder to conserve tokens...]"

    prompt = f"""You are an expert technical recruiter and resume strategist.
Analyze the following Job Description (JD) and extract structured data in JSON format.

Strict requirements:
1. role: Exact target job title.
2. seniority: Experience tier (e.g., 'Intern', 'Entry / Fresher', 'Mid-Level', 'Senior', 'Lead').
3. must_have_skills: Array of essential, required technical skills, languages, or frameworks mentioned.
4. nice_to_have_skills: Array of preferred/optional skills or qualifications.
5. keywords: Array of high-value ATS domain keywords (e.g. 'REST API', 'CI/CD', 'ETL').
6. responsibilities: 2 to 4 key primary responsibilities.
7. location: Specified location or 'Remote'.
8. application_instructions: Any explicit instructions for applying (e.g. 'Email resume to X with subject Y' or null).

Return ONLY a valid JSON object matching this schema.

Job Description:
{clean_jd}
"""

    for attempt in range(max_retries + 1):
        try:
            raw_response = generate(prompt, json_mode=True)
            # Try parsing JSON
            data = json.loads(raw_response)
            parsed = JDParsed.model_validate(data)
            log_event("jd_parser", f"Successfully parsed JD for role '{parsed.role}'")
            return parsed
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("JD parsing validation failure (attempt %d/%d): %s", attempt + 1, max_retries + 1, e)
            if attempt < max_retries:
                # Add corrective instruction to prompt
                prompt += f"\n\nPrevious response failed validation with error: {e}. Provide STRICT valid JSON only."

    # Fallback heuristic parser if LLM fails completely
    logger.warning("Falling back to basic rule-based JD parsing.")
    return _rule_based_fallback(jd_text)


def _rule_based_fallback(jd_text: str) -> JDParsed:
    """Simple heuristic fallback if LLM JSON parsing fails."""
    lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
    role = lines[0][:60] if lines else "Software Engineer"

    must_have = []
    common_skills = ["Python", "SQL", "FastAPI", "Django", "Docker", "Git", "PostgreSQL", "AWS", "REST"]
    for skill in common_skills:
        if skill.lower() in jd_text.lower():
            must_have.append(skill)

    return JDParsed(
        role=role,
        seniority="Mid-Level",
        must_have_skills=must_have or ["Python"],
        nice_to_have_skills=[],
        keywords=["Software Development", "API", "Database"],
        responsibilities=["Develop and maintain backend services."],
        location="Remote",
        application_instructions=None
    )

