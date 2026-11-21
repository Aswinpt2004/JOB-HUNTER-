from datetime import datetime
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator


class RawJob(BaseModel):
    title: str
    company: str
    location: str = "Remote"
    url: str
    description: str = ""
    source: str = "manual"
    source_job_id: Optional[str] = None
    posted_date: Optional[str] = None
    salary: Optional[str] = None
    recruiter_email: Optional[str] = None
    apply_url: Optional[str] = None
    apply_kind: str = "unknown"
    easy_apply: bool = False


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
    canonical_key: Optional[str] = None
    location_norm: Optional[str] = None
    location_raw: Optional[str] = None
    posted_at: Optional[datetime] = None
    salary: Optional[str] = None
    apply_url: Optional[str] = None
    apply_kind: str = "unknown"  # email | ats_greenhouse | ats_lever | ats_ashby | ats_workable | ats_smartrecruiters | linkedin | naukri | indeed | company_form | unknown
    easy_apply: int = 0
    source_names: Union[List[str], str] = Field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    is_active: int = 1
    created_at: Optional[datetime] = None


class Application(BaseModel):
    id: Optional[int] = None
    job_id: str
    status: str = "new"  # 'new', 'drafted', 'approved', 'sending', 'emailed', 'applied', 'replied', 'interview', 'offer', 'rejected', 'skipped'
    match_score: Optional[float] = None
    resume_path: Optional[str] = None
    tailored_json_path: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    sent_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    followup_sent_at: Optional[datetime] = None
    recipient_email: Optional[str] = None
    rationale: Optional[str] = None
    role_tier: Optional[str] = None
    role_lens: Optional[str] = None
    route: str = "email"  # 'email', 'ats_assist', 'packet'
    cover_note: Optional[str] = None
    packet_path: Optional[str] = None
    tone_score: float = 10.0
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RecruiterContact(BaseModel):
    id: Optional[int] = None
    job_id: Optional[str] = None
    company_id: Optional[int] = None
    email: str
    name: Optional[str] = None
    role: Optional[str] = "Recruiter / Hiring Team"
    source_type: str = "jd_text"  # 'jd_text', 'contact_page', 'careers_page', 'portal_listing', 'company_crawl'
    verified: bool = False
    domain_mx_valid: bool = False


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
    size_status: str = "unknown"
    field_tags: List[str] = Field(default_factory=list)
    field_fit_score: float = 0.0
    hiring_signal_score: float = 0.0
    company_score: float = 0.0
    tier: str = "C"
    discovered_via: Optional[str] = "manual"
    last_checked: Optional[datetime] = None
    status: str = "new"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CompanySignal(BaseModel):
    id: Optional[int] = None
    company_id: int
    signal_type: str
    value: str
    source_url: Optional[str] = None
    weight: float = 1.0
    captured_at: Optional[datetime] = None


class CompanyOutreach(BaseModel):
    id: Optional[int] = None
    company_id: int
    contact_id: Optional[int] = None
    mode: str = "speculative"
    resume_path: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    status: str = "drafted"
    sent_at: Optional[datetime] = None
    followup_due: Optional[datetime] = None
    followup_sent: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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


class ResumeExperienceItem(BaseModel):
    company: str
    role: str
    location: Optional[str] = ""
    start_date: Optional[str] = ""
    end_date: Optional[str] = ""
    dates: Optional[str] = ""
    bullets: List[ResumeBullet] = Field(default_factory=list)

    @field_validator("bullets", mode="before")
    def parse_bullets(cls, v):
        if isinstance(v, list):
            return [ResumeBullet.from_item(b) for b in v]
        return v


ResumeExperience = ResumeExperienceItem


class ResumeProjectItem(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = ""
    title: Optional[str] = ""
    technologies: List[str] = Field(default_factory=list)
    tech_stack: Union[str, List[str]] = Field(default_factory=list)
    description: Optional[str] = ""
    dates: Optional[str] = ""
    bullets: List[ResumeBullet] = Field(default_factory=list)
    link: Optional[str] = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.name and self.title:
            self.name = self.title
        elif not self.title and self.name:
            self.title = self.name
        if not self.technologies and self.tech_stack:
            if isinstance(self.tech_stack, list):
                self.technologies = self.tech_stack
            elif isinstance(self.tech_stack, str):
                self.technologies = [t.strip() for t in self.tech_stack.split("&middot;") if t.strip()]

    @field_validator("bullets", mode="before")
    def parse_bullets(cls, v):
        if isinstance(v, list):
            return [ResumeBullet.from_item(b) for b in v]
        return v


ResumeProject = ResumeProjectItem


class ResumeEducationItem(BaseModel):
    institution: str
    degree: str
    field_of_study: Optional[str] = ""
    graduation_year: Optional[str] = ""
    location: Optional[str] = ""
    gpa: Optional[str] = ""
    dates: Optional[str] = ""
    bullets: List[ResumeBullet] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.dates and self.graduation_year:
            self.dates = self.graduation_year

    @field_validator("bullets", mode="before")
    def parse_bullets(cls, v):
        if isinstance(v, list):
            return [ResumeBullet.from_item(b) for b in v]
        return v


ResumeEducation = ResumeEducationItem



class TailoredResume(BaseModel):
    contact: ResumeContactInfo
    headline: str
    summary: str
    skills: Dict[str, Union[List[str], str]]
    experience: List[ResumeExperienceItem]
    projects: List[ResumeProjectItem]
    education: List[ResumeEducationItem]
    coursework: Optional[List[str]] = Field(default_factory=list)
    achievements: Optional[List[str]] = Field(default_factory=list)
    certifications: Optional[List[str]] = Field(default_factory=list)
    lens: Optional[str] = "Generic ML / Data Science"
    target_tier: Optional[str] = "Tier A"
    match_score: Optional[float] = 0.0


class MasterResume(BaseModel):
    contact: ResumeContactInfo
    canonical_skills: Dict[str, List[str]]
    experience_pool: List[Dict[str, Any]]
    project_pool: List[Dict[str, Any]]
    education: List[ResumeEducationItem]
    coursework: List[str]
    achievements: List[str]
    certifications: List[str]
    lenses: Dict[str, Dict[str, Any]]

