import re
from typing import Dict, Any, Optional, List, Tuple

# Canonical alias mapping for target locations
LOCATION_ALIASES: Dict[str, List[str]] = {
    "bangalore": [
        "bangalore", "bengaluru", "blr", "bangaluru", "bengaluru urban",
        "koramangala", "whitefield", "electronic city", "electronics city",
        "hsr layout", "indiranagar", "marathahalli", "manyata", "bellandur",
        "sarjapur", "outer ring road bangalore"
    ],
    "thiruvananthapuram": [
        "thiruvananthapuram", "trivandrum", "tvm", "technopark",
        "kazhakkoottam", "kazhakoottam", "kazhakuttam", "vizhinjam",
        "kowdiar", "pattom", "palayam", "vellayambalam", "karyavattom"
    ],
    "kozhikode": [
        "kozhikode", "calicut", "kkd", "cyberpark", "cyber park",
        "mavoor road", "kinfra calicut", "hilite city", "palazhi"
    ],
    "kochi": [
        "kochi", "cochin", "ernakulam", "infopark", "kakkanad",
        "smartcity kochi", "smart city kochi", "edappally", "kaloor",
        "vytilla", "mg road kochi", "kalamassery"
    ],
    "remote_india": [
        "remote - india", "remote in india", "remote (india)", "india remote",
        "remote, india", "remote - in", "remote (in)", "remote india",
        "work from home - india", "anywhere in india", "pan-india", "pan india"
    ]
}

# Explicit non-target regions to instantly reject
FOREIGN_OR_NON_TARGET: List[str] = [
    "united states", "usa", "u.s.", "us-remote", "remote - us", "remote, united states",
    "canada", "toronto", "vancouver", "united kingdom", "uk", "london",
    "germany", "berlin", "munich", "ireland", "dublin", "singapore",
    "australia", "sydney", "melbourne", "brazil", "são paulo", "sao paulo",
    "netherlands", "amsterdam", "poland", "warsaw", "france", "paris",
    "spain", "madrid", "barcelona", "mexico", "mexico city",
    "mumbai", "pune", "delhi", "noida", "gurgaon", "gurugram", "hyderabad",
    "chennai", "kolkata", "ahmedabad", "jaipur"
]


def clean_text(text: str) -> str:
    """Normalize text by lowercasing and replacing punctuation/symbols with single spaces."""
    if not text:
        return ""
    # Normalize hyphens and slashes
    t = text.lower()
    t = re.sub(r'[\r\n\t]+', ' ', t)
    return t.strip()


def normalize_location(raw_location: Optional[str], jd_text: str = "", title: str = "") -> Dict[str, Any]:
    """
    Evaluates raw location string (and falls back to JD/title if needed).
    Returns:
        {
            "matched": bool,
            "city": Optional[str],
            "confidence": float,
            "evidence": str
        }
    """
    if not raw_location or not raw_location.strip():
        # Check fallback text
        combined_fallback = f"{title} {jd_text[:3000]}"
        return _search_in_text(combined_fallback, is_fallback=True)

    loc_str = clean_text(raw_location)

    # 1. Check if location has explicitly remote / hybrid markers
    is_remote_mentioned = "remote" in loc_str or "work from home" in loc_str or "wfh" in loc_str
    has_india_marker = "india" in loc_str or "in" in loc_str.split() or "ist" in loc_str

    # 2. Check for explicit foreign / non-target locations (e.g. "Remote - US", "London, UK", "Mumbai")
    # Split on delimiters: ; , / | and or -
    tokens = [t.strip() for t in re.split(r'[;,\/|&]|\band\b|\bor\b', loc_str) if t.strip()]

    # If all tokens are non-target, reject early
    matched_target = None
    target_evidence = ""
    highest_confidence = 0.0

    for token in tokens:
        # Check against target cities
        for canonical_city, aliases in LOCATION_ALIASES.items():
            if canonical_city == "remote_india":
                continue
            for alias in aliases:
                # Word boundary check
                pattern = rf'\b{re.escape(alias)}\b'
                if re.search(pattern, token):
                    matched_target = canonical_city
                    target_evidence = f"Matched alias '{alias}' in part '{token}'"
                    highest_confidence = 0.95
                    break
            if matched_target:
                break
        if matched_target:
            break

    # If not found in tokens, check whole loc_str for target aliases
    if not matched_target:
        for canonical_city, aliases in LOCATION_ALIASES.items():
            if canonical_city == "remote_india":
                continue
            for alias in aliases:
                pattern = rf'\b{re.escape(alias)}\b'
                if re.search(pattern, loc_str):
                    matched_target = canonical_city
                    target_evidence = f"Matched alias '{alias}' in '{raw_location}'"
                    highest_confidence = 0.90
                    break
            if matched_target:
                break

    # 3. Check for Remote India specifically
    for alias in LOCATION_ALIASES["remote_india"]:
        pattern = rf'\b{re.escape(alias)}\b'
        if re.search(pattern, loc_str):
            matched_target = "remote_india"
            target_evidence = f"Matched alias '{alias}' in '{raw_location}'"
            highest_confidence = 0.90
            break

    if not matched_target and is_remote_mentioned:
        # Must have India context
        if has_india_marker:
            # But must NOT specify foreign country like "Remote, United States" or "Remote - Europe"
            foreign_found = False
            for f in ["united states", "usa", "us", "uk", "europe", "emea", "latam", "canada", "germany", "australia"]:
                if re.search(rf'\b{re.escape(f)}\b', loc_str) and not re.search(r'\bindia\b', loc_str):
                    foreign_found = True
                    break
            if not foreign_found:
                matched_target = "remote_india"
                target_evidence = f"Matched remote India in '{raw_location}'"
                highest_confidence = 0.85

    # 4. If matched target found, make sure it's not a negated foreign match (e.g. "Remote, Poland")
    if matched_target:
        # Verify it wasn't matched purely as a substring inside an unrelated word
        return {
            "matched": True,
            "city": matched_target,
            "confidence": highest_confidence,
            "evidence": target_evidence
        }

    # 5. Check if plain "India" or empty with potential target in JD
    if loc_str == "india" or loc_str == "in":
        fallback_res = _search_in_text(f"{title} {jd_text[:3000]}", is_fallback=True)
        if fallback_res["matched"]:
            return fallback_res
        return {
            "matched": False,
            "city": None,
            "confidence": 0.0,
            "evidence": "Broad 'India' with no specific target city"
        }

    return {
        "matched": False,
        "city": None,
        "confidence": 0.0,
        "evidence": f"Location '{raw_location}' is outside target regions"
    }


def _search_in_text(text: str, is_fallback: bool = False) -> Dict[str, Any]:
    """Helper to find target city aliases inside description or title text."""
    clean = clean_text(text)
    if not clean:
        return {"matched": False, "city": None, "confidence": 0.0, "evidence": "No text available"}

    for canonical_city, aliases in LOCATION_ALIASES.items():
        if canonical_city == "remote_india":
            continue
        for alias in aliases:
            pattern = rf'\b{re.escape(alias)}\b'
            match = re.search(pattern, clean)
            if match:
                conf = 0.75 if is_fallback else 0.85
                return {
                    "matched": True,
                    "city": canonical_city,
                    "confidence": conf,
                    "evidence": f"Found '{alias}' in JD/title text"
                }

    # Check remote India in text
    if "remote" in clean and ("india" in clean or "ist" in clean):
        return {
            "matched": True,
            "city": "remote_india",
            "confidence": 0.70,
            "evidence": "Found Remote India context in text"
        }

    return {
        "matched": False,
        "city": None,
        "confidence": 0.0,
        "evidence": "No target city identified in text"
    }
