# 📖 JobPilot User Guide & Operations Manual

This guide provides practical instructions for operating, configuring, and maintaining the **JobPilot** job discovery, qualification, and outreach assistant.

---

## 1. Quick Start Guide

### Step 1: Open Terminal & Activate Virtual Environment
Open PowerShell or your preferred terminal in the project root directory:

```powershell
cd "d:\project JOB HUNT"
.\venv\Scripts\Activate.ps1
```

### Step 2: Verify Credentials (`.env`)
Ensure your `.env` file contains your free Google Gemini API key and Gmail App Password:

```dotenv
GEMINI_API_KEY=AIzaSy...your-gemini-key
GMAIL_USER=aswinpt2004@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

> [!TIP]
> For Gmail, generate a 16-character **App Password** from [Google Account Security > App passwords](https://myaccount.google.com/apppasswords). Do NOT use your primary Google account password.

### Step 3: Launch the Streamlit Web Dashboard
Run the following command to start the interactive web application:

```powershell
.\venv\Scripts\streamlit run app.py
```
Open your browser and navigate to: **[http://localhost:8501](http://localhost:8501)**.

---

## 2. Using the Web Dashboard

The web interface is divided into 6 intuitive tabs:

### 1. 📋 Review Queue
- Displays all applications that met the matching criteria ($\ge 65.0$), passed location & experience filters, and **possess a verified HR contact email**.
- **Role Tier & Lens Badges**: Clear visual pills indicate whether the job is Tier A (Core Fit), Tier B (Good Fit), or Tier C (Acceptable), alongside the active role lens (e.g., `Computer Vision & Drone Analytics`, `LLM & Agentic RAG`).
- **Verified HR Contact Badge**: Confirms the recipient email and DNS MX verification status.
- **Vertical Page Fill & Layout Fit Badge**: Displays the precise vertical page fill percentages measured by PyMuPDF (e.g. `Page 1: 96.1% | Page 2: 93.5%`) along with the `✅ Exact 2-Page Fit` status badge confirming zero overflow and zero orphaned headers.
- **Tone Score**: Displays the automated tone quality rating (e.g. `10.0 / 10.0`) confirming humble fresher tone and 90–140 word count.
- **Inspect PDF**: Click **Download Tailored Resume (PDF)** to preview or inspect the generated pixel-faithful 2-page ATS resume.
- **Edit Outreach Email**: Edit the generated email subject line or body text directly in the text area.
- **Approve**: Click **✅ Approve Application** to queue for dispatch.
- **Skip**: Click **⏭️ Skip Application** to discard.

### 2. 🎯 Instant Apply (Any External Job Link or Text)
- Found an interesting job on LinkedIn, Internshala, or a job board?
- Enter the **Job Title**, **Company**, and paste the **Job Description** or **Job URL**.
- Click **⚡ Process & Tailor Application**.
- JobPilot will:
  1. Determine role tier and seniority.
  2. Harvest and MX-validate company HR contacts.
  3. Tailor candidate experiences and 7 projects to the best matching role lens.
  4. Compile a 2-page ATS vector PDF using `xhtml2pdf`.
  5. Draft a humble fresher cold outreach email.

### 3. 💼 All Jobs
- Search and browse all discovered jobs stored in the local SQLite database.
- Filter by search keyword, company name, location, or source.

### 4. 🚀 Sent Applications
- Tracks all cold emails dispatched via Gmail SMTP.
- Displays sent timestamp, recipient email, and follow-up due date.
- **Mark as Replied**: Click when a recruiter responds to stop follow-up tracking.
- **Opt-Out & Block**: Click if a recruiter asks not to be contacted, instantly adding their address to the permanent `blocklist`.

### 5. ⏰ Follow-ups
- Surfaces applications where 6 days have elapsed since initial dispatch without a response.
- Pre-drafts a polite 2-sentence follow-up message ready to dispatch with one click.

### 6. 🏢 Target Companies
- Comprehensive directory of tech companies discovered across Bangalore, Thiruvananthapuram, Kochi, Kozhikode, and Remote India.
- **Size Metrics**: Track distribution of `Confirmed 20+`, `Likely 20+`, `Unknown Size`, and `Under 20`.
- **Search & Filter**: Filter by city, tier (Tier A, Tier B, Tier C), and size status.
- **Company Cards**: View verified domains, addresses, employee estimates, confidence levels, and full evidence ladders (Wikidata, schema.org, Kerala IT park directories, and ATS hiring volume proxies).
- **Actions**:
  - **Confirm 20+ Staff**: Manually verify and elevate an unknown company for outreach.
  - **Not Relevant**: Mark company excluded.
  - **Draft Speculative Outreach**: Instantly trigger the exact-format 2-page tailored resume engine and cold email drafting for this company.

### 7. ⚙️ Settings & System Health
- **Daily Quota Tracker**: Real-time display of LLM API requests and token usage against your daily free-tier limit.
- **Blocklist Management**: View and manually add emails to the opt-out blocklist.
- **Audit Logs**: View real-time system logs for scraping, matching, PDF generation, and dispatch events.

---

## 3. Command Line Interface (CLI) Guide

All JobPilot operations can be executed directly from the terminal for automation or background execution:

### 1. Audit & Diagnostics (`diagnose`)
Runs a complete diagnostic check of the scraping funnel, contact harvesting, and email tone quality, writing findings to `output/diagnosis.md`:
```powershell
.\venv\Scripts\python -m src.pipeline diagnose
```

### 2. Scrape New Postings (`scrape`)
Ingests fresh postings from Technopark Trivandrum, Infopark Kochi, Greenhouse, Lever, and target career portals:
```powershell
.\venv\Scripts\python -m src.pipeline scrape
```

### 3. Match Discovered Jobs (`match`)
Screens unprocessed jobs for location, 0–1 year experience, extracts recruiter contacts, and scores technical match against your master resume:
```powershell
.\venv\Scripts\python -m src.pipeline match --limit 20
```

> [!NOTE]
> Any job lacking a verified recruiter or HR email address is automatically marked `skipped` with rationale `"Skipped: No verified HR / recruiter contact email available for outreach"`. Resumes and emails are never drafted for contact-less postings.

### 4. Draft Resumes & Emails (`draft`)
Compiles 2-page ATS PDFs and personalized humble cold emails for qualified applications:
```powershell
.\venv\Scripts\python -m src.pipeline draft --limit 10
```

### 5. Test Email Dispatch (Simulated / Dry-Run)
Verifies the SMTP dispatch loop without transmitting real emails:
```powershell
.\venv\Scripts\python -m src.pipeline send-approved --dry-run
```

### 6. Send Approved Applications (Live Dispatch)
Sends approved emails via Gmail SMTP SSL with 2-page PDF resumes attached:
```powershell
.\venv\Scripts\python -m src.pipeline send-approved
```

### 7. Run Complete End-to-End Pipeline (`run-all`)
Executes both the reactive Jobs Engine and the proactive Company-First Engine in one automated command:
```powershell
# Dry-run mode (safe preview)
.\venv\Scripts\python -m src.pipeline run-all --dry-run

# Live pipeline execution
.\venv\Scripts\python -m src.pipeline run-all --match-limit 20 --draft-limit 10
```

### 8. Company Discovery & Speculative Outreach Commands
Run the company-first engine independently:
```powershell
# 1. Discover target companies across target cities
.\venv\Scripts\python -m src.pipeline discover-companies --city "Bangalore" --limit 20

# 2. Enrich company size via 5-level evidence ladder (20/50 rule)
.\venv\Scripts\python -m src.pipeline enrich-companies --limit 20

# 3. Deterministically score field-fit and hiring signals
.\venv\Scripts\python -m src.pipeline score-companies --limit 20

# 4. Harvest and MX-validate company HR & recruiter contacts
.\venv\Scripts\python -m src.pipeline company-contacts --limit 10

# 5. Draft exact-format 2-page tailored resumes & humble speculative cold emails
.\venv\Scripts\python -m src.pipeline draft-companies --limit 10

# 6. Run the entire Company-First Engine in one command
.\venv\Scripts\python -m src.pipeline run-companies --limit 10
```

---

## 4. Customizing Configuration (`config.yaml`)

### Target Regional Locations
```yaml
user_profile:
  preferred_locations:
    - "Bangalore"
    - "Bengaluru"
    - "Kochi"
    - "Cochin"
    - "Thiruvananthapuram"
    - "Trivandrum"
    - "TVM"
    - "Kozhikode"
    - "Calicut"
    - "KKD"
    - "Remote India"
```

### Adding New Greenhouse or Lever Boards
```yaml
scrapers:
  greenhouse_boards:
    - "inmobi"
    - "groww"
    - "slice"
    - "thoughtworks"
    - "your-target-company"
  lever_boards:
    - "meesho"
    - "cred"
    - "palantir"
    - "your-target-company"
```

### Email Dispatch Rates & Anti-Spam Safeguards
```yaml
sending:
  daily_cap: 15                  # Max cold emails per day
  delay_min_seconds: 60          # Minimum seconds between emails
  delay_max_seconds: 180         # Maximum seconds between emails
  sending_hours_start: 9         # 9 AM
  sending_hours_end: 18          # 6 PM
  cooldown_days: 30              # Days before re-contacting same company
  followup_days: 6               # Days before scheduling follow-up
```

---

## 5. Troubleshooting & Frequently Asked Questions

### Q1: Gmail SMTP Authentication Error (`SMTPAuthenticationError`)
- **Cause**: Using your normal Google account password instead of an App Password, or 2FA is not enabled.
- **Solution**: Enable 2-Step Verification on your Google account, generate a 16-character **App Password** for "Mail", and paste it into `GMAIL_APP_PASSWORD` in `.env`.

### Q2: Why are certain jobs being marked as `skipped` even if they have high match scores?
- **Cause**: The posting does not have a verified recruiter or HR contact email address, or the company domain's DNS MX lookup failed.
- **Policy**: JobPilot strictly avoids listings without actionable HR contact emails to prevent sending blind emails to generic contact forms or unmonitored inboxes.

### Q3: How do I verify my resume renders to exactly 2 pages?
- Run the dedicated unit test:
  ```powershell
  .\venv\Scripts\python -m pytest tests/test_two_page_resume.py -v
  ```
- Or inspect generated PDFs directly in `output/resumes/`.

### Q4: How do I run all 98 unit tests?
```powershell
.\venv\Scripts\python -m pytest tests/ -v
```
All 98 tests should pass in approximately 2 seconds.
