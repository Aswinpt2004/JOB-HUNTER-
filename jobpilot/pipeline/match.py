import json
import logging
import re
from typing import Dict, Any, List, Set, Tuple, Optional
from jobpilot.core.config import settings
from jobpilot.core.models import MatchResult, MasterResume
from jobpilot.core.llm import generate
from jobpilot.core.db import log_event

logger = logging.getLogger("jobpilot.pipeline.match")

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

SKILL_WEIGHTS: Dict[str, float] = {
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
    "git": 1.0,
    "linux": 1.0,
    "sql": 1.0,
    "numpy": 1.0,
    "pandas": 1.0,
    "scikit-learn": 1.0,
}


def clean_skill_string(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r'[\(\)\[\]\{\}\/\\,;]', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def are_skills_equivalent(skill1: str, skill2: str) -> bool:
    s1 = clean_skill_string(skill1)
    s2 = clean_skill_string(skill2)
    if not s1 or not s2:
        return False
    if s1 == s2 or s1 in s2 or s2 in s1:
        return True
    for group in SYNONYM_GROUPS:
        in_1 = any(clean_skill_string(syn) in s1 or s1 in clean_skill_string(syn) for syn in group)
        in_2 = any(clean_skill_string(syn) in s2 or s2 in clean_skill_string(syn) for syn in group)
        if in_1 and in_2:
            return True
    return False


def classify_role_tier_and_lens(title: str, description: str = "") -> Tuple[str, str]:
    """Classifies job into role tier (Tier A, Tier B, Tier C, reject) and chooses optimal lens."""
    t_clean = f"{title} {description}".lower()
    title_low = title.lower()

    # Reject non-technical or management roles
    for neg in ["sales", "marketing", "recruiter", "hr manager", "accountant", "graphic designer"]:
        if neg in title_low:
            return "reject", "Generic ML / Data Science"

    # Computer Vision / Drone / Surveillance Lens
    if any(k in t_clean for k in ["computer vision", "opencv", "yolo", "rt-detr", "tracking", "bytetrack", "drone", "uav", "surveillance", "video analytics", "image processing", "csrnet"]):
        return "Tier A", "Computer Vision / Drone / Aerial Perception"

    # LLM / RAG / Agentic AI Lens
    if any(k in t_clean for k in ["llm", "rag", "retrieval augmented", "langchain", "llamaindex", "gemini", "agentic", "agent", "prompt engineering", "vector database", "chromadb"]):
        return "Tier A", "LLM Applications / RAG / Agentic AI"

    # Document AI / OCR Lens
    if any(k in t_clean for k in ["ocr", "document ai", "idp", "document extraction", "tesseract", "layoutlm"]):
        return "Tier B", "Document AI / OCR / Information Extraction"

    # Federated / GNN Lens
    if any(k in t_clean for k in ["federated learning", "gnn", "graph neural", "flower", "graph ml"]):
        return "Tier B", "Federated Learning / Graph Neural Networks"

    # Python Backend / FastAPI Lens
    if any(k in t_clean for k in ["fastapi", "python backend", "backend developer", "python developer", "django", "rest api"]):
        return "Tier C", "Python Backend / FastAPI / Scalable Systems"

    # General Machine Learning
    if any(k in t_clean for k in ["machine learning", "deep learning", "ai engineer", "data science", "pytorch", "tensorflow"]):
        return "Tier B", "Generic ML / Data Science"

    return "Tier C", "Generic ML / Data Science"


def calculate_match_score(
    jd_skills: List[str],
    candidate_skills: Set[str],
    role_tier: str
) -> Tuple[float, List[str], List[str]]:
    """Calculates weighted match score between 0.0 and 100.0."""
    if not jd_skills:
        # Fallback based on tier
        tier_scores = {"Tier A": 85.0, "Tier B": 78.0, "Tier C": 70.0, "reject": 40.0}
        return tier_scores.get(role_tier, 65.0), list(candidate_skills)[:5], []

    matched: List[str] = []
    missing: List[str] = []
    total_weight = 0.0
    matched_weight = 0.0

    for skill in jd_skills:
        w = 1.0
        s_clean = clean_skill_string(skill)
        for kw, weight in SKILL_WEIGHTS.items():
            if kw in s_clean:
                w = weight
                break
        total_weight += w

        is_matched = any(are_skills_equivalent(skill, cs) for cs in candidate_skills)
        if is_matched:
            matched.append(skill)
            matched_weight += w
        else:
            missing.append(skill)

    score = (matched_weight / total_weight * 100.0) if total_weight > 0 else 75.0
    return round(score, 1), matched, missing


def evaluate_job_match(
    title: str,
    description: str,
    master_skills: Set[str]
) -> MatchResult:
    role_tier, role_lens = classify_role_tier_and_lens(title, description)
    # Extract naive keyword skills from description
    extracted_skills = []
    desc_clean = description.lower()
    for kw in SKILL_WEIGHTS.keys():
        if kw in desc_clean:
            extracted_skills.append(kw)

    score, matched, missing = calculate_match_score(extracted_skills, master_skills, role_tier)
    meets = score >= settings.min_match_score and role_tier != "reject"

    return MatchResult(
        match_score=score,
        matched_skills=matched,
        missing_skills=missing,
        rationale=f"Role evaluated as {role_tier} with lens '{role_lens}'. Found {len(matched)} matching skill areas.",
        meets_threshold=meets,
        role_tier=role_tier,
        role_lens=role_lens
    )

