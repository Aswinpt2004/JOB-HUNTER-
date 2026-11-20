import json
import logging
import re
from typing import Optional, Tuple, Dict, Any
from jinja2 import Template
from src.config import settings
from src.models import MasterResume, TailoredResume, Job, JDParsed
from src.llm import generate
from src.db import log_event
from src.matcher import classify_role

logger = logging.getLogger("jobpilot.email_writer")

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

# Section 7: Hook per Role Lens
ROLE_LENS_HOOKS = {
    "Computer Vision / Drone / Surveillance": (
        "At Quantumweave Intelligence I currently build detection, tracking, and intrusion-analytics pipelines "
        "for drone and surveillance video, focusing on reducing false positives."
    ),
    "LLM / GenAI / RAG / Agents": (
        "I built an offline Malayalam-English RAG chatbot on Llama-3 with Ollama, and an agentic storefront generator "
        "that produces structured outputs with Pydantic."
    ),
    "Document AI / Healthcare AI": (
        "During my internship at Synbrains I built a pipeline that converts PDF/DOCX medical reports into validated schemas, "
        "and contributed FastAPI modules to a clinical reporting platform."
    ),
    "Federated / Privacy / Graph ML / Research": (
        "I designed FedGraph-Shield, a hierarchical federated graph learning framework with differential privacy for fraud detection."
    ),
    "Backend / Full-stack with AI": (
        "I have built FastAPI and Django services and Docker-deployed dashboards."
    ),
    "Generic ML / Data Science": (
        "At Quantumweave Intelligence and through my M.Sc. research, I have developed machine learning models and computer-vision pipelines with PyTorch."
    )
}


def score_email_tone(body: str) -> Dict[str, Any]:
    """Evaluates tone, word count, humility, and banned sales phrases."""
    clean_body = re.sub(r'https?://\S+', '', body)
    words = clean_body.split()
    word_count = len(words)

    penalties = 0.0
    detected_banned = []
    for pat in BANNED_PHRASES:
        if re.search(pat, body, re.IGNORECASE):
            detected_banned.append(pat)
            penalties += 2.0

    # Word count penalty (ideal: 90 - 150 words)
    if word_count < 80:
        penalties += 1.5
    elif word_count > 160:
        penalties += 1.5

    # Check for humble call to action
    has_humble_cta = bool(re.search(
        r'(?:grateful|welcome\s+the\s+opportunity|appreciate\s+your\s+consideration|chance\s+to\s+interview|technical\s+assessment)',
        body,
        re.IGNORECASE
    ))
    if not has_humble_cta:
        penalties += 1.5

    # Check opt-out
    has_optout = MANDATORY_OPTOUT.lower() in body.lower()
    if not has_optout:
        penalties += 3.0

    tone_score = max(0.0, min(10.0, 10.0 - penalties))
    return {
        "score": tone_score,
        "word_count": word_count,
        "banned_phrases": detected_banned,
        "has_optout": has_optout,
        "has_humble_cta": has_humble_cta
    }


def build_polite_fallback(
    job: Job,
    jd_parsed: JDParsed,
    master: MasterResume,
    recruiter_name: Optional[str] = None,
    role_lens: Optional[str] = None
) -> Tuple[str, str]:
    """Generates a guaranteed humble, polite, and ATS-compliant outreach email based on role lens."""
    greeting = f"Hi {recruiter_name}," if recruiter_name else f"Hi {job.company} Team,"
    role = jd_parsed.role or job.title
    subject = f"Application: {role} - {master.contact.name}"

    if not role_lens:
        _, role_lens = classify_role(role, " ".join(jd_parsed.must_have_skills + jd_parsed.responsibilities))

    hook = ROLE_LENS_HOOKS.get(role_lens, ROLE_LENS_HOOKS["Generic ML / Data Science"])

    body = (
        f"{greeting}\n\n"
        f"I am writing to express my interest in the {role} position at {job.company}. "
        f"As a recent M.Sc. graduate in Machine Intelligence with hands-on experience from a research assistant role and an internship, {hook}\n\n"
        f"I am eager to contribute to your engineering team with clean code, strong evaluation discipline, and enthusiasm. "
        f"I have attached my tailored resume as a PDF for your review.\n\n"
        f"If my background looks like a good match, I would be grateful for the chance to interview or complete a technical assessment.\n\n"
        f"{MANDATORY_OPTOUT}\n\n"
        f"Best regards,\n"
        f"{master.contact.name}\n"
        f"{master.contact.phone}\n"
        f"GitHub: {master.contact.github} | LinkedIn: {master.contact.linkedin} | Portfolio: {master.contact.portfolio}"
    )
    return subject, body


def generate_application_email(
    job: Job,
    jd_parsed: JDParsed,
    tailored_resume: TailoredResume,
    master_resume: MasterResume,
    recruiter_name: Optional[str] = None
) -> Tuple[str, str]:
    """
    Generates a tailored, humble, 90-140 word outreach email for early-career AI/ML engineer.
    Returns (subject, body).
    """
    role_lens = getattr(tailored_resume, "role_lens", None)
    default_subject, default_body = build_polite_fallback(
        job=job,
        jd_parsed=jd_parsed,
        master=master_resume,
        recruiter_name=recruiter_name,
        role_lens=role_lens
    )

    template_path = settings.templates_dir / "email_prompt.txt"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            prompt_template_str = f.read()
    except Exception:
        return default_subject, default_body

    template = Template(prompt_template_str)

    links = []
    if master_resume.contact.github:
        links.append(f"GitHub: {master_resume.contact.github}")
    if master_resume.contact.linkedin:
        links.append(f"LinkedIn: {master_resume.contact.linkedin}")
    if master_resume.contact.portfolio:
        links.append(f"Portfolio: {master_resume.contact.portfolio}")

    hook = ROLE_LENS_HOOKS.get(role_lens, ROLE_LENS_HOOKS["Generic ML / Data Science"])

    rendered_prompt = template.render(
        candidate_name=master_resume.contact.name,
        candidate_email=master_resume.contact.email,
        candidate_phone=master_resume.contact.phone,
        candidate_links=" | ".join(links),
        candidate_projects_and_skills=f"Key experience hook: {hook}. Summary: {tailored_resume.summary}",
        company=job.company,
        role=jd_parsed.role,
        recruiter_name=recruiter_name,
        jd_requirements=", ".join(jd_parsed.must_have_skills[:6])
    )

    try:
        raw_res = generate(rendered_prompt, json_mode=True)
        data = json.loads(raw_res)
        subject = data.get("subject", "").strip() or default_subject
        body = data.get("body", "").strip() or default_body

        # Guarantee mandatory opt-out is in the body
        if MANDATORY_OPTOUT not in body:
            if "Best regards" in body:
                parts = body.split("Best regards")
                body = parts[0].rstrip() + f"\n\n{MANDATORY_OPTOUT}\n\nBest regards" + parts[1]
            elif "Sincerely" in body:
                parts = body.split("Sincerely")
                body = parts[0].rstrip() + f"\n\n{MANDATORY_OPTOUT}\n\nSincerely" + parts[1]
            else:
                body = body.rstrip() + f"\n\n{MANDATORY_OPTOUT}"

        # Clean any accidental pushy lines from LLM
        for banned in BANNED_PHRASES:
            if re.search(banned, body, re.IGNORECASE):
                body = re.sub(
                    banned,
                    "grateful for the chance to interview or discuss how my skills fit your team",
                    body,
                    flags=re.IGNORECASE
                )

        # Evaluate tone
        metrics = score_email_tone(body)
        if metrics["score"] < 6.5:
            logger.info("Generated email tone score (%.1f) below target. Using polite fallback template.", metrics["score"])
            return default_subject, default_body

        log_event("email_writer", f"Drafted email for {job.company} ({jd_parsed.role}), Tone: {metrics['score']:.1f}/10")
        return subject, body

    except Exception as e:
        logger.warning("Email writing exception, using polite fallback: %s", e)
        return default_subject, default_body
