import re
from typing import Optional


def normalize_job_title(title: str) -> str:
    if not title:
        return ""
    t = re.sub(r'[\r\n\t]+', ' ', title).strip()
    # Normalize common abbreviations
    t = re.sub(r'\bml\b', 'Machine Learning', t, flags=re.IGNORECASE)
    t = re.sub(r'\bai\b', 'AI', t, flags=re.IGNORECASE)
    t = re.sub(r'\bcv\b', 'Computer Vision', t, flags=re.IGNORECASE)
    t = re.sub(r'\bsw\b', 'Software', t, flags=re.IGNORECASE)
    t = re.sub(r'\bswe\b', 'Software Engineer', t, flags=re.IGNORECASE)
    return t


def normalize_salary(salary_raw: Optional[str]) -> Optional[str]:
    if not salary_raw:
        return None
    s = str(salary_raw).strip()
    if not s or s.lower() in ["not disclosed", "competitive", "none", "n/a"]:
        return None
    return s


def normalize_employment_type(raw_type: Optional[str]) -> str:
    if not raw_type:
        return "Full-time"
    t = raw_type.lower()
    if "intern" in t:
        return "Internship"
    if "contract" in t or "freelance" in t:
        return "Contract"
    if "part" in t:
        return "Part-time"
    return "Full-time"

