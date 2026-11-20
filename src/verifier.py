import logging
import re
from typing import List, Tuple, Set, Dict
from src.models import MasterResume, TailoredResume

logger = logging.getLogger("jobpilot.verifier")

# Canonical synonym map for tech terms
SYNONYM_MAP: Dict[str, str] = {
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "torch": "pytorch",
    "pytorch": "pytorch",
    "tf": "tensorflow",
    "tensorflow": "tensorflow",
    "ts": "typescript",
    "typescript": "typescript",
    "js": "javascript",
    "javascript": "javascript",
    "node": "nodejs",
    "nodejs": "nodejs",
    "node.js": "nodejs",
    "py": "python",
    "python": "python",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "gcp": "google cloud platform",
    "google cloud platform": "google cloud platform",
    "aws": "amazon web services",
    "amazon web services": "amazon web services",
    "cv": "computer vision",
    "computer vision": "computer vision",
    "dl": "deep learning",
    "deep learning": "deep learning",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "ai": "artificial intelligence",
    "artificial intelligence": "artificial intelligence",
    "rag": "retrieval-augmented generation",
    "retrieval-augmented generation": "retrieval-augmented generation",
}


def normalize_term(term: str) -> str:
    """Normalizes terms using synonym mapping and punctuation stripping."""
    clean = re.sub(r'[^a-zA-Z0-9]', '', term.lower().strip())
    raw = term.lower().strip()
    return SYNONYM_MAP.get(raw, clean)


def _extract_all_master_tokens(master: MasterResume) -> Set[str]:
    """Extracts all recognized skills, tools, employers, degrees, and project tokens from master resume."""
    tokens = set()

    # Skills
    for cat_skills in master.skills.values():
        for s in cat_skills:
            tokens.add(normalize_term(s))
            for word in s.replace("/", " ").replace("-", " ").split():
                if len(word) > 2:
                    tokens.add(normalize_term(word))

    # Experience
    for exp in master.experience:
        tokens.add(normalize_term(exp.company))
        tokens.add(normalize_term(exp.role))
        for b in exp.bullets:
            b_text = b if isinstance(b, str) else getattr(b, "text", str(b))
            for word in b_text.replace(",", " ").replace(".", " ").replace("(", " ").replace(")", " ").split():
                if len(word) > 2:
                    tokens.add(normalize_term(word))

    # Projects
    for proj in master.projects:
        tokens.add(normalize_term(proj.name))
        for tech in getattr(proj, "technologies", []) or getattr(proj, "stack", []):
            tokens.add(normalize_term(tech))
        for b in proj.bullets:
            b_text = b if isinstance(b, str) else getattr(b, "text", str(b))
            for word in b_text.replace(",", " ").replace(".", " ").replace("(", " ").replace(")", " ").split():
                if len(word) > 2:
                    tokens.add(normalize_term(word))

    # Education
    for edu in master.education:
        tokens.add(normalize_term(edu.degree))
        tokens.add(normalize_term(edu.institution))
        tokens.add(normalize_term(edu.field_of_study))

    # Certifications
    for cert in master.certifications:
        tokens.add(normalize_term(cert))

    return tokens


def verify_no_fabrication(
    tailored: TailoredResume,
    master: MasterResume
) -> Tuple[bool, List[str]]:
    """
    Checks that every skill, employer, project, and degree in the tailored output exists in master.
    Returns (is_valid, list_of_violations).
    """
    # Defensive guard: if arguments are passed in reversed order (master, tailored), swap them
    if (isinstance(tailored, MasterResume) and isinstance(master, TailoredResume)) or (
        hasattr(tailored, "skills") and not hasattr(tailored, "highlighted_skills") and hasattr(master, "highlighted_skills")
    ):
        tailored, master = master, tailored

    violations = []
    master_tokens = _extract_all_master_tokens(master)

    # 1. Verify Skills
    tailored_skills_dict = getattr(tailored, "highlighted_skills", None) or getattr(tailored, "skills", {})
    for cat, skills in tailored_skills_dict.items():
        for s in skills:
            norm_s = normalize_term(s)
            if norm_s not in master_tokens and not any(norm_s in mt or mt in norm_s for mt in master_tokens if len(mt) > 3):
                violations.append(f"Fabricated skill detected in category '{cat}': '{s}'")

    # 2. Verify Employers
    master_companies = {normalize_term(e.company) for e in master.experience}
    for exp in tailored.experience:
        if normalize_term(exp.company) not in master_companies:
            violations.append(f"Fabricated employer detected: '{exp.company}'")

    # 3. Verify Projects
    master_projects = {normalize_term(p.name) for p in master.projects}
    for proj in tailored.projects:
        if normalize_term(proj.name) not in master_projects:
            violations.append(f"Fabricated project detected: '{proj.name}'")

    # 4. Verify Degrees
    master_degrees = {normalize_term(edu.degree) for edu in master.education}
    for edu in tailored.education:
        if normalize_term(edu.degree) not in master_degrees:
            violations.append(f"Fabricated degree detected: '{edu.degree}'")

    # 5. Verify Dates
    master_exp_dates = {(normalize_term(e.company), e.start_date.strip(), e.end_date.strip()) for e in master.experience}
    for exp in tailored.experience:
        exp_key = (normalize_term(exp.company), exp.start_date.strip(), exp.end_date.strip())
        if exp_key not in master_exp_dates:
            violations.append(f"Altered experience date detected for '{exp.company}': '{exp.start_date} – {exp.end_date}'")

    is_valid = len(violations) == 0
    return is_valid, violations


def sanitize_tailored_resume(
    tailored: TailoredResume,
    master: MasterResume
) -> TailoredResume:
    """
    Sanitizes the tailored resume by removing any fabricated skills, employers, or projects,
    falling back to master content when violations occur.
    """
    # Defensive guard: if arguments are passed in reversed order, swap them
    if (isinstance(tailored, MasterResume) and isinstance(master, TailoredResume)) or (
        hasattr(tailored, "skills") and not hasattr(tailored, "highlighted_skills") and hasattr(master, "highlighted_skills")
    ):
        tailored, master = master, tailored

    master_tokens = _extract_all_master_tokens(master)
    master_companies = {normalize_term(e.company): e for e in master.experience}
    master_projects = {normalize_term(p.name): p for p in master.projects}

    # Sanitize Skills
    tailored_skills_dict = getattr(tailored, "highlighted_skills", None) or getattr(tailored, "skills", {})
    cleaned_skills: Dict[str, List[str]] = {}
    for cat, skills in tailored_skills_dict.items():
        valid_skills = []
        for s in skills:
            norm_s = normalize_term(s)
            if norm_s in master_tokens or any(norm_s in mt or mt in norm_s for mt in master_tokens if len(mt) > 3):
                valid_skills.append(s)
            else:
                logger.warning("Sanitizer purged fabricated skill: %s", s)
        if valid_skills:
            cleaned_skills[cat] = valid_skills

    if hasattr(tailored, "highlighted_skills"):
        tailored.highlighted_skills = cleaned_skills
    if hasattr(tailored, "skills"):
        tailored.skills = cleaned_skills

    # Sanitize Experience
    cleaned_exp = []
    for exp in tailored.experience:
        norm_c = normalize_term(exp.company)
        if norm_c in master_companies:
            cleaned_exp.append(exp)
        else:
            logger.warning("Sanitizer purged fabricated employer: %s", exp.company)
    tailored.experience = cleaned_exp or master.experience

    # Sanitize Projects
    cleaned_projects = []
    for proj in tailored.projects:
        norm_p = normalize_term(proj.name)
        if norm_p in master_projects:
            cleaned_projects.append(proj)
        else:
            logger.warning("Sanitizer purged fabricated project: %s", proj.name)
    tailored.projects = cleaned_projects or master.projects

    return tailored

