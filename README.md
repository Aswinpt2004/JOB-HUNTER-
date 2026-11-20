# ✈️ JobPilot: Autonomous Job Discovery & Tailored Application Assistant

JobPilot is a production-grade, local, privacy-preserving AI assistant built with Python 3.11+. It discovers companies and job postings in target locations, evaluates technical fit against your genuine master resume, verifies legitimate public HR contacts via DNS MX validation, tailors 2-page exact ATS resumes and concise cold emails, and delivers them through Gmail SMTP **only after your explicit human approval**.

---

## 🎯 Key Guarantees & Safeguards

- **Human-in-the-Loop Approval**: Every application and speculative inquiry is drafted to a review queue. No email leaves Gmail without explicit approval.
- **Truthful Delivery**: Connects directly to `smtp.gmail.com:465` (SSL) using a 16-character Google App Password. Dispatched emails appear in your Gmail Sent folder with genuine Message-IDs.
- **Strict Anti-Spam Safeguards**:
  - **Shared Daily Cap**: Maximum 15 emails per day across both reactive jobs and speculative company outreach.
  - **Human Sending Spacing**: Random 60–180 second delays between consecutive dispatches.
  - **Local Sending Hours**: Only dispatches between **09:00 and 18:00 IST** (Asia/Kolkata).
  - **30-Day Cooldown**: Prevents reaching out to any company or email address contacted in the last 30 days.
  - **Single Follow-Up**: At most one polite follow-up after 6 days.
  - **Permanent Blocklist**: Immediate, permanent suppression of any recipient who requests to opt out.
- **Anti-Hallucination & ATS Resumes**:
  - The master resume (`data/master_resume.json`) is the sole ground truth.
  - Verifier strips or flags any ungrounded skills, employers, metrics, or degrees.
  - Renders pixel-exact, 2-page ATS-formatted PDFs with vertical page-fill enforcement (93–100%).
- **Public & Sanctioned Contacts Only**:
  - Discovers official listings from public tech park directories and official career portals.
  - Validates DNS MX records before queuing any contact address.

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- **Python 3.11+** installed ([python.org](https://www.python.org/downloads/)).
- Google Gemini API key ([aistudio.google.com](https://aistudio.google.com)).
- Gmail account with 2-Factor Authentication enabled and a **16-character App Password**.

### 2. Installation
Open PowerShell in the project directory:
```powershell
# 1. Activate or create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install production dependencies
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file at the project root:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GMAIL_USER=your_real_email@gmail.com
GMAIL_APP_PASSWORD=abcdefghijklmnop
```
*(App password must be 16 lowercase characters with spaces removed).*

### 4. Load Production Companies & HR Contacts
Import verified regional companies and official HR/careers email contacts:
```powershell
python -m src.pipeline import-companies --csv data/ai_hr_contacts.csv
```
This performs live DNS MX validation on each company domain and registers their profile, size signals, and hiring contacts into the local database.

### 5. Run the Discovery & Matching Pipeline
Run the combined pipeline to discover jobs, score opportunities, and generate tailored application drafts:
```powershell
python -m src.pipeline run
```

### 6. Launch the Dashboard
Open the interactive Streamlit dashboard:
```powershell
streamlit run app.py
```
Navigate to `http://localhost:8501`:
1. **Review Queue**: Inspect tailored 2-page resumes, verify email copy, and click **Approve** or **Send Now**.
2. **Companies**: Browse verified companies, assigned tiers (A/B/C), and verified contacts.
3. **Sent**: Review delivery logs, timestamps, and Google Message-IDs.
4. **Follow-ups**: Monitor due follow-ups (capped at 1 per company).
5. **Settings & Health**: Check live SMTP connection status and quota usage.

### 7. Background Delivery (Optional)
To run the automated, paced background sender during IST business hours for approved items:
```powershell
python -m src.pipeline send-worker
```

---

## 📋 Production CLI Reference

| Command | Description |
| :--- | :--- |
| `python -m src.pipeline run` | Runs full discovery, scoring, and drafting across jobs and companies |
| `python -m src.pipeline import-companies --csv <path>` | Imports real company contacts with DNS MX checks |
| `python -m src.pipeline send-approved` | Dispatches all approved applications within IST sending hours |
| `python -m src.pipeline send-worker` | Runs continuous background sending worker with 60–180s pacing |
| `python -m src.pipeline send-diagnose` | Audits credentials, SMTP connection, and queue state |
| `python -m src.pipeline followups` | Drafts due follow-up emails (6-day cooldown, 1-follow-up limit) |
| `streamlit run app.py` | Launches the Streamlit dashboard |

---

## 🔒 Configuration (`config.yaml`)

- `user_profile`: Candidate contact details, target roles, and preferred locations.
- `search_filters`: Positive keywords, excluded locations, and minimum match score.
- `sending`: Daily cap (`15`), delays (`60–180s`), business hours (`9–18` IST), and cooldown (`30` days).
- `company_discovery`: Size threshold (`min_employees: 20`, `preferred_employees: 50`).
- `outreach.require_contact_email`: Ensures speculative emails are only drafted for companies with verified contacts.

---

## 🧪 Developer Tests

Unit tests are located in `dev/tests/` and can be run using the dev environment:
```powershell
pip install -r requirements-dev.txt
pytest dev/tests -o pythonpath=.
```
