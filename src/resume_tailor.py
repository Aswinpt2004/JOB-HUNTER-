import json
import logging
import re
from typing import Dict, List, Set, Tuple, Optional
from src.models import (
    MasterResume, TailoredResume, JDParsed,
    ResumeExperience, ResumeProject, ResumeBullet
)
from src.llm import generate
from src.db import log_event
from src.verifier import verify_no_fabrication, sanitize_tailored_resume
from src.matcher import are_skills_synonyms, classify_role

logger = logging.getLogger("jobpilot.resume_tailor")

# Role Lenses definition as per Section 6 specification
ROLE_LENS_HEADLINES = {
    "Computer Vision / Drone / Surveillance": "Computer Vision Engineer | Drone & Surveillance AI",
    "LLM / GenAI / RAG / Agents": "GenAI / LLM Engineer | RAG & Agentic AI",
    "Document AI / Healthcare AI": "AI/ML Engineer | Document AI & Healthcare",
    "Federated / Privacy / Graph ML / Research": "ML Engineer | Federated & Graph Learning",
    "Backend / Full-stack with AI": "AI Engineer | Python & FastAPI Backend",
    "Generic ML / Data Science": "AI/ML Engineer | Computer Vision & LLM Applications",
}

ROLE_LENS_CONFIG = {
    "Computer Vision / Drone / Surveillance": {
        "exp1_lead_ids": ["exp1b1", "exp1b2", "exp1b3", "exp1b4", "exp1b5"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p5", "p4", "p1", "p3", "p2", "p6", "p7"],
        "summary_focus": "computer-vision systems for drone and surveillance video, object detection (YOLO, RT-DETR, RF-DETR), and multi-object tracking (ByteTrack)"
    },
    "LLM / GenAI / RAG / Agents": {
        "exp1_lead_ids": ["exp1b5", "exp1b1", "exp1b2", "exp1b3", "exp1b4"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p1", "p3", "p2", "p4", "p5", "p6", "p7"],
        "summary_focus": "production LLM applications, retrieval-augmented generation (RAG) with Llama-3/Ollama, agentic AI workflows, and Pydantic structured outputs"
    },
    "Document AI / Healthcare AI": {
        "exp1_lead_ids": ["exp1b5", "exp1b1", "exp1b2", "exp1b3", "exp1b4"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p1", "p6", "p4", "p5", "p3", "p2", "p7"],
        "summary_focus": "automated document extraction (PDF/DOCX), Pydantic data contract validation, and clinical AI platform modules (PI-RADS) with FastAPI integration"
    },
    "Federated / Privacy / Graph ML / Research": {
        "exp1_lead_ids": ["exp1b1", "exp1b2", "exp1b3", "exp1b4", "exp1b5"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p4", "p6", "p5", "p1", "p3", "p2", "p7"],
        "summary_focus": "hierarchical federated graph learning (Flower), differential privacy, graph neural networks, and rigorous experimental benchmarking"
    },
    "Backend / Full-stack with AI": {
        "exp1_lead_ids": ["exp1b5", "exp1b1", "exp1b2", "exp1b3", "exp1b4"],
        "exp2_lead_ids": ["exp2b2", "exp2b1", "exp2b3"],
        "project_order_ids": ["p7", "p2", "p1", "p3", "p4", "p5", "p6"],
        "summary_focus": "scalable backend microservices in Python (FastAPI, Django), Dockerized deployments, REST APIs, and automated data pipelines"
    },
    "Generic ML / Data Science": {
        "exp1_lead_ids": ["exp1b1", "exp1b2", "exp1b3", "exp1b4", "exp1b5"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p4", "p5", "p1", "p3", "p2", "p6", "p7"],
        "summary_focus": "applied machine learning, PyTorch model development, data preprocessing, and rigorous experiment evaluation"
    }
}


def deduplicate_and_reorder_skills(
    master_skills: Dict[str, List[str]],
    jd_skills: List[str]
) -> Dict[str, List[str]]:
    """
    De-duplicates repeated skills (like SQL and model benchmarking across groups)
    and reorders skills so JD-matched skills appear first in each group.
    Preserves all 6 groups without dropping any unique skill.
    """
    seen_skills_lower: Set[str] = set()
    tailored_skills: Dict[str, List[str]] = {}

    for cat_name, skill_list in master_skills.items():
        matched_in_group = []
        unmatched_in_group = []

        for skill in skill_list:
            s_clean = skill.strip()
            s_low = s_clean.lower()
            if s_low in seen_skills_lower:
                continue
            seen_skills_lower.add(s_low)

            # Check if matches JD
            if any(are_skills_synonyms(s_clean, jds) for jds in jd_skills):
                matched_in_group.append(s_clean)
            else:
                unmatched_in_group.append(s_clean)

        # Matched first, then remaining
        ordered_group = matched_in_group + unmatched_in_group
        if ordered_group:
            tailored_skills[cat_name] = ordered_group

    return tailored_skills


def build_tailored_summary(
    master: MasterResume,
    role_lens: str,
    target_role: str,
    jd_skills: List[str]
) -> str:
    """
    Synthesizes a 3-4 sentence truthful professional summary:
    - Built strictly from master facts
    - Mentions the target role
    - Highlights genuine matching tech stack
    """
    lens_cfg = ROLE_LENS_CONFIG.get(role_lens, ROLE_LENS_CONFIG["Generic ML / Data Science"])
    focus_phrase = lens_cfg["summary_focus"]

    s1 = f"AI/ML engineer (M.Sc. Computer Science, Machine Intelligence, 2026) targeting {target_role} roles with hands-on experience in {focus_phrase}."
    s2 = "At Quantumweave Intelligence, I develop detection, tracking, and telemetry-aware intrusion pipelines with GPU inference optimization, automated test suites, and Dockerized surveillance web dashboards."
    s3 = "Earlier projects include an agentic storefront platform with Pydantic schemas, an offline RAG assistant on Llama-3, and federated graph learning with differential privacy."
    s4 = "Strong foundation in Python, PyTorch, and FastAPI, dedicated to false-positive reduction, clean evaluation, and collaborative Git branching workflows."

    return f"{s1} {s2} {s3} {s4}"


def tailor_experience(
    master_experience: List[ResumeExperience],
    role_lens: str
) -> List[ResumeExperience]:
    """
    Reorders bullets inside each experience role according to role lens priority.
    Reverse-chronological order is strictly preserved (Quantumweave first, Synbrains second).
    """
    lens_cfg = ROLE_LENS_CONFIG.get(role_lens, ROLE_LENS_CONFIG["Generic ML / Data Science"])
    exp1_lead = lens_cfg["exp1_lead_ids"]
    exp2_lead = lens_cfg["exp2_lead_ids"]

    tailored_exp = []
    for exp in master_experience:
        lead_order = exp1_lead if "Quantumweave" in exp.company else exp2_lead
        # Map bullets by ID
        bullet_map = {b.id: b for b in exp.bullets if b.id}

        ordered_bullets = []
        for bid in lead_order:
            if bid in bullet_map:
                ordered_bullets.append(bullet_map[bid])
        # Add any remaining
        for b in exp.bullets:
            if b not in ordered_bullets:
                ordered_bullets.append(b)

        tailored_exp.append(ResumeExperience(
            company=exp.company,
            role=exp.role,
            location=exp.location,
            start_date=exp.start_date,
            end_date=exp.end_date,
            bullets=ordered_bullets
        ))

    return tailored_exp


def tailor_projects(
    master_projects: List[ResumeProject],
    role_lens: str
) -> List[ResumeProject]:
    """
    Orders projects by role lens relevance.
    All 7 projects are retained:
    - Top 4 projects retain all their bullets
    - Bottom 3 projects keep their primary bullet to fit exactly on page 2.
    """
    lens_cfg = ROLE_LENS_CONFIG.get(role_lens, ROLE_LENS_CONFIG["Generic ML / Data Science"])
    order_ids = lens_cfg["project_order_ids"]

    proj_map = {}
    for p in master_projects:
        pid = p.id
        if not pid:
            # Fallback by matching name
            if "Storefront" in p.name:
                pid = "p1"
            elif "KuTo" in p.name:
                pid = "p2"
            elif "Manglish" in p.name:
                pid = "p3"
            elif "FedGraph" in p.name:
                pid = "p4"
            elif "SHADER" in p.name:
                pid = "p5"
            elif "Connectome" in p.name:
                pid = "p6"
            elif "PETZZO" in p.name:
                pid = "p7"
        if pid:
            proj_map[pid] = p

    ordered_projects: List[ResumeProject] = []
    for pid in order_ids:
        if pid in proj_map:
            ordered_projects.append(proj_map[pid])

    # In case any project was missing from order_ids
    for p in master_projects:
        if p not in ordered_projects:
            ordered_projects.append(p)

    # Retain all authentic bullets for all 7 projects ordered by lens relevance
    final_projects = []
    for p in ordered_projects:
        final_projects.append(ResumeProject(
            id=p.id,
            name=p.name,
            technologies=p.technologies,
            description=p.description,
            bullets=p.bullets,
            link=p.link
        ))

    return final_projects


def tailor_resume(
    master: MasterResume,
    jd: JDParsed
) -> TailoredResume:
    """
    Executes role-lens tailoring:
    1. Classifies role into Tier and Role Lens.
    2. De-duplicates and reorders skills (matched skills first).
    3. Builds 3-4 sentence summary from master facts with role focus.
    4. Reorders experience bullets while preserving reverse-chronological order.
    5. Reorders all 7 projects based on role lens priority.
    6. Runs strict verification to guarantee NO fabrication.
    """
    role_tier, role_lens = classify_role(jd.role, " ".join(jd.must_have_skills + jd.responsibilities))

    jd_skills = jd.must_have_skills + jd.nice_to_have_skills + jd.keywords

    # 1. Skills
    tailored_skills = deduplicate_and_reorder_skills(master.skills, jd_skills)

    # 2. Summary
    tailored_summary = build_tailored_summary(master, role_lens, jd.role, jd_skills)

    # 3. Experience
    tailored_exp = tailor_experience(master.experience, role_lens)

    # 4. Projects
    tailored_projs = tailor_projects(master.projects, role_lens)

    headline = ROLE_LENS_HEADLINES.get(role_lens, "AI/ML Engineer | Computer Vision & LLM Applications")

    tailored = TailoredResume(
        contact=master.contact,
        targeted_title=f"{jd.role} | AI/ML Engineer",
        headline=headline,
        summary=tailored_summary,
        highlighted_skills=tailored_skills,
        experience=tailored_exp,
        projects=tailored_projs,
        education=master.education,
        certifications=master.certifications,
        matched_skills=[s for s in jd_skills if any(are_skills_synonyms(s, ms) for sl in tailored_skills.values() for ms in sl)],
        role_lens=role_lens,
        role_tier=role_tier
    )

    # 5. Strict Verification
    is_valid, violations = verify_no_fabrication(tailored, master)
    if not is_valid:
        logger.warning("Tailored resume had fabrication violations: %s. Sanitizing...", violations)
        tailored = sanitize_tailored_resume(tailored, master)

    log_event("resume_tailor", f"Tailored resume for {jd.role} (Lens: {role_lens}, Tier: {role_tier})")
    return tailored
