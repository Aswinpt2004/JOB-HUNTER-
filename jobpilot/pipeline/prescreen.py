import re
from typing import Dict, Any

SENIOR_TITLES = [
    r'\bsenior\b', r'\bsr\.?\b', r'\blead\b', r'\bstaff\b', r'\bprincipal\b',
    r'\barchitect\b', r'\bdirector\b', r'\bvp\b', r'\bvice\s+president\b',
    r'\bhead\s+of\b', r'\bmanager\b', r'\bengineering\s+manager\b',
    r'\bexpert\b', r'\bdistinguished\b'
]

FRESHER_MARKERS = [
    r'\bfresher\b', r'\bentry\s+level\b', r'\bjunior\b', r'\bjr\.?\b',
    r'\bintern\b', r'\binternship\b', r'\bgraduate\b', r'\btrainee\b',
    r'\b0\s*-\s*1\s*(years?|yrs?)\b', r'\b0\s*-\s*2\s*(years?|yrs?)\b',
    r'\b1\s*(year|yr)\b', r'\bcollege\b', r'\buniversity\b', r'\bassociate\b'
]

HIGH_EXP_PATTERNS = [
    r'\b([3-9]|1[0-9])\+?\s*(years?|yrs?)\s*(of)?\s*(experience|exp)\b',
    r'\bmin(imum)?\s*([3-9]|1[0-9])\s*(years?|yrs?)\b',
    r'\b([3-9]|1[0-9])\s*to\s*[0-9]+\s*(years?|yrs?)\b'
]


def prescreen_job(title: str, description: str = "") -> Dict[str, Any]:
    """
    Zero-token fast rule-based prescreen.
    Disqualifies senior, architect, staff, or 3+ year roles.
    Allows fresher, 0-1 yr, junior, trainee, associate, intern, or entry roles.
    """
    title_lower = title.lower()
    desc_lower = description.lower() if description else ""

    # 1. Senior title checks
    for pat in SENIOR_TITLES:
        if re.search(pat, title_lower):
            # If title also explicitly says intern or trainee (rare edge case), allow
            if not any(re.search(f, title_lower) for f in [r'\bintern\b', r'\btrainee\b']):
                return {
                    "eligible": False,
                    "reason": f"Senior title detected: {pat}"
                }

    # 2. Check for explicit fresher indicators
    for f in FRESHER_MARKERS:
        if re.search(f, title_lower):
            return {"eligible": True, "reason": f"Fresher title marker: {f}"}

    # 3. Check for high experience requirements in description
    for pat in HIGH_EXP_PATTERNS:
        match = re.search(pat, desc_lower[:3000])
        if match:
            # If description explicitly says "0-1 year" or "freshers can apply", allow
            if re.search(r'\b(freshers?|0\s*-\s*1\s*years?)\b', desc_lower[:3000]):
                return {"eligible": True, "reason": "Fresher clause supersedes experience text"}
            return {
                "eligible": False,
                "reason": f"Experience requirement detected: {match.group(0)}"
            }

    return {"eligible": True, "reason": "Passed prescreening"}

