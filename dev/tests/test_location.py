import pytest
from src.location import normalize_location

TEST_CASES = [
    # --- BANGALORE (Target) ---
    ("Bangalore", True, "bangalore"),
    ("Bengaluru", True, "bangalore"),
    ("Bengaluru, Karnataka, India", True, "bangalore"),
    ("Hybrid (Bangalore)", True, "bangalore"),
    ("Bangalore, India", True, "bangalore"),
    ("Bangalore, Karnataka", True, "bangalore"),
    ("Bengaluru-VTP, India", True, "bangalore"),
    ("IN-Bengaluru", True, "bangalore"),
    ("Whitefield, Bangalore", True, "bangalore"),
    ("Electronic City, Bangalore", True, "bangalore"),
    ("Manyata Tech Park, Bengaluru", True, "bangalore"),
    ("Koramangala, Bangalore", True, "bangalore"),
    ("Bangalore; Hyderabad; Pune", True, "bangalore"),
    ("Hybrid - Bangalore / Bengaluru", True, "bangalore"),
    ("Bellandur, Bengaluru", True, "bangalore"),

    # --- THIRUVANANTHAPURAM / TVM (Target) ---
    ("Thiruvananthapuram", True, "thiruvananthapuram"),
    ("Trivandrum", True, "thiruvananthapuram"),
    ("TVM", True, "thiruvananthapuram"),
    ("Trivandrum, Kerala", True, "thiruvananthapuram"),
    ("Technopark, TVM", True, "thiruvananthapuram"),
    ("Technopark, Trivandrum", True, "thiruvananthapuram"),
    ("Kazhakkoottam, Thiruvananthapuram", True, "thiruvananthapuram"),
    ("Trivandrum, Kerala, India", True, "thiruvananthapuram"),
    ("Technopark Phase 3, Trivandrum", True, "thiruvananthapuram"),

    # --- KOZHIKODE / KKD (Target) ---
    ("Kozhikode", True, "kozhikode"),
    ("Calicut", True, "kozhikode"),
    ("KKD", True, "kozhikode"),
    ("Calicut - Cyberpark", True, "kozhikode"),
    ("Cyberpark, Kozhikode", True, "kozhikode"),
    ("Kozhikode, Kerala", True, "kozhikode"),
    ("Hilite City, Calicut", True, "kozhikode"),

    # --- KOCHI (Target) ---
    ("Kochi", True, "kochi"),
    ("Cochin", True, "kochi"),
    ("Ernakulam", True, "kochi"),
    ("Infopark, Kochi", True, "kochi"),
    ("Kakkanad, Kochi", True, "kochi"),
    ("SmartCity Kochi", True, "kochi"),
    ("Kochi, Kerala, India", True, "kochi"),

    # --- REMOTE INDIA (Target) ---
    ("Remote - India", True, "remote_india"),
    ("Remote in India", True, "remote_india"),
    ("India Remote", True, "remote_india"),
    ("Remote, India", True, "remote_india"),
    ("Anywhere in India", True, "remote_india"),

    # --- NON-TARGET / REJECTED ---
    ("Remote - USA", False, None),
    ("Remote, United States", False, None),
    ("US-Remote", False, None),
    ("New York, NY", False, None),
    ("San Francisco, CA", False, None),
    ("London, United Kingdom", False, None),
    ("Dublin, Ireland", False, None),
    ("Singapore", False, None),
    ("Berlin, Germany", False, None),
    ("Toronto, Canada", False, None),
    ("São Paulo, Brazil", False, None),
    ("Mumbai", False, None),
    ("Pune", False, None),
    ("Hyderabad", False, None),
    ("Chennai", False, None),
    ("Delhi NCR", False, None),
    ("Kolkata", False, None),
    ("Home based - Worldwide", False, None),
    ("Home based - EMEA", False, None),
    ("Home based - Americas", False, None)
]


@pytest.mark.parametrize("raw_loc, expected_matched, expected_city", TEST_CASES)
def test_normalize_location_matrix(raw_loc, expected_matched, expected_city):
    result = normalize_location(raw_loc)
    assert result["matched"] == expected_matched, f"Failed for '{raw_loc}': got {result}"
    if expected_matched:
        assert result["city"] == expected_city, f"Expected city '{expected_city}' but got '{result['city']}' for '{raw_loc}'"


def test_fallback_to_jd_text():
    # When raw location is empty but JD mentions Technopark, Trivandrum
    res = normalize_location("", jd_text="Join our machine learning team based at Technopark, Trivandrum building computer vision.")
    assert res["matched"] is True
    assert res["city"] == "thiruvananthapuram"

    # When raw location is "India" but JD mentions Kozhikode
    res2 = normalize_location("India", jd_text="Office location: Cyberpark, Kozhikode. Python and PyTorch required.")
    assert res2["matched"] is True
    assert res2["city"] == "kozhikode"

