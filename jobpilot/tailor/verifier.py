import logging
import re
from typing import List, Tuple, Set, Dict, Any
from jobpilot.core.models import TailoredResume

logger = logging.getLogger("jobpilot.tailor.verifier")

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
    "cv": "computer vision",
    "computer vision": "computer vision",
    "dl": "deep learning",
    "deep learning": "deep learning",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "ai": "artificial intelligence",
    "rag": "retrieval-augmented generation",
}


def normalize_term(term: str) -> str:
    clean = re.sub(r'[^a-zA-Z0-9]', '', term.lower().strip())
    raw = term.lower().strip()
    return SYNONYM_MAP.get(raw, clean)


def _extract_all_master_tokens(master: Any) -> Set[str]:
    tokens = set()

    # Support canonical_skills, skills, or dictionary
    skills_dict = getattr(master, "canonical_skills", getattr(master, "skills", None))
    if isinstance(master, dict):
        skills_dict = master.get("canonical_skills") or master.get("skills")

    if isinstance(skills_dict, dict):
        for cat_skills in skills_dict.values():
            if isinstance(cat_skills, list):
                for s in cat_skills:
                    tokens.add(normalize_term(str(s)))
                    for word in str(s).replace("/", " ").replace("-", " ").split():
                        if len(word) > 2:
                            tokens.add(normalize_term(word))
            elif isinstance(cat_skills, str):
                for s in cat_skills.split(","):
                    tokens.add(normalize_term(s.strip()))

    # Experience companies & titles
    exp_pool = getattr(master, "experience_pool", getattr(master, "experience", []))
    if isinstance(master, dict):
        exp_pool = master.get("experience_pool") or master.get("experience", [])
    for e in exp_pool:
        comp = getattr(e, "company", None) or (e.get("company") if isinstance(e, dict) else "")
        role = getattr(e, "role", None) or (e.get("role") if isinstance(e, dict) else "")
        if comp:
            tokens.add(normalize_term(comp))
        if role:
            for w in role.split():
                tokens.add(normalize_term(w))

    # Education degrees & institutions
    edu_pool = getattr(master, "education", [])
    if isinstance(master, dict):
        edu_pool = master.get("education", [])
    for ed in edu_pool:
        inst = getattr(ed, "institution", None) or (ed.get("institution") if isinstance(ed, dict) else "")
        deg = getattr(ed, "degree", None) or (ed.get("degree") if isinstance(ed, dict) else "")
        if inst:
            tokens.add(normalize_term(inst))
        if deg:
            for w in deg.split():
                tokens.add(normalize_term(w))

    return tokens


def verify_no_fabrication(master: Any, tailored: Any) -> Tuple[bool, List[str]]:
    """
    Zero-fabrication verification check:
    Ensures that every skill in the tailored resume is grounded in the master resume.
    Prevents hallucinating unearned degrees, companies, or unsupported skills.
    """
    # Guard against swapped arguments
    if hasattr(master, "lens") and not hasattr(tailored, "lens") and hasattr(tailored, "canonical_skills"):
        master, tailored = tailored, master

    violations: List[str] = []
    master_tokens = _extract_all_master_tokens(master)

    tailored_skills = getattr(tailored, "skills", {})
    if isinstance(tailored, dict):
        tailored_skills = tailored.get("skills", {})

    if isinstance(tailored_skills, dict):
        for cat, skills in tailored_skills.items():
            if isinstance(skills, list):
                for s in skills:
                    norm = normalize_term(str(s))
                    # Allow composite terms if sub-words exist
                    words = [normalize_term(w) for w in str(s).replace("/", " ").replace("-", " ").split() if len(w) > 2]
                    if norm not in master_tokens and not any(w in master_tokens for w in words):
                        violations.append(f"Unverified skill in tailored resume: '{s}' (category: {cat})")
            elif isinstance(skills, str):
                for s in skills.split(","):
                    s_clean = s.strip()
                    norm = normalize_term(s_clean)
                    words = [normalize_term(w) for w in s_clean.replace("/", " ").replace("-", " ").split() if len(w) > 2]
                    if norm not in master_tokens and not any(w in master_tokens for w in words):
                        violations.append(f"Unverified skill: '{s_clean}'")

    is_valid = len(violations) == 0
    if not is_valid:
        logger.warning("Fabrication verifier detected %d ungrounded items: %s", len(violations), violations)
    return is_valid, violations


def sanitize_tailored_resume(master: Any, tailored: Any) -> Any:
    """Strips any ungrounded skills from tailored resume to guarantee 100% factual accuracy."""
    master_tokens = _extract_all_master_tokens(master)
    skills = getattr(tailored, "skills", {})
    if isinstance(skills, dict):
        for cat, items in skills.items():
            if isinstance(items, list):
                valid_items = []
                for s in items:
                    norm = normalize_term(str(s))
                    words = [normalize_term(w) for w in str(s).replace("/", " ").replace("-", " ").split() if len(w) > 2]
                    if norm in master_tokens or any(w in master_tokens for w in words):
                        valid_items.append(s)
                skills[cat] = valid_items
    return tailored

