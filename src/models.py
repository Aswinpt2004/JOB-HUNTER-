from datetime import datetime
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator


class Job(BaseModel):
    id: str
    title: str
    company: str
    location: str = "Remote"
    url: str
    description: str
    posted_date: Optional[str] = None
    source: str = "manual"
    recruiter_email: Optional[str] = None
    role_tier: Optional[str] = None  # 'Tier A', 'Tier B', 'Tier C', 'reject'
    role_lens: Optional[str] = None  # CV/Drone, LLM/RAG, Document AI, Federated/Graph, Backend, Generic
    company_id: Optional[int] = None
    created_at: Optional[datetime] = None


class Company(BaseModel):
    id: Optional[int] = None
    name: str
    domain: Optional[str] = None
    website: Optional[str] = None
    careers_url: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    hq_country: Optional[str] = "India"
    employee_min: Optional[int] = None
    employee_max: Optional[int] = None
    employee_estimate: Optional[int] = None
    size_confidence: float = 0.0
    size_source: Optional[str] = None
    size_evidence: Optional[str] = None
    size_status: str = "unknown"  # confirmed_20plus | likely_20plus | unknown | under_20
    field_tags: List[str] = Field(default_factory=list)
    field_fit_score: float = 0.0
    hiring_signal_score: float = 0.0
    company_score: float = 0.0
    tier: str = "C"  # A | B | C | excluded
    discovered_via: Optional[str] = "manual"
    last_checked: Optional[datetime] = None
    status: str = "new"  # new | active | not_relevant | excluded
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CompanySignal(BaseModel):
    id: Optional[int] = None
    company_id: int
    signal_type: str  # field_keyword | open_role | tech_blog | github | funding | team_page | park_directory
    value: str
    source_url: Optional[str] = None
    weight: float = 1.0
    captured_at: Optional[datetime] = None


class CompanyOutreach(BaseModel):
    id: Optional[int] = None
    company_id: int
    contact_id: Optional[int] = None
    mode: str = "speculative"  # job_application | speculative
    resume_path: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    status: str = "drafted"  # drafted | approved | sent | replied | failed | skipped
    sent_at: Optional[datetime] = None
    followup_due: Optional[datetime] = None
    followup_sent: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Application(BaseModel):
    id: Optional[int] = None
    job_id: str
    status: str = "new"  # 'new', 'matched', 'drafted', 'approved', 'sent', 'followed_up', 'skipped'
    match_score: Optional[float] = None
    resume_path: Optional[str] = None
    tailored_json_path: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    sent_at: Optional[datetime] = None
    followup_sent_at: Optional[datetime] = None
    recipient_email: Optional[str] = None
    rationale: Optional[str] = None
    role_tier: Optional[str] = None
    role_lens: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RecruiterContact(BaseModel):
    job_id: Optional[str] = None
    company_id: Optional[int] = None
    email: str
    name: Optional[str] = None
    role: Optional[str] = "Recruiter / Hiring Team"
    source_type: str = "jd_text"  # 'jd_text', 'contact_page', 'careers_page', 'portal_listing', 'company_crawl'
    verified: bool = False
    domain_mx_valid: bool = False


class JDParsed(BaseModel):
    role: str
    seniority: str = "Mid"
    must_have_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    application_instructions: Optional[str] = None


class MatchResult(BaseModel):
    match_score: float = Field(ge=0.0, le=100.0)
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    rationale: str = ""
    meets_threshold: bool = False
    role_tier: str = "reject"
    role_lens: str = "Generic ML / Data Science"


class ResumeContactInfo(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    linkedin: Optional[str] = ""
    github: Optional[str] = ""
    portfolio: Optional[str] = ""


class ResumeBullet(BaseModel):
    id: Optional[str] = None
    text: str

    @classmethod
    def from_item(cls, item: Any) -> "ResumeBullet":
        if isinstance(item, dict):
            return cls(id=item.get("id"), text=item.get("text", ""))
        elif isinstance(item, cls):
            return item
        return cls(id=None, text=str(item))

    def __str__(self) -> str:
        return self.text


class ResumeExperience(BaseModel):
    company: str
    role: str
    location: Optional[str] = ""
    start_date: str
    end_date: str
    bullets: List[ResumeBullet] = Field(default_factory=list)

    @field_validator("bullets", mode="before")
    @classmethod
    def parse_bullets(cls, v):
        if not v:
            return []
        return [ResumeBullet.from_item(b) for b in v]


class ResumeProject(BaseModel):
    id: Optional[str] = None
    name: str
    technologies: List[str] = Field(default_factory=list)
    description: str = ""
    bullets: List[ResumeBullet] = Field(default_factory=list)
    link: Optional[str] = ""

    @field_validator("bullets", mode="before")
    @classmethod
    def parse_bullets(cls, v):
        if not v:
            return []
        return [ResumeBullet.from_item(b) for b in v]


class ResumeEducation(BaseModel):
    institution: str
    degree: str
    field_of_study: str
    graduation_year: str
    location: Optional[str] = ""
    gpa: Optional[str] = ""


class MasterResume(BaseModel):
    contact: ResumeContactInfo
    summary: str
    summary_facts: List[str] = Field(default_factory=list)
    skills: Dict[str, List[str]] = Field(default_factory=dict)  # 6 categories
    experience: List[ResumeExperience] = Field(default_factory=list)
    projects: List[ResumeProject] = Field(default_factory=list)
    education: List[ResumeEducation] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    contact: ResumeContactInfo
    targeted_title: str
    summary: str
    highlighted_skills: Dict[str, List[str]] = Field(default_factory=dict)
    experience: List[ResumeExperience] = Field(default_factory=list)
    projects: List[ResumeProject] = Field(default_factory=list)
    education: List[ResumeEducation] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    matched_skills: List[str] = Field(default_factory=list)
    headline: str = "AI/ML Engineer | Computer Vision & LLM Applications"
    role_lens: str = "Generic ML / Data Science"
    role_tier: str = "Tier A"
    page_fill: Optional[Dict[str, float]] = None
    layout_warning: bool = False
