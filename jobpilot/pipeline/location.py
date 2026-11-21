import re
from typing import Dict, Any, Optional, List

LOCATION_ALIASES: Dict[str, List[str]] = {
    "Bangalore": [
        "bangalore", "bengaluru", "blr", "bangaluru", "bengaluru urban",
        "koramangala", "whitefield", "electronic city", "electronics city",
        "hsr layout", "indiranagar", "marathahalli", "manyata", "bellandur",
        "sarjapur", "outer ring road bangalore"
    ],
    "Thiruvananthapuram": [
        "thiruvananthapuram", "trivandrum", "tvm", "technopark",
        "kazhakkoottam", "kazhakoottam", "kazhakuttam", "vizhinjam",
        "kowdiar", "pattom", "palayam", "vellayambalam", "karyavattom"
    ],
    "Kozhikode": [
        "kozhikode", "calicut", "kkd", "cyberpark", "cyber park",
        "mavoor road", "kinfra calicut", "hilite city", "palazhi"
    ],
    "Kochi": [
        "kochi", "cochin", "ernakulam", "infopark", "kakkanad",
        "smartcity kochi", "smart city kochi", "edappally", "kaloor",
        "vytilla", "mg road kochi", "kalamassery"
    ],
    "Remote India": [
        "remote - india", "remote in india", "remote (india)", "india remote",
        "remote, india", "remote - in", "remote (in)", "remote india",
        "work from home - india", "anywhere in india", "pan-india", "pan india"
    ]
}

FOREIGN_OR_NON_TARGET: List[str] = [
    "united states", "usa", "u.s.", "us-remote", "remote - us", "remote, united states",
    "canada", "toronto", "vancouver", "united kingdom", "uk", "london",
    "germany", "berlin", "munich", "ireland", "dublin", "singapore",
    "australia", "sydney", "melbourne", "brazil", "netherlands", "amsterdam",
    "poland", "warsaw", "france", "paris", "spain", "madrid", "barcelona",
    "mumbai", "pune", "delhi", "noida", "gurgaon", "gurugram", "hyderabad",
    "chennai", "kolkata", "ahmedabad", "jaipur"
]


def clean_text(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r'[\r\n\t]+', ' ', t)
    return t.strip()


def normalize_location(raw_location: Optional[str], jd_text: str = "", title: str = "") -> Dict[str, Any]:
    """
    Evaluates raw location string (and falls back to JD/title if needed).
    Returns dict: {
        "matched": bool,
        "city": Optional[str],
        "normalized_city": str,
        "confidence": float,
        "evidence": str
    }
    """
    if not raw_location or not raw_location.strip() or raw_location.lower() == "remote":
        combined_fallback = f"{title} {jd_text[:3000]}"
        fallback_res = _search_in_text(combined_fallback, is_fallback=True)
        if fallback_res["matched"]:
            return fallback_res
        # If explicitly remote without foreign exclusion, allow as Remote India
        if raw_location and raw_location.lower() == "remote":
            clean_fb = clean_text(combined_fallback)
            for non_t in FOREIGN_OR_NON_TARGET:
                if re.search(r'\b' + re.escape(non_t) + r'\b', clean_fb):
                    return {"matched": False, "city": None, "normalized_city": "Excluded", "confidence": 0.0, "evidence": f"Excluded non-target in JD: {non_t}"}
            return {"matched": True, "city": "Remote India", "normalized_city": "Remote India", "confidence": 0.8, "evidence": "Remote (no foreign restrictions detected)"}
        return {"matched": False, "city": None, "normalized_city": "Unknown", "confidence": 0.0, "evidence": "No valid target location found"}

    loc_str = clean_text(raw_location)

    # Check for explicit foreign / non-target locations
    for non_t in FOREIGN_OR_NON_TARGET:
        pattern = r'\b' + re.escape(non_t) + r'\b'
        if re.search(pattern, loc_str):
            # Check if an allowed target city is also explicitly co-listed (e.g. Bangalore / Mumbai)
            has_allowed_match = False
            for target_city, aliases in LOCATION_ALIASES.items():
                for alias in aliases:
                    if re.search(r'\b' + re.escape(alias) + r'\b', loc_str):
                        return {
                            "matched": True,
                            "city": target_city,
                            "normalized_city": target_city,
                            "confidence": 0.9,
                            "evidence": f"Multi-city match including {target_city}"
                        }
            return {
                "matched": False,
                "city": None,
                "normalized_city": "Excluded",
                "confidence": 0.0,
                "evidence": f"Matches non-target location: {non_t}"
            }

    # Match aliases
    for target_city, aliases in LOCATION_ALIASES.items():
        for alias in aliases:
            pattern = r'\b' + re.escape(alias) + r'\b'
            if re.search(pattern, loc_str):
                return {
                    "matched": True,
                    "city": target_city,
                    "normalized_city": target_city,
                    "confidence": 1.0,
                    "evidence": f"Matched alias '{alias}' for {target_city}"
                }

    # Check for general India match if remote
    if ("remote" in loc_str or "wfh" in loc_str) and ("india" in loc_str or "in" in loc_str.split()):
        return {
            "matched": True,
            "city": "Remote India",
            "normalized_city": "Remote India",
            "confidence": 0.95,
            "evidence": "Remote within India"
        }

    return {
        "matched": False,
        "city": None,
        "normalized_city": "Other",
        "confidence": 0.0,
        "evidence": f"Location '{raw_location}' not in target list"
    }


def _search_in_text(text: str, is_fallback: bool = False) -> Dict[str, Any]:
    if not text:
        return {"matched": False, "city": None, "normalized_city": "Unknown", "confidence": 0.0, "evidence": "Empty text"}
    cleaned = clean_text(text)

    # Check foreign exclusions
    for non_t in FOREIGN_OR_NON_TARGET:
        if re.search(r'\b' + re.escape(non_t) + r'\b', cleaned):
            # If target city also explicitly mentioned, prioritize target city
            for target_city, aliases in LOCATION_ALIASES.items():
                for alias in aliases:
                    if re.search(r'\b' + re.escape(alias) + r'\b', cleaned):
                        return {
                            "matched": True,
                            "city": target_city,
                            "normalized_city": target_city,
                            "confidence": 0.75,
                            "evidence": f"Found {target_city} in text despite {non_t}"
                        }
            return {"matched": False, "city": None, "normalized_city": "Excluded", "confidence": 0.0, "evidence": f"Excluded non-target {non_t}"}

    for target_city, aliases in LOCATION_ALIASES.items():
        for alias in aliases:
            if re.search(r'\b' + re.escape(alias) + r'\b', cleaned):
                return {
                    "matched": True,
                    "city": target_city,
                    "normalized_city": target_city,
                    "confidence": 0.75 if is_fallback else 0.9,
                    "evidence": f"Found '{alias}' in text"
                }

    return {"matched": False, "city": None, "normalized_city": "Unknown", "confidence": 0.0, "evidence": "No target city found in text"}

