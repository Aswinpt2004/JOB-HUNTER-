# ✈️ JobPilot: Autonomous Local Job Discovery & Tailored Application Assistant

JobPilot is a local, privacy-focused, zero-paid-API automation assistant built with Python 3.11+. It monitors public job boards, scores postings against your master resume, extracts public recruiter contacts, strictly tailors ATS-compliant resumes and personalized cold emails, and dispatches them **only after your explicit human approval**.

---

## 🎯 Key Features & Guarantees
- **100% Free Stack**: Uses Google Gemini's free tier, Gmail SMTP, and open-source scraping/rendering libraries. No paid subscriptions or SaaS dependencies.
- **Strict Human Approval & Optional Auto-Pilot**: Default mode is Review Queue (nothing sent without click). Auto-Pilot mode (`auto-apply`) can be triggered when you want qualified jobs tailored and dispatched automatically.
- **Token Protection & Anti-Waste Guardrails**:
  - **SQLite Cache**: SHA-256 prompt hashing guarantees identical JDs/prompts are never sent to Gemini twice (0 duplicate tokens).
  - **Smart Short-Circuit**: Irrelevant scraped postings with 0 skill overlap skip LLM evaluation entirely, saving thousands of tokens.
  - **JD Boilerplate Truncation**: Automatically caps raw JD text at 3,000 characters, stripping legal and cookie disclaimers before LLM calls.
  - **Daily Quota Ceiling**: Hard daily limit (default: 250 requests, 350k tokens) ensures you never exceed Google's 1,500 RPD / 1M TPM free limits.
  - **Live Pacing**: Enforces minimum 4.0-second delay between consecutive live calls, staying strictly under 15 requests per minute (RPM) to prevent HTTP 429 rate limits.
- **Zero-Fabrication Verifier**: The master resume (`data/master_resume.json`) is the single source of truth. The system enforces an automated post-generation verification step that strips or flags any fabricated skills, employers, metrics, or degrees.
- **Ethical & Anti-Spam Guardrails**:
  - Respects `robots.txt` and uses polite 2–5s delays.
  - Never scrapes LinkedIn, Naukri, or Indeed.
  - Extracts only publicly listed business/recruiter emails with MX domain verification via `dnspython`.
  - Enforces a 15 email/day cap, 30-day company/email cooldown, local business hours window (9 AM – 6 PM), and permanent opt-out blocklisting.
  - Mandatory opt-out line included in every cold email.
  - At most **one** 6-day polite follow-up.

---

## 🏗️ Architecture & Project Structure
```text
jobpilot/
├── config.yaml                 # User profile, search keywords, company slugs, sending caps
├── .env.example                # Template for Gemini API key & Gmail credentials
├── .gitignore                  # Keeps local database, PDFs, and secrets private
├── requirements.txt            # Python dependencies
├── README.md                   # Setup, usage, and operations guide
├── data/
│   ├── master_resume.json      # Single source of truth for candidate details
│   └── jobpilot.db             # Local SQLite database (auto-created on first run)
├── templates/
│   ├── resume.html             # ATS-optimized single-column resume template
│   └── email_prompt.txt        # Cold email prompt template
├── output/
│   └── resumes/                # Generated tailored ATS PDFs and JSONs
├── src/
│   ├── __init__.py
│   ├── config.py               # YAML & environment variable loader
│   ├── db.py                   # SQLite schema, indices & CRUD functions
│   ├── models.py               # Pydantic data schemas
│   ├── llm.py                  # Gemini unified generator with cache & exponential backoff
│   ├── jd_parser.py            # Extracts role, skills, keywords, and instructions
│   ├── matcher.py              # Hybrid deterministic + semantic fit score (0-100)
│   ├── resume_tailor.py        # Strict no-fabrication tailor & verification engine
│   ├── pdf_builder.py          # ATS-friendly PDF generation (xhtml2pdf / WeasyPrint / python-docx)
│   ├── email_writer.py         # Concise, non-salesy 100-150 word application email generator
│   ├── contacts.py             # Public recruiter contact finder & MX validation
│   ├── scrapers/               # Polite job board crawlers
│   │   ├── base.py             # Base crawler with delays and deduplication
│   │   ├── greenhouse.py       # Greenhouse public boards API
│   │   ├── lever.py            # Lever public postings API
│   │   ├── remotive.py         # Remotive public API
│   │   └── career_page.py      # Generic career page scraper with Playwright fallback
│   ├── sender.py               # Gmail SMTP dispatcher with rate-limits & guardrails
│   ├── followup.py             # 6-day follow-up tracker & blocklist manager
│   └── pipeline.py             # CLI orchestrator with --dry-run
├── app.py                      # Streamlit interactive human-review dashboard
└── tests/                      # Pytest unit test suite
    ├── test_jd_parser.py
    ├── test_verifier.py
    ├── test_contacts.py
    ├── test_dedupe.py
    └── test_sender_cap.py
```

---

## 🚀 Installation & Setup Guide

### 1. Prerequisites
- **Python 3.11+** installed ([python.org](https://www.python.org/downloads/)).
- Git installed.

### 2. Set Up Virtual Environment (Windows)
Open PowerShell in the project directory:
```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Upgrade pip and install dependencies
pip install -r requirements.txt
```
*(If using `uv`: `uv venv venv` and `uv pip install -r requirements.txt --python .\venv\Scripts\python.exe`)*

### 3. Configure API Key & Credentials
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Open `.env` in any text editor and fill in:

#### A. Free Google Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google Account and click **Get API Key**.
3. Create a free API key and paste it:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```
*(Note: JobPilot comes equipped with automated model cascading across `gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3.7-flash`, and `gemini-3.8-flash` so if a free-tier model encounters temporary quota limits, it seamlessly transitions to the next active model without interrupting your workflow).*

#### B. Free Gmail App Password (for Human-Approved Sending)
1. Go to your [Google Account Security Settings](https://myaccount.google.com/security).
2. Ensure **2-Step Verification** is turned ON.
3. Search for or navigate to [App Passwords](https://myaccount.google.com/apppasswords).
4. Create a new App Password called `JobPilot`.
5. Copy the 16-character generated code and paste it into `.env`:
   ```env
   GMAIL_USER=your_email@gmail.com
   GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
   ```

### 4. Fill Your Master Resume
Edit `data/master_resume.json` with your real background. This file is your **single source of truth**:
- **contact**: Name, email, phone, location, LinkedIn, GitHub, portfolio.
- **summary**: Your core elevator pitch.
- **skills**: Categorized lists of your real languages, frameworks, databases, and tools.
- **experience**: Work history with bullet points highlighting your accomplishments.
- **projects**: Key projects with technologies, links, and bullets.
- **education**: Degree, institution, graduation year.
- **certifications**: Any genuine professional certifications.

### 5. Tune `config.yaml`
Customize `config.yaml` with your preferred target roles, locations, keywords, and Greenhouse/Lever board slugs:
```yaml
search_filters:
  keywords:
    - "python"
    - "backend"
    - "fastapi"
  min_match_score: 65

sending:
  daily_cap: 15
  sending_hours_start: 9
  sending_hours_end: 18
  cooldown_days_per_company: 30
  followup_days: 6
```

---

## 🖥️ Running the Application

### 1. Interactive Streamlit Dashboard (Recommended)
Launch the human-in-the-loop dashboard:
```powershell
.\venv\Scripts\python -m streamlit run app.py
```
This opens `http://localhost:8501` in your browser. From here you can:
- **Scrape, Match & Tailor** with single-click sidebar buttons.
- Toggle **Dry-Run Mode** on/off.
- View **Review Queue**: preview the tailored ATS PDF, read the match breakdown, edit the personalized email draft, and click **Approve** or **Send Now**.
- Track **Sent Applications** and mark recruiter replies.
- Review and trigger **Follow-ups** after 6 days.
- Manage the permanent **Blocklist** and audit logs.

### 2. Command-Line Interface (CLI Pipeline)
You can run individual stages or schedule them:
```powershell
# Scrape new job openings from public APIs & career boards
.\venv\Scripts\python -m src.pipeline scrape

# Match discovered jobs against your master resume
.\venv\Scripts\python -m src.pipeline match --threshold 65

# Tailor ATS resumes (PDF + JSON) and draft cold emails
.\venv\Scripts\python -m src.pipeline draft

# Run Scrape -> Match -> Draft in one safe pass (never auto-sends)
.\venv\Scripts\python -m src.pipeline run-all

# Simulate execution with the --dry-run flag
.\venv\Scripts\python -m src.pipeline run-all --dry-run

# Dispatch human-approved applications via Gmail SMTP
.\venv\Scripts\python -m src.pipeline send-approved

# Check and draft 6-day follow-ups
.\venv\Scripts\python -m src.pipeline followups
```

---

## ⏰ Scheduling Automated Scans

### Windows Task Scheduler
To run `run-all` daily at 8:00 AM:
1. Open **Task Scheduler** in Windows (`taskschd.msc`).
2. Click **Create Basic Task...** and name it `JobPilot Daily Scan`.
3. Set Trigger to **Daily** at `08:00 AM`.
4. Set Action to **Start a program**:
   - **Program/script**: `D:\project JOB HUNT\venv\Scripts\python.exe`
   - **Add arguments**: `-m src.pipeline run-all`
   - **Start in**: `D:\project JOB HUNT`
5. Finish. Every morning, your review queue will be pre-populated with matched, drafted jobs ready for your morning review in Streamlit.

### Linux / macOS Cron
Add this entry to your crontab (`crontab -e`):
```bash
0 8 * * * cd "/path/to/jobpilot" && ./venv/bin/python -m src.pipeline run-all >> logs/cron.log 2>&1
```

---

## 🧪 Running Unit Tests
Execute the test suite to verify the parser, no-fabrication verifier, contacts extractor, deduplication, and sending guardrails:
```powershell
.\venv\Scripts\pytest -v
```

---

## ⚠️ Known Limitations & Best Practices

1. **Recruiter Email Availability**: Not all companies list public recruiter emails in job postings. For postings without public emails, JobPilot marks them as **"apply via link"** and will not attempt to guess emails or cold-email them.
2. **WeasyPrint on Windows**: WeasyPrint requires native GTK/Pango C libraries. JobPilot automatically utilizes `xhtml2pdf` and `python-docx` as native zero-configuration fallbacks on Windows, ensuring reliable single-column ATS document generation.
3. **Gemini Free Tier Quota**: The free tier of Gemini allows up to 15 requests per minute (RPM). JobPilot automatically hashes and caches every prompt and response in SQLite to prevent duplicate calls, and implements exponential backoff to handle HTTP 429 rate limits gracefully.
4. **Gmail Sending Limits**: Free Gmail accounts have a sending limit of 500 emails/day, but for job hunting etiquette, JobPilot defaults to a conservative **15 emails/day cap** to ensure deliverability and avoid spam classification.
5. **Human Inspection Recommended**: Always take 30 seconds in the Review Queue to glance over the tailored resume and email draft before clicking Send. Customizing a sentence with a specific detail about the company's recent work yields significantly higher response rates.

