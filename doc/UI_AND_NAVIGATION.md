# JobPilot v2: UI and Navigation Guide

JobPilot v2 features a server-rendered web UI powered by **FastAPI + Jinja2 + HTMX + Alpine.js + local Tailwind CSS** (running on `http://127.0.0.1:8000`).

---

## 1. Global Navigation & Layout

### Persistent Left Sidebar
- **Today** (`/`): Dashboard overview, live funnel stats, pending approval queue, and follow-ups.
- **Discover Jobs** (`/discover`): Filterable job table, search bar, and import modal.
- **Pipeline Board** (`/pipeline`): Kanban board across all stages.
- **Companies** (`/companies`): Target companies directory, size indicators, and MX contacts.
- **Outbox & Sent** (`/outbox`): Sent cold emails audit log with Message-IDs.
- **Follow-ups** (`/followups`): 6-day follow-up manager.
- **Sources & Runs** (`/sources`): Status of source plugins and execution history.
- **Profile & Answers** (`/answers`): Candidate screener answers with `[FILL]` indicator chips.
- **Settings & Health** (`/settings`): Live SMTP and Gemini status, blocklist manager.

### Top Bar
- **Global Search**: Type or press `/` to instantly focus the search input.
- **Run Discovery Button**: One-click trigger to initiate background job harvesting.
- **SSE Stream Pulse**: Real-time connected indicator streaming live job discovery events.

### Keyboard Shortcuts
- `/`: Focus search input
- `j` / `k`: Navigate between job rows
- `a`: Approve selected job for sending
- `s`: Send or apply to current job
- `o`: Open job listing in new browser tab
- `e`: Focus cover note / email body editor

---

## 2. Screen Specifications

### Screen 1: Today Dashboard (`/`)
- **KPI Metrics**: Total Jobs, Drafted & Tailored, Approved Pending Send, Emailed & Applied.
- **Profile Attention Banner**: Highlights if any screener answers have un-filled `[FILL]` tokens.
- **Review Queue Table**: Jobs awaiting candidate approval with 1-click link to Workbench.
- **Safeguards Status Card**: Live daily send cap counter, IST sending window status, and cooldown status.

### Screen 2: Discover Jobs (`/discover`)
- **Filters**: Search query, location (Bangalore, Kochi, TVM, Kozhikode, Remote India), apply route, and status.
- **Jobs Table**: Displays role, company, source chips, apply channel badges, match score, and direct actions.
- **Import Modal**:
  - *Import from URL*: Scrapes title, company, description, and canonical apply target.
  - *Paste JD Text*: Manually create and tailor an application from raw text.

### Screen 3: Job Workbench (`/workbench/{job_id}`)
A 3-column split layout designed for deep review and action:
- **Left Column**: Job metadata, Tier badge, Lens badge, Recruiter contact (with MX verification), and full JD text.
- **Middle Column**: Live PDF viewer of the tailored 2-page resume with measured fit percentage (93-100%). Includes "Re-Tailor" and "PDF ↗" buttons.
- **Right Column (Contextual by Apply Route)**:
  - *Email Route*: Editable subject, tone score (10.0/10), editable body with mandatory opt-out, "Approve" and "Send Email Now (SSL:465)" buttons.
  - *ATS Assist Route*: Playwright visible browser launcher, cover note text box with 1-click Copy, and "Mark as Submitted" button.
  - *Packet Route*: Direct link to job on LinkedIn/Naukri/Indeed, 1-click Copy for tailored cover note, screener question answers, and "Mark Applied" button.

### Screen 4: Application Pipeline Kanban (`/pipeline`)
Columns with move/status update controls:
1. New Discovered
2. Drafted & Tailored
3. Approved
4. Applied / Emailed
5. Interview Scheduled
6. Completed / Closed (Offer / Rejected)

### Screen 5: Target Companies Directory (`/companies`)
- List of 220+ curated companies.
- Size status badges (`confirmed_20plus`, `likely_20plus`).
- Field tags (`computer_vision`, `llm`, `drone`, `healthcare_ai`, `backend`).
- Public HR recruiter contacts with DNS MX verification status.

### Screen 6: Outbox & Sent Audit Log (`/outbox`)
- Timestamp of every dispatched email.
- Masked recipient address (e.g. `c***s@company.com`).
- RFC 5322 Message-ID and subject line.
- Link to the exact PDF attachment generated for that application.

### Screen 7: 6-Day Follow-up Manager (`/followups`)
- Identifies sent emails that have aged past 6 days without a reply.
- Enforces the hard limit of **at most one follow-up message**.
- Includes pre-drafted polite follow-up template with mandatory opt-out.

### Screen 8: Sources & Runs (`/sources`)
- Grid cards for all 10 sources: Adzuna, Jooble, Careerjet, JSearch, Remotive, Arbeitnow, ATS Boards, Kerala Parks, Company Careers, and Manual.
- API Key and credential configuration badges.
- "Run Now" per source and "Run All Configured Sources" buttons.
- Historical execution log table with discovered/filtered counts.

### Screen 9: Profile & Answers (`/answers`)
- Interactive table of candidate screener questions.
- Visual amber chips for `[FILL]` placeholders.
- Inline edit and save inputs that update both SQLite and `data/answers.json`.

### Screen 10: Settings & System Health (`/settings`)
- Live credential checks for Gemini LLM and Gmail SMTP SSL:465.
- Daily LLM token consumption meter (out of 350,000 daily budget).
- SQLite database file size indicator.
- Blocklist and opt-out management table with form to block any address.
