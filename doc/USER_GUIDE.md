# JobPilot v2: Candidate User Guide (for Aswin P T)

Welcome to **JobPilot v2**, your personal multi-source job search and application assistant.

---

## 1. Quick Start

### Step 1: Start the Web App
Double-click `run.bat` (on Windows) or execute in terminal:
```bash
.\venv\Scripts\python.exe -m jobpilot run
```
Open your browser and navigate to: **`http://127.0.0.1:8000`**

### Step 2: Complete Your Profile Answers
1. In the sidebar, click **Profile & Answers** (`/answers`).
2. Review the pre-populated values (your name, degree, contact info, LinkedIn, GitHub, and portfolio are already set).
3. Fill in any `[FILL]` items (e.g. `cgpa_percentage`). Click **Save** on each row.

### Step 3: Run Multi-Source Discovery
1. Click **Sources & Runs** in the sidebar (`/sources`) or click the **Run Discovery** button in the top navigation bar.
2. JobPilot will harvest new openings from active sources (ATS boards, Kerala IT parks, Remotive, Arbeitnow, and configured aggregator APIs).
3. The real-time SSE indicator in the sidebar pulses green as jobs are parsed and saved.

---

## 2. Reviewing & Applying to Jobs

### The Job Workbench (`/workbench/{job_id}`)
When you select a job from the **Today** queue or the **Discover** tab, you enter the 3-column Workbench:

1. **Left Column (Job Context)**:
   - Read the full job description.
   - Review the match score, role tier, and chosen lens.
   - If an HR email exists, verify the MX status badge.

2. **Middle Column (Tailored Resume Preview)**:
   - View your tailored 2-page resume rendered directly in the embedded PDF viewer.
   - Verify that the page fill is between 93% and 100%.
   - If you want to emphasize a different technical angle, click **Re-Tailor**.

3. **Right Column (Contextual Action Route)**:
   - **For HR Email roles**:
     - Review the humble cold email text.
     - Verify the tone score (target: 10/10).
     - Click **Approve for Sending** when you are satisfied.
     - Click **Send Cold Email Now** to dispatch via Gmail SMTP SSL (port 465).
   - **For ATS Portal roles** (Greenhouse, Lever, Ashby, Workable, SmartRecruiters):
     - Click **Launch Visible ATS Assist 🚀**.
     - A real Chromium window will open, navigate to the application form, pre-fill your profile details, and attach your tailored 2-page PDF.
     - Review the form in the browser window and click Submit yourself.
     - Return to JobPilot and click **Mark as Submitted**.
   - **For LinkedIn / Naukri / Indeed roles**:
     - Click **Open Job on LinkedIn / Naukri**.
     - Use the **Copy Cover Note** and **Copy Answers** buttons to paste your responses into the portal.
     - Click **Mark Applied**.

---

## 3. 1-Click Gmail Automation (Score ≥ 75%)

JobPilot v2 includes a complete **1-Click Draft to Gmail** workflow that connects securely via IMAP SSL (993) to your actual Gmail account:

### How it works:
1. Filters all unapplied jobs with match score **≥ 75%** and verified HR contacts.
2. Automatically tailors your exact 2-page ATS resume across the best technical lens.
3. Generates the tailored PDF attachment.
4. Drafts a humble, personalized cold email with mandatory opt-out.
5. Saves the email directly into your **Gmail Drafts folder (`[Gmail]/Drafts`)** with the tailored PDF attached!

### How to use:
* **From the Web UI**: On the **Today (`/`)** screen, click **⚡ 1-Click Draft to Gmail (Score ≥ 75)**.
* **From the Workbench**: On any individual email role, click **✉️ Save to Gmail Drafts**.
* **From the Terminal**:
  ```bash
  .\venv\Scripts\python.exe -m jobpilot draft-gmail --min-score 75 --limit 30
  ```
* **To Send**: Open your Gmail app or [mail.google.com/mail/u/0/#drafts](https://mail.google.com/mail/u/0/#drafts), review your drafts, and click Send!

---

## 4. CLI Commands

You can also run JobPilot directly from the command line:

```bash
# Start the web server and background scheduler
python -m jobpilot run

# 1-Click batch draft creation directly into your Gmail Drafts folder
python -m jobpilot draft-gmail --min-score 75 --limit 30

# Run all enabled discovery sources once
python -m jobpilot discover

# Process and send pending approved emails within IST business hours
python -m jobpilot send-approved

# Read-only health and funnel diagnostics
python -m jobpilot diagnose
```

---

## 4. Production Safeguards FAQ

- **What happens if I approve 20 emails in one day?**
  JobPilot enforces a hard cap of 15 emails per day. The first 15 will be sent with 60–180 second randomized delays; the rest remain safely in the approved queue for the next business morning.
- **Can emails be sent at night?**
  No. JobPilot strictly honors the 09:00 — 18:00 IST business window.
- **Can I contact the same company twice in a week?**
  No. A 30-day company cooldown prevents spamming the same employer with multiple applications.
- **Will JobPilot auto-click on LinkedIn?**
  Never. Headless automation on LinkedIn, Naukri, or Indeed violates their terms of service and risks candidate account restrictions. JobPilot prepares the packet for you to submit manually with 1 click.
