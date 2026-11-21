import json
import logging
import re
from typing import Dict, List, Set, Tuple, Optional, Any
from pathlib import Path
from jobpilot.core.config import settings
from jobpilot.core.models import (
    TailoredResume, ResumeExperienceItem, ResumeProjectItem,
    ResumeEducationItem, ResumeContactInfo, ResumeBullet, Job
)
from jobpilot.core.db import log_event
from jobpilot.tailor.verifier import verify_no_fabrication, sanitize_tailored_resume
from jobpilot.pipeline.match import are_skills_equivalent, classify_role_tier_and_lens

logger = logging.getLogger("jobpilot.tailor.resume_tailor")

ROLE_LENS_HEADLINES = {
    "Computer Vision / Drone / Aerial Perception": "Computer Vision Engineer | Drone & Surveillance AI",
    "LLM Applications / RAG / Agentic AI": "GenAI / LLM Engineer | RAG & Agentic AI",
    "Document AI / OCR / Information Extraction": "AI/ML Engineer | Document AI & Healthcare",
    "Federated Learning / Graph Neural Networks": "ML Engineer | Federated & Graph Learning",
    "Python Backend / FastAPI / Scalable Systems": "AI Engineer | Python & FastAPI Backend",
    "Generic ML / Data Science": "AI/ML Engineer | Computer Vision & LLM Applications",
}

ROLE_LENS_CONFIG = {
    "Computer Vision / Drone / Aerial Perception": {
        "exp1_lead_ids": ["exp1b1", "exp1b2", "exp1b3", "exp1b4", "exp1b5"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p5", "p4", "p1", "p3", "p2", "p6", "p7"],
        "summary_focus": "computer-vision systems for drone and surveillance video, object detection (YOLO, RT-DETR, RF-DETR), and multi-object tracking (ByteTrack)"
    },
    "LLM Applications / RAG / Agentic AI": {
        "exp1_lead_ids": ["exp1b5", "exp1b1", "exp1b2", "exp1b3", "exp1b4"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p1", "p3", "p2", "p4", "p5", "p6", "p7"],
        "summary_focus": "production LLM applications, retrieval-augmented generation (RAG) with Llama-3/Ollama, agentic AI workflows, and Pydantic structured outputs"
    },
    "Document AI / OCR / Information Extraction": {
        "exp1_lead_ids": ["exp1b5", "exp1b1", "exp1b2", "exp1b3", "exp1b4"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p1", "p6", "p4", "p5", "p3", "p2", "p7"],
        "summary_focus": "automated document extraction (PDF/DOCX), Pydantic data contract validation, and clinical AI platform modules with FastAPI integration"
    },
    "Federated Learning / Graph Neural Networks": {
        "exp1_lead_ids": ["exp1b1", "exp1b2", "exp1b3", "exp1b4", "exp1b5"],
        "exp2_lead_ids": ["exp2b1", "exp2b2", "exp2b3"],
        "project_order_ids": ["p4", "p6", "p5", "p1", "p3", "p2", "p7"],
        "summary_focus": "hierarchical federated graph learning (Flower), differential privacy, graph neural networks, and rigorous experimental benchmarking"
    },
    "Python Backend / FastAPI / Scalable Systems": {
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


def load_master_resume(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or settings.master_resume_path
    if not p.exists():
        raise FileNotFoundError(f"Master resume not found at {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def tailor_resume_for_job(job: Job, master_dict: Optional[Dict[str, Any]] = None) -> TailoredResume:
    master = master_dict or load_master_resume()

    role_tier, role_lens = classify_role_tier_and_lens(job.title, job.description)
    lens_cfg = ROLE_LENS_CONFIG.get(role_lens, ROLE_LENS_CONFIG["Generic ML / Data Science"])

    # 1. Contact info
    contact_dict = master.get("contact", {})
    contact = ResumeContactInfo(
        name=contact_dict.get("name", "Aswin P T"),
        email=contact_dict.get("email", "aswinpt2004@gmail.com"),
        phone=contact_dict.get("phone", "+91 88913 81713"),
        location=contact_dict.get("location", "Thiruvananthapuram, Kerala, India"),
        linkedin=contact_dict.get("linkedin", "https://www.linkedin.com/in/aswinpt2004"),
        github=contact_dict.get("github", "https://github.com/Aswinpt2004"),
        portfolio=contact_dict.get("portfolio", "https://codedbyaswinpt.vercel.app/")
    )

    # 2. Headline
    headline = ROLE_LENS_HEADLINES.get(role_lens, "AI/ML Engineer | Computer Vision & LLM Applications")

    # 3. Summary
    focus = lens_cfg["summary_focus"]
    summary = (
        f"AI/ML engineer (M.Sc. Computer Science in Machine Intelligence, 2026) targeting {job.title} "
        f"roles with hands-on experience in {focus}. "
        f"At Quantumweave Intelligence, I develop detection, tracking, and telemetry-aware intrusion pipelines "
        f"with GPU inference optimization and Dockerized surveillance web dashboards. "
        f"Solid foundation in Python, PyTorch, and FastAPI, dedicated to false-positive reduction, clean evaluation, "
        f"and collaborative Git branching workflows."
    )

    # 4. Skills reordering (preserving categories)
    canonical_skills = master.get("canonical_skills", {})
    tailored_skills: Dict[str, List[str]] = {}
    for cat, slist in canonical_skills.items():
        tailored_skills[cat] = list(slist)

    # 5. Experience bullets reordering
    exp_pool = master.get("experience_pool") or master.get("experience", [])
    tailored_exp: List[ResumeExperienceItem] = []
    for exp in exp_pool:
        comp_name = exp.get("company", "")
        lead_order = lens_cfg["exp1_lead_ids"] if "Quantumweave" in comp_name else lens_cfg["exp2_lead_ids"]
        bullet_objs = [ResumeBullet.from_item(b) for b in exp.get("bullets", [])]
        bullet_map = {b.id: b for b in bullet_objs if b.id}

        ordered_bullets = []
        for bid in lead_order:
            if bid in bullet_map:
                ordered_bullets.append(bullet_map[bid])
        for b in bullet_objs:
            if b not in ordered_bullets:
                ordered_bullets.append(b)

        dates_str = exp.get("dates") or f"{exp.get('start_date', '')} - {exp.get('end_date', '')}".strip(" -")
        tailored_exp.append(ResumeExperienceItem(
            company=comp_name,
            role=exp.get("role", ""),
            location=exp.get("location", ""),
            start_date=exp.get("start_date", ""),
            end_date=exp.get("end_date", ""),
            dates=dates_str,
            bullets=ordered_bullets
        ))

    # 6. Projects ordering
    proj_pool = master.get("project_pool") or master.get("projects", [])
    order_ids = lens_cfg["project_order_ids"]
    proj_map = {}
    for p in proj_pool:
        name = p.get("name") or p.get("title", "")
        pid = p.get("id") or str(name)[:4].lower()
        proj_map[pid] = p

    tailored_projects: List[ResumeProjectItem] = []
    # Add ordered projects
    for pid in order_ids:
        if pid in proj_map:
            p = proj_map[pid]
            name = p.get("name") or p.get("title", "")
            tech = p.get("technologies") or p.get("tech_stack", [])
            bullets = [ResumeBullet.from_item(b) for b in p.get("bullets", [])]
            tailored_projects.append(ResumeProjectItem(
                id=pid,
                name=name,
                title=name,
                technologies=tech if isinstance(tech, list) else [tech],
                tech_stack=tech,
                dates=p.get("dates", ""),
                bullets=bullets
            ))
    # Add remainder
    for p in proj_pool:
        name = p.get("name") or p.get("title", "")
        if not any(tp.name == name or tp.title == name for tp in tailored_projects):
            tech = p.get("technologies") or p.get("tech_stack", [])
            bullets = [ResumeBullet.from_item(b) for b in p.get("bullets", [])]
            tailored_projects.append(ResumeProjectItem(
                id=p.get("id"),
                name=name,
                title=name,
                technologies=tech if isinstance(tech, list) else [tech],
                tech_stack=tech,
                dates=p.get("dates", ""),
                bullets=bullets
            ))

    # 7. Education
    education = [ResumeEducationItem(**ed) for ed in master.get("education", [])]


    tailored = TailoredResume(
        contact=contact,
        headline=headline,
        summary=summary,
        skills=tailored_skills,
        experience=tailored_exp,
        projects=tailored_projects,
        education=education,
        coursework=master.get("coursework", []),
        achievements=master.get("achievements", []),
        certifications=master.get("certifications", []),
        lens=role_lens,
        target_tier=role_tier,
        match_score=85.0
    )

    # Verification and sanitization
    is_valid, violations = verify_no_fabrication(master, tailored)
    if not is_valid:
        tailored = sanitize_tailored_resume(master, tailored)

    return tailored

