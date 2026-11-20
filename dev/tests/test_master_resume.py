import json
from pathlib import Path
import pytest
from src.models import MasterResume
from src.config import settings


def test_master_resume_loading_and_structure():
    resume_path = settings.master_resume_path
    assert Path(resume_path).exists(), f"Missing master resume file at {resume_path}"

    with open(resume_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    master = MasterResume.model_validate(data)

    # 1. Assert 2 experiences
    assert len(master.experience) == 2, f"Expected 2 experiences, got {len(master.experience)}"
    assert master.experience[0].company == "Quantumweave Intelligence"
    assert master.experience[1].company == "Synbrains Solutions Pvt Ltd"

    # 2. Assert 7 projects
    assert len(master.projects) == 7, f"Expected 7 projects, got {len(master.projects)}"
    expected_projects = [
        "AI-Powered E-Commerce Storefront & Catalog Generation Agent",
        "KuTo: Kerala-First Managed Booking Marketplace",
        "Manglish WhatsApp Chatbot (RAG with Llama-3 / Ollama)",
        "FedGraph-Shield: Hierarchical Federated Graph Learning for Financial Fraud Detection",
        "Adaptive Confidence Modeling for SHADER-Based 3D Human Body Shape Estimation",
        "Dynamic Connectome Prediction of Reality Monitoring Failure Under Sleep Deprivation",
        "PETZZO: Comprehensive Pet Care Platform"
    ]
    actual_project_names = [p.name for p in master.projects]
    assert actual_project_names == expected_projects

    # 3. Assert 6 skill groups
    assert len(master.skills) == 6, f"Expected 6 skill groups, got {len(master.skills)}"
    expected_skill_groups = [
        "Programming",
        "GenAI & Agents",
        "Data & Experimentation",
        "Backend & Integration",
        "Data & Cloud",
        "ML & Evaluation"
    ]
    assert list(master.skills.keys()) == expected_skill_groups

    # 4. Assert every experience bullet has an id
    for exp in master.experience:
        for b in exp.bullets:
            assert b.id is not None and b.id.strip() != "", f"Experience bullet missing id: {b}"
            assert len(b.text.strip()) > 0

    # 5. Assert every project bullet has an id
    for proj in master.projects:
        for b in proj.bullets:
            assert b.id is not None and b.id.strip() != "", f"Project bullet missing id: {b}"
            assert len(b.text.strip()) > 0

    # 6. Assert summary facts exist
    assert len(master.summary_facts) >= 5, "Expected at least 5 summary facts"

