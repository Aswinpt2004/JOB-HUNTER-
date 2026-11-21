import re
from typing import Dict, Any, Optional
from jobpilot.core.config import settings


def generate_cover_note(
    job_title: str,
    company: str,
    role_lens: str,
    matched_skills: list[str],
    location: str = "Bangalore"
) -> str:
    """
    Generates a concise 60-100 word high-impact cover note for ATS text boxes,
    LinkedIn InMail, and candidate portals.
    Follows strict anti-hype standards: humble, concrete, and factually grounded.
    """
    skills_preview = ", ".join(matched_skills[:3]) if matched_skills else "Python, Computer Vision, and LLM applications"

    if "Computer Vision" in role_lens or "Drone" in role_lens:
        focus_sentence = (
            f"I have built production-grade aerial object detection and tracking pipelines "
            f"using YOLOv8, RT-DETR, and ByteTrack, achieving 94.6% mAP50."
        )
    elif "LLM" in role_lens or "RAG" in role_lens:
        focus_sentence = (
            f"I have engineered local RAG and agentic workflows using Ollama, Llama-3, "
            f"and FastAPI with schema-enforced Pydantic contracts."
        )
    elif "Backend" in role_lens:
        focus_sentence = (
            f"I specialize in architecting asynchronous Python backend services using FastAPI, "
            f"PostgreSQL, and Docker with automated validation."
        )
    else:
        focus_sentence = (
            f"My technical background centers on practical machine learning pipelines in Python, "
            f"focusing on {skills_preview}."
        )

    note = (
        f"Hi Hiring Team,\n\n"
        f"I am writing to express my strong interest in the {job_title} role at {company}. "
        f"As an M.Sc. Computer Science graduate specializing in Machine Intelligence, {focus_sentence} "
        f"I am available to join immediately and fully prepared to work on-site in {location} or remotely. "
        f"I would welcome the opportunity to discuss how my hands-on technical skills can contribute to {company}'s engineering goals.\n\n"
        f"Best regards,\n"
        f"Aswin P T\n"
        f"+91 88913 81713 | aswinpt2004@gmail.com"
    )

    return note.strip()


def check_cover_note_tone(text: str) -> float:
    """Calculates tone penalty score (10.0 is perfect, subtracts for corporate fluff/buzzwords)."""
    score = 10.0
    banned_words = [
        "synergy", "rockstar", "ninja", "game-changer", "paradigm",
        "revolutionary", "world-class", "guru", "unmatched", "passionate visionary"
    ]
    t_lower = text.lower()
    for w in banned_words:
        if w in t_lower:
            score -= 2.0
    words = text.split()
    if len(words) > 150:
        score -= 2.0  # Penalize verbosity
    return max(0.0, score)

