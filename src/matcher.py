import json
import logging
import re
from typing import Dict, Any, List, Set, Tuple, Optional
from src.config import settings
from src.models import JDParsed, MasterResume, MatchResult
from src.llm import generate
from src.db import log_event

logger = logging.getLogger("jobpilot.matcher")

# Section 5: Extended Synonym Map
SYNONYM_GROUPS: List[List[str]] = [
    ["cv", "computer vision", "image processing", "video analytics", "visual perception"],
    ["object detection", "detection", "yolo", "yolov8", "rt-detr", "rf-detr", "detr"],
    ["tracking", "multi-object tracking", "mot", "bytetrack", "botsort", "bot-sort"],
    ["crowd counting", "people counting", "csrnet"],
    ["uav", "drone", "aerial", "unmanned aerial vehicle"],
    ["llm", "large language model", "genai", "generative ai", "gpt", "gemini api", "llama"],
    ["rag", "retrieval augmented generation", "retrieval-augmented generation", "vector search"],
    ["agentic ai", "ai agents", "agent workflows", "multi-agent"],
    ["vlm", "vision-language model", "multimodal"],
    ["nlp", "natural language processing", "text mining"],
    ["fastapi", "rest api", "python api", "backend api"],
    ["pydantic", "schema validation", "data contracts"],
    ["federated learning", "fl", "flower", "fedavg"],
    ["gnn", "graph neural network", "graph ml", "gat", "graph attention"],
    ["dl", "deep learning", "neural networks"],
    ["mlops", "model deployment", "inference optimisation", "gpu inference"],
    ["ocr", "document extraction", "pdf extraction", "idp", "document ai"],
    ["pytorch", "torch"],
    ["k8s", "kubernetes"],
    ["ts", "typescript"],
    ["js", "javascript"]
]

# Section 4: Skill Weights
SKILL_WEIGHTS: Dict[str, float] = {
    # 3.0 weight
    "computer vision": 3.0,
    "object detection": 3.0,
    "yolo": 3.0,
    "rt-detr": 3.0,
    "tracking": 3.0,
    "opencv": 3.0,
    "pytorch": 3.0,
    "llm apps": 3.0,
    "rag": 3.0,
    "agentic ai": 3.0,

    # 2.0 weight
    "fastapi": 2.0,
    "python": 2.0,
    "pydantic": 2.0,
    "docker": 2.0,
    "drone": 2.0,
    "uav": 2.0,
    "surveillance": 2.0,
    "document extraction": 2.0,
    "gnn": 2.0,
    "federated learning": 2.0,
    "tensorflow": 2.0,

    # 1.0 weight
    "django": 1.0,
    "flask": 1.0,
    "sql": 1.0,
    "postgresql": 1.0,
    "mysql": 1.0,
    "git": 1.0,
    "gcp": 1.0,
    "node.js": 1.0,
    "react": 1.0,
    "next.js": 1.0,
    "gemini api": 1.0
}


def are_skills_synonyms(skill_a: str, skill_b: str) -> bool:
    """Checks if two skill strings are equivalent or synonyms."""
    a = skill_a.strip().lower()
    b = skill_b.strip().lower()
    if a == b or a in b or b in a:
        return True
    for group in SYNONYM_GROUPS:
        in_a = any(term in a or a == term for term in group)
        in_b = any(term in b or b == term for term in group)
        if in_a and in_b:
            return True
    return False


def get_skill_weight(skill: str) -> float:
    """Returns assigned skill weight (3.0, 2.0, 1.0, default 1.0)."""
    s_low = skill.strip().lower()
    for k, w in SKILL_WEIGHTS.items():
        if are_skills_synonyms(s_low, k):
            return w
    return 1.0


def classify_role(role_title: str, jd_text: str = "") -> Tuple[str, str]:
    """
    Classifies role into (role_tier, role_lens).
    Tiers: Tier A (core fit), Tier B (good fit), Tier C (acceptable if AI included), reject.
    Role lenses:
      - Computer Vision / Drone / Surveillance
      - LLM / GenAI / RAG / Agents
      - Document AI / Healthcare AI
      - Federated / Privacy / Graph ML / Research
      - Backend / Full-stack with AI
      - Generic ML / Data Science
    """
    t_clean = f"{role_title} {jd_text[:1500]}".lower()
    title_low = role_title.lower()

    # 1. Hard Rejections
    reject_patterns = [
        r'\b(?:frontend|front-end|react\s+developer|ui\/ux|angular)\b',
        r'\b(?:qa\b|quality\s+assurance|software\s+tester|automation\s+tester)\b',
        r'\b(?:sap\b|erp\b|salesforce|workday)\b',
        r'\b(?:java\s+developer|\.net\s+developer|c#\s+developer)\b',
        r'\b(?:embedded\s+firmware|hardware|vlsi|pcb)\b',
        r'\b(?:sales|marketing|bpo|customer\s+support|technical\s+writer)\b',
        r'\b(?:data\s+entry|telecaller|tele-sales)\b'
    ]
    # Check if title itself is a reject
    is_rejected = any(re.search(p, title_low) for p in reject_patterns)
    if is_rejected and not any(k in title_low for k in ["ai", "ml", "computer vision", "machine learning"]):
        return "reject", "Generic ML / Data Science"

    # 2. Tier B checks (Document AI, Healthcare AI, Research, Graph, Federated)
    tier_b_patterns = [
        r'document\s+ai', r'document\s+processing', r'idp',
        r'medical\s+imaging', r'healthcare\s+ai', r'clinical\s+ai',
        r'data\s+scientist', r'research\s+assistant', r'research\s+associate',
        r'research\s+engineer', r'federated\s+learning', r'graph\s+ml',
        r'graph\s+neural'
    ]
    for pat in tier_b_patterns:
        if re.search(pat, title_low) or re.search(pat, t_clean):
            if any(k in t_clean for k in ["document", "pdf", "extraction", "medical", "clinical", "pi-rads", "ocr"]):
                return "Tier B", "Document AI / Healthcare AI"
            if any(k in t_clean for k in ["federated", "graph", "gnn", "privacy", "connectome", "research"]):
                return "Tier B", "Federated / Privacy / Graph ML / Research"
            return "Tier B", "Generic ML / Data Science"

    # 3. Tier A checks
    tier_a_patterns = [
        r'computer\s+vision', r'video\s+analytics', r'vision\s+engineer',
        r'object\s+detection', r'perception\s+engineer', r'drone', r'uav',
        r'surveillance', r'ai\/ml\s+engineer', r'applied\s+ml',
        r'machine\s+learning\s+engineer', r'deep\s+learning', r'genai',
        r'llm\s+engineer', r'ai\s+application', r'rag', r'agentic\s+ai',
        r'agent\s+developer', r'ai\s+engineer'
    ]
    for pat in tier_a_patterns:
        if re.search(pat, title_low):
            # Determine lens
            if any(k in t_clean for k in ["drone", "uav", "surveillance", "video", "tracking", "yolo", "opencv", "vision"]):
                return "Tier A", "Computer Vision / Drone / Surveillance"
            if any(k in t_clean for k in ["llm", "rag", "agent", "genai", "prompt", "langchain"]):
                return "Tier A", "LLM / GenAI / RAG / Agents"
            return "Tier A", "Generic ML / Data Science"

    # 4. Tier C checks (Backend with AI)
    if any(k in title_low for k in ["python", "backend", "full stack", "software engineer", "mlops"]):
        has_ai = any(k in t_clean for k in ["ai", "ml", "machine learning", "llm", "model", "fastapi", "django"])
        if has_ai:
            return "Tier C", "Backend / Full-stack with AI"

    return "reject", "Generic ML / Data Science"


def is_experience_eligible(jd: JDParsed, role_tier: str) -> Tuple[bool, str]:
    """
    Experience rule update:
    - Accept 0-1, 0-2, 0-3 years preferred and fresher/graduate/trainee/associate roles.
    - Accept 1-2 years only if Tier A/B and JD says 'or equivalent project experience' or lists must-haves met.
    - Reject 2+ minimum, 3+, and senior/lead/staff/principal/manager titles.
    """
    role_lower = jd.role.lower()
    seniority_lower = jd.seniority.lower()

    # Reject senior titles unless they contain intern/trainee/fresher
    senior_keywords = ["senior", "sr.", "sr ", "lead", "staff", "principal", "architect", "manager", "director", "head of", "vp"]
    is_senior = any(sk in role_lower for sk in senior_keywords) and not any(ok in role_lower for ok in ["junior", "intern", "associate", "trainee"])
    if is_senior or "senior" in seniority_lower or "lead" in seniority_lower:
        return False, f"Role '{jd.role}' indicates senior/lead tier."

    combined = " ".join([jd.role, jd.seniority] + jd.must_have_skills + jd.keywords + jd.responsibilities).lower()

    # Check for strict 3+ years minimum
    if re.search(r'\b[3-9]\+?\s*(?:to\s*[0-9]+\s*)?years?\b', combined) or re.search(r'\b(?:minimum|at least)\s*[3-9]\s*years?\b', combined):
        return False, "Requires 3+ years minimum experience."

    # Check for strict 2+ years minimum
    min_2y = re.search(r'\b(?:minimum|at least)\s*2\s*years?\b', combined) or re.search(r'\b2\+?\s*years?\b', combined)
    if min_2y:
        # Check if 1-2 or 0-2 or 0-3 preferred
        if re.search(r'\b0\s*[-–to]\s*[123]\s*years?\b', combined) or "preferred" in combined:
            return True, "Eligible (0-2/0-3 years preferred range)."
        if role_tier in ["Tier A", "Tier B"] and ("project experience" in combined or "equivalent" in combined or "fresher" in combined):
            return True, "Eligible (Tier A/B with project experience clause)."
        return False, "Requires 2+ years minimum experience."

    return True, "Meets fresher / 0-1 year experience criteria."


def compute_match_score(
    jd: JDParsed,
    master: MasterResume,
    threshold: float = 65.0
) -> MatchResult:
    """
    Computes weighted score:
    score = 45% weighted must-have coverage + 15% nice-to-have coverage + 20% role-tier bonus (A=100, B=80, C=55) + 20% Gemini semantic fit
    Seniority or location failures force 0.
    """
    # 1. Classify Tier and Lens
    role_tier, role_lens = classify_role(jd.role, " ".join(jd.must_have_skills + jd.responsibilities + jd.keywords))

    # Reject early if completely off-domain
    if role_tier == "reject":
        return MatchResult(
            match_score=0.0,
            matched_skills=[],
            missing_skills=jd.must_have_skills,
            rationale=f"Disqualified: Role '{jd.role}' does not match target AI/ML profile.",
            meets_threshold=False,
            role_tier="reject",
            role_lens=role_lens
        )

    # 2. Check Experience eligibility
    exp_ok, exp_reason = is_experience_eligible(jd, role_tier)
    if not exp_ok:
        return MatchResult(
            match_score=0.0,
            matched_skills=[],
            missing_skills=jd.must_have_skills,
            rationale=f"Disqualified: {exp_reason}",
            meets_threshold=False,
            role_tier=role_tier,
            role_lens=role_lens
        )

    # 3. Flatten Master Skills
    master_skills = set()
    for cat_list in master.skills.values():
        for s in cat_list:
            master_skills.add(s.strip().lower())
    for exp in master.experience:
        for b in exp.bullets:
            for w in b.text.lower().split():
                if len(w) > 3:
                    master_skills.add(w.strip(",.;()"))

    # 4. Must-have Coverage (Weighted, 45%)
    must_haves = jd.must_have_skills or jd.keywords or ["Python"]
    matched_must = []
    missing_must = []
    total_must_weight = 0.0
    matched_must_weight = 0.0

    for s in must_haves:
        w = get_skill_weight(s)
        total_must_weight += w
        if any(are_skills_synonyms(s, m) for m in master_skills):
            matched_must.append(s)
            matched_must_weight += w
        else:
            missing_must.append(s)

    must_coverage = (matched_must_weight / max(total_must_weight, 1.0)) * 100.0

    # 5. Nice-to-have Coverage (15%)
    nice_haves = jd.nice_to_have_skills
    matched_nice = []
    if nice_haves:
        for s in nice_haves:
            if any(are_skills_synonyms(s, m) for m in master_skills):
                matched_nice.append(s)
        nice_coverage = (len(matched_nice) / len(nice_haves)) * 100.0
    else:
        nice_coverage = must_coverage  # Fallback to must-have coverage if no nice-to-haves listed

    # 6. Role-tier Bonus (20%)
    tier_bonuses = {"Tier A": 100.0, "Tier B": 80.0, "Tier C": 55.0, "reject": 0.0}
    tier_score = tier_bonuses.get(role_tier, 0.0)

    # 7. Semantic Fit (20%)
    # Use deterministic semantic estimate or LLM if survivor
    semantic_fit = (must_coverage * 0.7) + (tier_score * 0.3)
    if must_coverage > 40.0:
        try:
            prompt = (
                f"Rate fit (0 to 100) for candidate Aswin P T (M.Sc. AI/ML fresher, computer vision & LLM projects) "
                f"for role '{jd.role}' at company with requirements: {', '.join(must_haves[:5])}. "
                f"Return JSON: {{\"semantic_score\": 85, \"rationale\": \"...\"}}"
            )
            raw = generate(prompt, json_mode=True)
            res = json.loads(raw)
            semantic_fit = float(res.get("semantic_score", semantic_fit))
            rationale_text = res.get("rationale", "")
        except Exception:
            rationale_text = f"Matched {len(matched_must)}/{len(must_haves)} must-have skills with {role_tier} alignment."
    else:
        rationale_text = f"Low skill overlap ({len(matched_must)}/{len(must_haves)} matched)."

    # Final Weighted Formula:
    # 45% must-have + 15% nice-to-have + 20% tier-bonus + 20% semantic
    final_score = (0.45 * must_coverage) + (0.15 * nice_coverage) + (0.20 * tier_score) + (0.20 * semantic_fit)
    final_score = round(max(0.0, min(100.0, final_score)), 1)

    meets_threshold = (final_score >= threshold) and (role_tier != "reject")

    rationale = f"{role_tier} ({role_lens}): {rationale_text}"

    return MatchResult(
        match_score=final_score,
        matched_skills=matched_must + matched_nice,
        missing_skills=missing_must,
        rationale=rationale,
        meets_threshold=meets_threshold,
        role_tier=role_tier,
        role_lens=role_lens
    )
