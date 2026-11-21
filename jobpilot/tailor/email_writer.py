import logging
import re
from typing import Optional, Tuple, Dict, Any
from jinja2 import Template
from jobpilot.core.config import settings
from jobpilot.core.models import TailoredResume, Job
from jobpilot.core.llm import generate
from jobpilot.core.db import log_event

logger = logging.getLogger("jobpilot.tailor.email_writer")

MANDATORY_OPTOUT = "If this isn't the right contact, let me know and I won't follow up."

BANNED_PHRASES = [
    r'brief\s+(?:10-?minute\s+)?conversation',
    r'quick\s+(?:10-?minute\s+)?call',
    r'open\s+to\s+a\s+(?:brief|quick)\s+conversation',
    r'discuss\s+how\s+my\s+(?:technical\s+)?skill\s*set',
    r'discuss\s+(?:team|your)\s+roadmap',
    r'over\s+the\s+past\s+few\s+years',
    r'seasoned\s+engineer',
    r'proven\s+track\s+record',
    r'ideal\s+candidate',
    r'synergies?',
    r'\b[1-9]\s*years\s+of\s+experience\b'
]

ROLE_LENS_HOOKS = {
    "Computer Vision / Drone / Aerial Perception": (
        "At Quantumweave Intelligence I build detection, tracking, and intrusion-analytics pipelines "
        "for drone and surveillance video, focusing on reducing false positives."
    ),
    "LLM Applications / RAG / Agentic AI": (
        "I built an offline Malayalam-English RAG chatbot on Llama-3 with Ollama, and an agentic storefront generator "
        "that produces structured outputs with Pydantic."
    ),
    "Document AI / OCR / Information Extraction": (
        "During my internship at Synbrains I built a pipeline converting PDF/DOCX medical reports into validated schemas, "
        "and contributed FastAPI modules to a clinical reporting platform."
    ),
    "Federated Learning / Graph Neural Networks": (
        "I designed FedGraph-Shield, a hierarchical federated graph learning framework with differential privacy for fraud detection."
    ),
    "Python Backend / FastAPI / Scalable Systems": (
        "I have built asynchronous FastAPI and Django services and Docker-deployed dashboards."
    ),
    "Generic ML / Data Science": (
        "At Quantumweave Intelligence and through my M.Sc. research, I have developed machine learning models and computer-vision pipelines with PyTorch."
    )
}


def score_email_tone(body: str) -> Dict[str, Any]:
    clean_body = re.sub(r'https?://\S+', '', body)
    words = clean_body.split()
    word_count = len(words)

    penalties = 0.0
    detected_banned = []
    for pat in BANNED_PHRASES:
        if re.search(pat, body, re.IGNORECASE):
            detected_banned.append(pat)
            penalties += 2.0

    if word_count < 70:
        penalties += 2.0
    elif word_count > 175:
        penalties += 2.5

    if MANDATORY_OPTOUT.lower() not in body.lower():
        penalties += 3.0

    final_score = max(0.0, 10.0 - penalties)
    return {
        "score": round(final_score, 1),
        "word_count": word_count,
        "penalties": penalties,
        "banned_phrases": detected_banned,
        "has_optout": MANDATORY_OPTOUT.lower() in body.lower()
    }


def generate_tailored_email(
    job: Job,
    tailored: TailoredResume,
    recipient_name: Optional[str] = None
) -> Tuple[str, str, float]:
    """Generates humble, concrete cold email."""
    lens = tailored.lens or "Generic ML / Data Science"
    hook = ROLE_LENS_HOOKS.get(lens, ROLE_LENS_HOOKS["Generic ML / Data Science"])

    greeting = f"Hi {recipient_name.split()[0]}," if recipient_name and recipient_name.strip() else "Hi Hiring Team,"
    target_role = job.title or "AI/ML Engineer"
    comp = job.company or "your team"

    subject = f"Aswin P T — Application for {target_role} ({comp})"

    body = (
        f"{greeting}\n\n"
        f"I came across the {target_role} opening at {comp} and wanted to reach out directly. "
        f"I am completing my M.Sc. in Computer Science (Machine Intelligence) and am available to join immediately.\n\n"
        f"{hook}\n\n"
        f"I have attached my 2-page resume covering these projects and technical stack. "
        f"I am open to on-site work in {job.location} or remote.\n\n"
        f"{MANDATORY_OPTOUT}\n\n"
        f"Best regards,\n"
        f"Aswin P T\n"
        f"+91 88913 81713\n"
        f"Portfolio: https://codedbyaswinpt.vercel.app/\n"
        f"GitHub: https://github.com/Aswinpt2004"
    )

    tone = score_email_tone(body)
    return subject, body, tone["score"]

