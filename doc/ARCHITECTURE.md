# JobPilot v2: Architecture Specification

## 1. Executive Summary & Goals

JobPilot v2 is an agentic, multi-source job search and application assistant tailored specifically for **Aswin P T** (Fresher AI/ML Engineer, 0–1 year experience; target locations: Bangalore, Thiruvananthapuram, Kochi, Kozhikode, and Remote India).

Unlike legacy scrapers that only target emails, JobPilot v2 discovers jobs across structured aggregator APIs, ATS feeds, regional IT park portals, and direct career pages. It maps every job to the optimal legal and permitted application route:
1. **Cold HR Outreach (`email`)**: Gmail SMTP SSL:465 with tailored 2-page PDF and MX verification.
2. **ATS Assist (`ats_assist`)**: Playwright visible browser assistant that pre-fills profile answers and uploads resume, stopping for human review before submission.
3. **Assisted Apply Packet (`packet`)**: Copyable packet for LinkedIn, Naukri, and Indeed (zero bot automation to protect candidate accounts).

---

## 2. Directory Structure

```
d:\project JOB HUNT\
├── jobpilot/
│   ├── app/                    # FastAPI web server and SSE progress
│   │   ├── main.py             # App lifecycle, routing, static/output mounts
│   │   ├── api.py              # REST API & SSE streaming endpoints
│   │   └── ui/
│   │       ├── templates/      # Jinja2 templates (10 full-featured screens)
│   │       └── static/         # Local Tailwind CSS, Alpine.js, HTMX (zero CDN)
│   ├── core/                   # Shared infrastructure
│   │   ├── config.py           # Typed settings from config.yaml & .env
│   │   ├── db.py               # SQLite connection, CRUD, caching, migrations
│   │   ├── models.py           # Pydantic v2 schemas
│   │   ├── llm.py              # Gemini client with quota caps and SHA-256 cache
│   │   ├── events.py           # Async pub-sub Server-Sent Events (SSE) broadcaster
│   │   └── scheduler.py        # APScheduler in-process background worker (Asia/Kolkata)
│   ├── sources/                # Pluggable multi-source discovery plugins
│   │   ├── base.py             # BaseSource ABC and registry pattern
│   │   ├── adzuna.py           # Adzuna API (India)
│   │   ├── jooble.py           # Jooble API (India)
│   │   ├── careerjet.py        # Careerjet API (India)
│   │   ├── jsearch.py          # RapidAPI Google-for-Jobs aggregator
│   │   ├── remotive.py         # Remotive remote dev & data API
│   │   ├── arbeitnow.py        # Arbeitnow remote job board API
│   │   ├── ats.py              # Direct feeds (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)
│   │   ├── kerala_parks.py     # Technopark TVM and Infopark Kochi crawlers
│   │   ├── company_careers.py  # Regional tech firm career pages
│   │   └── manual.py           # URL scraper and JD paste import
│   ├── pipeline/               # Ingestion & normalization pipeline
│   │   ├── normalize.py        # Title and salary cleaner
│   │   ├── prescreen.py        # Zero-token senior/experience filter
│   │   ├── location.py         # 5-city + Remote India normalizer & foreign rejector
│   │   ├── dedupe.py           # Canonical key + SequenceMatcher deduplication
│   │   ├── route.py            # Apply route classifier & recruiter email extractor
│   │   ├── contacts.py         # Email extraction and DNS MX verification
│   │   └── match.py            # 6-lens classifier & weighted skill matcher
│   ├── tailor/                 # Fit engine & document generators
│   │   ├── resume_tailor.py    # Master resume pool lens selector
│   │   ├── verifier.py         # Anti-hallucination zero-fabrication verifier
│   │   ├── pdf_builder.py      # xhtml2pdf & PyMuPDF 93-100% 2-page fit engine
│   │   ├── cover_note.py       # Concise 60-100 word ATS cover note generator
│   │   └── email_writer.py     # Cold email generator with tone critic & mandatory opt-out
│   └── apply/                  # Multi-route execution layer
│       ├── email_sender.py     # Gmail SSL 465 sender with IST window & daily cap
│       ├── ats_assist.py       # Playwright visible pre-fill assistant
│       └── packet.py           # Assisted Apply Packet markdown/JSON generator
├── data/                       # Local data storage
│   ├── answers.json            # Candidate profile screener answers
│   ├── master_resume.json      # Single source of truth resume pool
│   └── jobpilot.db             # SQLite database (migrated to v2 schema)
├── dev/tests/                  # Automated pytest test suite (137 tests passing)
├── output/                     # Generated tailored resumes & packets
│   ├── resumes/                # 2-page PDFs
│   └── packets/                # Markdown apply packets
├── run.bat                     # Windows 1-click startup script
└── run.sh                      # Linux/macOS startup script
```

---

## 3. Core Principles & Safeguards

1. **Local-First & 100% Free Stack**:
   - Runs locally on `http://127.0.0.1:8000`.
   - SQLite for persistence.
   - Google Gemini free tier with auto-fallback between `gemini-3.5-flash-lite` and `gemini-3.8-flash`.
   - Local CSS and JS: no external CDN dependencies at runtime.

2. **Hard Sending Safeguards**:
   - **Daily Cap**: Max 15 cold emails per calendar day.
   - **Business Hours Window**: 09:00 — 18:00 IST (Asia/Kolkata).
   - **Pacing**: 60 to 180 seconds randomized delay between dispatches.
   - **Company Cooldown**: 30 days per company before any repeat outreach.
   - **Follow-up Limit**: Exactly one polite follow-up sent after 6+ days of no reply.
   - **Mandatory Opt-Out**: Every email ends with: *"If this isn't the right contact, let me know and I won't follow up."*

3. **Safe Third-Party Platform Policies**:
   - **LinkedIn, Naukri, Indeed**: Zero headless bot logins or auto-clicks. Only Assisted Apply Packets are generated, leaving the candidate in complete control.
   - **ATS Portals**: Playwright visible assistant fills form fields and attaches resume in a real browser, pausing for human review.

4. **Zero-Fabrication Verifier**:
   - Every skill, tool, company, and date in tailored resumes is grounded against `master_resume.json`.
   - Any hallucinated terms are automatically stripped before PDF rendering.
