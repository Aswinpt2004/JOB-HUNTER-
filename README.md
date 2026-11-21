# ✈️ JobPilot v2: Multi-Source Job Search & Application Assistant

JobPilot v2 is a local-first, privacy-preserving job search and application assistant engineered for **Aswin P T** (Fresher AI/ML Engineer, 0–1 yr exp; target locations: Bangalore, Thiruvananthapuram, Kochi, Kozhikode, and Remote India).

It expands from direct HR cold emails into a **multi-source discovery + multi-route application engine**:
1. **Multi-Source Discovery**: Structured Aggregator APIs (Adzuna, Jooble, Careerjet, JSearch), Direct ATS Feeds (Greenhouse, Lever, Ashby, Workable, SmartRecruiters), Kerala IT Parks (Technopark TVM, Infopark Kochi), and Remote Boards (Remotive, Arbeitnow).
2. **Three Permitted Apply Routes**:
   - ✉️ **Cold HR Outreach (`email`)**: Gmail SMTP SSL:465 with tailored 2-page PDF, DNS MX verification, 09:00–18:00 IST sending window, 15/day cap, and 30-day company cooldown.
   - 🤖 **Visible ATS Assist (`ats_assist`)**: Playwright visible Chromium browser pre-fills profile fields from `data/answers.json` and attaches resume, pausing for human review (never auto-submits).
   - 📦 **Assisted Apply Packet (`packet`)**: Prepared application packet for LinkedIn, Naukri, and Indeed (zero bot clicks to protect candidate accounts).
3. **Exact 2-Page Resume Fit Engine**: 6 canonical lenses, zero-fabrication verifier against `master_resume.json`, and dynamic vertical page-fill tuning (93%–100% target fill).
4. **Modern Local UI**: FastAPI + Jinja2 + HTMX + Alpine.js + prebuilt local Tailwind CSS (running on `http://127.0.0.1:8000` with zero runtime CDN). Includes in-process APScheduler and real-time SSE stream.

---

## 🚀 Quickstart

### 1. Requirements
- Python 3.11+
- Google Gemini API key
- Gmail address with 16-character App Password

### 2. Run the Application
On Windows, simply double-click `run.bat` or run:
```powershell
.\venv\Scripts\python.exe -m jobpilot run
```
On Linux/macOS:
```bash
./run.sh
```
Open **`http://127.0.0.1:8000`** in your browser.

---

## 🛠️ CLI Commands

```powershell
# Start web server and scheduler
python -m jobpilot run

# Run multi-source job discovery
python -m jobpilot discover

# Process and send approved queue within IST window
python -m jobpilot send-approved

# System health and pipeline diagnostics
python -m jobpilot diagnose
```

---

## 🔒 Production Safeguards

- **Human Approval**: Every application requires explicit candidate approval before dispatch.
- **Daily Cap**: Max 15 cold emails per calendar day.
- **IST Window**: Dispatches only between 09:00 and 18:00 IST (Asia/Kolkata).
- **Pacing Delay**: Randomized 60 to 180 seconds between dispatches.
- **Company Cooldown**: 30-day blackout period per company.
- **Single Follow-Up**: Exactly one polite follow-up after 6 days.
- **Safe LinkedIn/Naukri/Indeed Policy**: Zero headless bot automation; prepares 1-click copy packets instead.
- **Zero-Fabrication Verifier**: Rejects and sanitizes any technical claim ungrounded in `master_resume.json`.

---

## 🧪 Automated Tests

The test suite contains 137 unit and integration tests covering the pipeline, sources, deduplication, fit engine, verifier, tone critic, and FastAPI endpoints:
```powershell
.\venv\Scripts\python.exe -m pytest dev/tests -q
# Result: 137 passed in 15s
```
