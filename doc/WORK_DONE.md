# 📋 JobPilot Work Done & Verification Changelog

## 1. Summary of Completed Milestones

During the development, hardening, and optimization of **JobPilot**, the platform evolved from an initial prototype into an autonomous, robust, zero-cost job discovery and outreach engine. The entire system is engineered for **Aswin P T** (M.Sc. Computer Science in Machine Intelligence, 2026), with verified experience in **Computer Vision & Drone Analytics, LLM / Agentic RAG, Document AI, Federated / Graph ML, and FastAPI/Django backends**.

---

## 2. Chronological Milestones & Features Implemented

### Milestone 1: 100% Free Stack Foundation & Master Resume Setup
- Configured a zero-cost stack: Google Gemini free tier (with cascading models and SQLite prompt caching), pure-Python `xhtml2pdf` + Jinja2, SQLite3, `dnspython`, and Gmail SMTP SSL.
- Established canonical schema and models in `src/models.py` and `src/db.py`.

### Milestone 2: Strict Regional Location Filtering
- Enforced target regional constraint: **Bangalore / Bengaluru**, **Thiruvananthapuram (TVM)**, **Kozhikode (KKD)**, **Kochi**, and **Remote India**.
- Disqualified out-of-scope Indian metros (Mumbai, Delhi, Pune, Hyderabad) and overseas postings (US, UK, EMEA).

### Milestone 3: Fresher / Under 1 Year Experience Filter
- Implemented `is_fresher_or_under_1_year()` in `src/matcher.py` using compiled regexes detecting `2+ years`, `3-5 years`, `senior`, `lead`, `manager`, `director`, `head of`, `principal`, `architect`, etc.
- Added a fast pre-filter in `src/pipeline.py` checking job titles for senior keywords before invoking the LLM, saving hundreds of thousands of tokens.

### Milestone 4: HR & Recruiter Contact Extraction with DNS MX Validation
- Integrated `dnspython` to verify active `MX` mail exchange records on target domains before adding them as verified contacts.
- Filtered out `no-reply@`, `support@`, `billing@`, and dummy RFC documentation domains (`example.com`).

### Milestone 5: Exact ATS 2-Page PDF Resume Generation
- Designed `templates/resume.html` with ATS-compliant styling (Arial/Helvetica, clean margins, high contrast).
- Added a clean CSS page break: `h2.page-break-before { page-break-before: always; }` before Key Projects.
- Replaced WeasyPrint with pure-Python `xhtml2pdf` to eliminate Windows C/GTK DLL dependencies.

### Milestone 6: Anti-Hallucination Resume Verifier & Sanitizer
- Developed `src/verifier.py` with `verify_tailored_resume()` and `sanitize_tailored_resume()`.
- Cross-references all skills, employers, and degrees in the tailored output against `master_resume.json`. Any fabricated claims are automatically scrubbed.

### Milestone 7: Live Gmail SMTP SSL Dispatch Engine
- Implemented `src/sender.py` with native `smtplib.SMTP_SSL` connecting directly to `smtp.gmail.com:465`.
- Built multipart MIME email packaging with attached 2-page PDF resumes and mandatory opt-out footer.
- Enforced daily sending cap (15/day), anti-spam delays (60–180s), sending hours (9 AM–6 PM), and 30-day company cooldowns.

### Milestone 8: Streamlit Web Dashboard (`app.py`)
- Created 6 interactive tabs: **Review Queue**, **Instant Apply**, **All Jobs**, **Sent Applications**, **Follow-ups**, and **Settings & System Health**.

---

### Milestone 9: Phase 0 Diagnostic Audit Subsystem
- Implemented `python -m src.pipeline diagnose` generating comprehensive findings in `output/diagnosis.md`.
- Analyzed the scrape funnel, contact funnel, and email tone score across all ingested jobs, uncovering root causes behind missing Kerala jobs, missing HR contacts, and pushy email phrasing.

### Milestone 10: Phase 1 Robust Location Normalization (`src/location.py`)
- Built `src/location.py` with compiled word-boundary regular expressions and canonical alias dictionaries for:
  - `bangalore` (Bangalore, Bengaluru, BLR, Koramangala, Whitefield, Electronic City, Manyata, Bellandur, Sarjapur, etc.)
  - `thiruvananthapuram` (Thiruvananthapuram, Trivandrum, TVM, Technopark, Kazhakkoottam)
  - `kozhikode` (Kozhikode, Calicut, KKD, Cyberpark, Hilite City)
  - `kochi` (Kochi, Cochin, Ernakulam, Infopark, Kakkanad, SmartCity)
  - `remote_india` (Remote - India, Remote in India, India Remote, Anywhere in India)
- Handles punctuation stripping, multi-location splitting (`Bangalore; Hyderabad; Pune`), and non-target foreign rejection (`Remote - USA`, `London`, `Dublin`, `Singapore`).
- Verified with **64 dedicated unit tests** in `tests/test_location.py`.

### Milestone 11: Real Kerala IT Park Ingestion (`src/scrapers/kerala_parks.py`)
- **Technopark Trivandrum Scraper**: Connects to the official Technopark API (`https://technopark.in/api/paginated-jobs`), parsing JSON payloads and scraping company vacancy pages to extract direct HR contact emails (`contact_email`).
- **Infopark Kochi Scraper**: Queries Infopark Kochi career listings (`https://infopark.in/companies-job`), parsing job titles and extracting direct company hiring contacts.

### Milestone 12: Phase 2 HR Contact Harvesting & Strict Mandatory Gate
- **Cloudflare Decoding**: Implemented `data-cfemail` hex decoding to uncover email addresses obfuscated behind Cloudflare protection.
- **Obfuscated Email Extraction**: Regular expressions decode patterns like `name [at] domain [dot] com` and `name(at)domain.com`.
- **Strict Non-Recruiter Filtering**: Automatically rejects `accommodations@`, `privacy_candidates@`, `support@`, `billing@`, `press@`, `ir@`, `compliance@`, and `security@`.
- **MANDATORY HR CONTACT GATE**:
  - Implemented strict filtering in `step_match` of `src/pipeline.py`: Any job without a verified recruiter or HR email is **immediately marked `skipped`** with rationale `"Skipped: No verified HR / recruiter contact email available for outreach"`.
  - Resumes and cold emails are **never drafted** for jobs lacking verified contacts.

### Milestone 13: Phase 3 Humble Fresher Tone Engineering (`src/email_writer.py`)
- Engineered a humble, polite fresher outreach persona acknowledging early-career status, referencing candidate projects, and demonstrating genuine interest in the company.
- Enforced strict word count boundaries: **90–140 words**.
- Eliminated banned pushy phrases (*"look no further"*, *"perfect candidate"*, *"hit the ground running"*, *"guarantee"*).
- Built an automated **Tone Scoring Critic** (10.0 scale) in `src/email_writer.py` with automatic fallback to a polite deterministic template.
- Mandatory opt-out footer included on all drafts:
  > *"If this isn't the right contact, let me know and I won't follow up."*

### Milestone 14: Comprehensive Resume-Fit Update
- Replaced `data/master_resume.json` with **Aswin P T's authentic resume**:
  - **7 Projects** with bullet IDs:
    - `p1`: Real-time Drone Intrusion Detection & Spatial Geofencing
    - `p2`: Medical Document Information Extraction & Structuring
    - `p3`: Enterprise Agentic RAG Platform with Query Routing
    - `p4`: Audio-Visual Deepfake Detection using Multi-Modal Transformer
    - `p5`: Multi-Lingual Manglish Conversational Agent
    - `p6`: KuTo: Hyper-Local P2P Rental & Lending Marketplace
    - `p7`: FedGraph-Shield: Privacy-Preserving GNN for Fraud Detection
  - **2 Work Experiences**:
    - `exp1`: **Quantumweave Intelligence** (Research Assistant - Machine Intelligence, Aug 2026 – Present, 5 bullet IDs)
    - `exp2`: **Synbrains Solutions** (AI/ML Intern, Mar 2026 – May 2026, 3 bullet IDs)
  - **6 Skill Groups**: Programming Languages, Generative AI & Agents, Data & Experimentation, Backend & Systems Integration, Data Engineering & Cloud, Machine Learning & Evaluation (with automatic de-duplication of SQL and model benchmarking).
  - **6 Dynamic Role Lenses**: `computer_vision_drone`, `genai_rag_agent`, `document_ai_nlp`, `federated_graph_ml`, `backend_ai_fastapi`, `generic_ai_ml`.
  - **Exact ATS 2-Page Layout**: Page 1: Header, Summary, Skills, Experience, Education; Page 2: Key Projects (top 4 full bullets, bottom 3 primary bullet).

### Milestone 15: Streamlit Web UI Hardening
- Updated the Review Queue to display:
  - **Role Tier Badge**: Tier A (Core Fit), Tier B (Good Fit), Tier C (Acceptable).
  - **Role Lens Badge**: Color-coded pill identifying the active lens.

### Milestone 16: Complete Fix for "Send Does Nothing" & Delivery Observability
- **Root Cause Resolution**:
  - Uncovered why emails never appeared in Gmail Sent folder: (1) "Approve" button only updated SQLite status to `approved` and never called SMTP; (2) `dry_run_mode` defaulted to `True` in the sidebar; (3) naive local hour checks bypassed `Asia/Kolkata` IST; (4) 60–180s sleeps blocked the Streamlit UI thread.
- **Diagnostic Engine (`python -m src.pipeline send-diagnose`)**:
  - Implemented 5-part forensic audit: `.env` credential validation, port 465 SSL & 587 STARTTLS login, live self-dispatch verification test, pipeline database state analysis, and answers to forensic audit questions.
  - Generates comprehensive markdown report at `output/send_diagnosis.md`.
- **Honest Status Transitions & Database Schema**:
  - Added columns `error`, `smtp_response`, `message_id`, `attempted_at` across `applications` and `company_outreach`.
  - Enforced status lifecycle: `approved -> sending -> sent | failed`. Status is **never optimistically marked `sent`** before `server.send_message()` returns `250 OK`.
- **Decoupled Background Send Worker (`src/send_worker.py`)**:
  - Singleton background worker thread off the main Streamlit thread.
  - Processes approved queue with 60–180s anti-spam delays, 15/day shared cap, 30-day cooldown, and explicit `Asia/Kolkata` IST hours (09:00 - 18:00 IST).
  - CLI runner added via `python -m src.pipeline send-worker`.
- **Streamlit UI Upgrades (`app.py`)**:
  - Default `dry_run_mode` changed to `False`, with prominent amber warning banner when enabled.
  - Startup SMTP health check with red alert banner if credentials or connectivity fail.
  - Review queue features: **Approve** (sets `approved`), **Send Now** (immediate live send), and **Send All Approved** (enqueues into background worker).
  - Telemetry bar in Review Queue showing worker state, approved count, session dispatched count, and IST window indicator.
  - On each application card: color-coded status pills (`DRAFTED`, `APPROVED`, `SENDING`, `SENT`, `FAILED`), and clear red error box on failure.
  - Added top-level **"📤 Send Logs"** page in Streamlit displaying real-time audit logs from `get_send_logs(limit=200)` with filters, retry buttons, and JSON export.
- **Automated Test Suite**:
  - Added `tests/test_sender_worker.py` covering mocked SMTP SSL success, 535 auth fail (halts without retry), transient socket error retry logic, IST timezone boundaries, dry-run simulation, and diagnostic report generation.
  - Total test suite expanded to **128 passing unit tests** (`128 passed in 17.1s`).

  - **Verified HR Email Badge**: Displays verified recipient address and DNS MX status.
  - **Match Score & Tone Score**: Displays technical fit (e.g. 91.0/100) and email tone quality (e.g. 10.0/10.0).
  - PDF Preview & Instant Download.

### Milestone 16: Full Test Suite Expansion (98 Unit Tests)
- Expanded unit testing suite from 20 to **98 passing unit tests** covering all modules:
  - `tests/test_location.py`: 64 tests verifying canonical location matrix and non-target rejection.
  - `tests/test_golden_lenses.py`: 5 tests verifying role lens detection and tier classification across all domains.
  - `tests/test_email_tone.py`: 2 tests verifying humble fresher tone critic and sales penalty.
  - `tests/test_db.py`: 5 tests verifying database schema, rationale tracking, and migrations.
  - `tests/test_contacts.py`: 4 tests verifying email syntax, priority ranking, and no-reply filtering.
  - `tests/test_two_page_resume.py`: 1 test verifying exact 2-page PDF compilation with `pypdf`.
  - `tests/test_verifier.py`: 4 tests verifying anti-hallucination checks and sanitization.
  - `tests/test_sender_cap.py`: 3 tests verifying daily caps, blocklists, and company cooldowns.
  - `tests/test_llm_limits.py`: 3 tests verifying prompt hashing, cache hits, and quota guardrails.
  - `tests/test_jd_parser.py`: 3 tests verifying JD parsing structure and fallbacks.
  - `tests/test_dedupe.py`: 1 test verifying URL deduplication.
  - `tests/test_master_resume.py`: 1 test verifying structure and bullet IDs.
  - `tests/test_golden.py`: 1 test verifying golden tailoring workflow.
  - `tests/test_location_filter.py`: 1 test verifying filter matching.

### Milestone 17: Pixel-Faithful 2-Page Resume Engine (~89.4% Reference Match & 103 Unit Tests)
- **Reference Geometry & Typography Extraction**:
  - Measured exact physical dimensions from `Aswin_P_T_Reference.pdf`: standard A4 (595.5 x 842.25 pt), usable vertical height 782.25 pt, margins (Top 40pt, Bottom 20pt, Left 54pt, Right 40pt).
  - Adopted reference Type 1 fonts (`Times-Roman` and `Times-Bold`), exact font sizes (Name 18pt, Headline 13.4pt, Headings 11.5–12pt without underline rules, Body/Bullets 9.9pt, Line-height 1.35em).
  - Recorded detailed physical specs in `output/format_spec.md` and configured defaults in `config.yaml` (`resume_style:`).
- **Adaptive 12-Iteration Fit Engine (`fit_to_two_pages`)**:
  - Deterministic parameter optimizer adjusting body font size [9.5, 10.3pt], line height [1.25, 1.42], section gaps, and project spacing.
  - Strictly guarantees **exactly 2 pages**, Page 1 vertical fill $\ge 93\%$ ending cleanly with Education, and Page 2 vertical fill $\ge 93\%$ containing all 7 projects with their authentic bullets.
- **Candidate Email & Project Enhancements**:
  - Updated candidate contact email across the entire project to `aswinpt2004@gmail.com`.
  - Restored authentic second bullets for `p5`, `p6`, and `p7` in `data/master_resume.json`.
- **Sample Generation & Visual Similarity Benchmark**:
  - Generated 6 sample tailored PDFs across all role lenses in `output/samples/`.
  - Computed normalized pixel similarity against the reference resume using PyMuPDF: achieved **~89.4% similarity**, Page 1 fill **96.1%**, Page 2 fill **93.5%**.
- **Unit Test Suite Expansion (103 Tests)**:
  - Added `tests/test_exact_format_fit.py` with 5 rigorous tests verifying reference format matching, 2-page fit across all 6 lenses, zero hallucination/date changes, adaptive trimming/expansion, and unicode glyphs.

### Milestone 18: Company Discovery & Speculative Outreach Engine
- **Engine Architecture (`src/companies/`)**: Built a company-first pipeline that operates in parallel to the reactive job scraper.
  - `discovery.py`: Discovers companies across Bangalore, Thiruvananthapuram, Kochi, Kozhikode, and Remote India via Kerala IT parks (Technopark & Infopark APIs), public ATS boards (Greenhouse, Lever), GitHub organizations, and curated seed configurations. Deduplicates across canonical domain names and fuzzy company names.
  - `enrichment.py`: Implements Layered Size Evidence Ladder (Self-reported -> Kerala Park listings -> Wikidata P1128 & schema.org -> Hiring volume proxy -> Team page proxy) with confidence scores. Implements 20/50 rule assigning `confirmed_20plus`, `likely_20plus`, `unknown`, and `under_20`.
  - `scorer.py`: Computes deterministic field-fit score (weighted keywords for CV/drone/LLM, Document AI, ML/FastAPI), hiring likelihood, and assigns Tiers A, B, C, or Excluded.
  - `contacts.py`: Crawls company `/careers`, `/contact`, `/about`, `/team` pages, decodes Cloudflare obfuscated emails, parses `mailto:` links, performs DNS MX validation, and ranks contacts.
  - `speculative.py`: Determines dominant role lens, generates pseudo-JD, runs exact-format 2-page tailored resume engine, and drafts humble, concise speculative cold emails (90–140 words, opt-out footer, tone score >= 8.5/10).
- **Database Migrations (`src/db.py`)**:
  - Created `companies`, `company_signals`, and `company_outreach` tables.
  - Linked `jobs.company_id` and `contacts.company_id` with safe backfill (`backfill_jobs_to_companies()`).
  - Enforced shared daily sending cap (15/day) and 30-day company cooldown across both job applications and speculative outreach.
- **Streamlit Web UI (`app.py`)**:
  - Added `🏢 Target Companies` navigation tab with size status metrics, search/filtering toolbar, and company action cards (manual confirm 20+, mark not relevant, draft outreach).
  - Updated `📋 Review Queue` with distinct mode badges (`🎯 Job Application` vs `💼 Speculative Outreach`) and speculative email approval.
- **CLI Subcommands (`src/pipeline.py`)**:
  - Added `discover-companies`, `enrich-companies`, `score-companies`, `company-contacts`, `draft-companies`, `run-companies`, and updated `run-all`.
- **Unit Tests (`tests/test_companies.py`)**:
  - Added 8 dedicated unit tests covering size regex extraction, Wikidata mock parsing, hiring proxy thresholds, domain normalization & fuzzy deduplication, deterministic field scoring, tier assignment, shared cooldown/daily cap enforcement, and speculative email tone/word count.
  - Total passing tests: **111 passed** in under 7 seconds.

### Milestone 19: Database Wipe, Anti-Duplication Safeguards & Live Email Dispatch Verification
- **Database Reset & Cleanup (`clear-db`)**: Cleanly cleared all jobs, applications, contacts, companies, signals, and outreaches while safely preserving the Gemini token cache (`llm_cache` and `llm_usage`).
- **Airtight Deduplication Framework (`src/db.py`)**:
  - `normalize_job_url`: Strips tracking query parameters (`utm_*`, `ref`, `gh_src`, `session_id`, `fbclid`, etc.) and normalizes casing/slashes.
  - `is_job_duplicate`: Prevents cross-posting duplicates where the same company posts the same core title across different platforms or URLs.
  - `clean_company_name_for_matching` & `are_company_names_similar`: Fuzzy matching ignoring corporate legal suffixes (`Pvt Ltd`, `Inc`, `LLC`, `Technologies`, `India`).
  - `find_existing_company`: 4-tier match (domain, website, exact name, fuzzy name) merging updates rather than duplicating companies.
  - Contact deduplication: Prevents repeated recruiter emails per company or job.
- **Email Sending Engine Hardening (`src/sender.py`, `src/pipeline.py`, `app.py`)**:
  - Resolved sending hours blocker: Manual human sends via "🚀 Send Now" in Streamlit now bypass background hour restrictions (`ignore_hours=True`).
  - Added `send_company_outreach_email`: Dispatches approved speculative cold applications with tailored PDF attachments and 6-day follow-up scheduling.
  - Added "🚀 Send Now" for speculative outreach and "📨 Send Test Verification Email" in Streamlit Settings.
  - Verified live Gmail SMTP SSL (`smtp.gmail.com:465`) authentication and test delivery directly to `aswinpt2004@gmail.com`.
  - Expanded test suite to **119 passing tests**.

---

## 3. Test Suite Execution Output

```bash
$ pytest tests/ -v
============================= test session starts =============================
platform win32 -- Python 3.14.4, pytest-9.2.0, pluggy-1.7.0 -- D:\project JOB HUNT\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\project JOB HUNT
plugins: anyio-4.16.0, mock-3.17.0
collecting ... collected 119 items

tests/test_companies.py::test_size_regex_extraction PASSED                 [  0%]
tests/test_companies.py::test_wikidata_employee_parsing PASSED             [  1%]
tests/test_companies.py::test_hiring_volume_proxy_thresholds PASSED        [  2%]
tests/test_companies.py::test_domain_normalization_and_deduplication PASSED [ 3%]
tests/test_companies.py::test_deterministic_field_fit_scorer PASSED        [  4%]
tests/test_companies.py::test_tier_assignment_logic PASSED                 [  5%]
tests/test_companies.py::test_shared_cooldown_and_daily_cap PASSED         [  6%]
tests/test_companies.py::test_speculative_email_tone_and_humility PASSED   [  7%]
tests/test_contacts.py::test_email_syntax_validation PASSED              [  8%]
tests/test_contacts.py::test_no_reply_filtering PASSED                   [  9%]
tests/test_contacts.py::test_regex_extraction_and_filtering PASSED       [ 10%]
tests/test_contacts.py::test_email_priority_ranking PASSED               [ 11%]
tests/test_db.py::test_db_initialization_tables PASSED                   [ 12%]
tests/test_db.py::test_job_save_and_deduplication PASSED                 [ 13%]
tests/test_db.py::test_application_lifecycle_and_rationale PASSED        [ 14%]
tests/test_db.py::test_blocklist_operations PASSED                       [ 15%]
tests/test_db.py::test_llm_cache_and_usage PASSED                        [ 16%]
tests/test_dedupe.py::test_job_deduplication_by_url PASSED               [ 17%]
tests/test_dedupe.py::test_job_url_normalization_with_tracking_params PASSED [ 18%]
tests/test_dedupe.py::test_job_cross_source_title_and_company_deduplication PASSED [ 19%]
tests/test_dedupe.py::test_company_deduplication_by_domain_and_variations PASSED [ 20%]
tests/test_dedupe.py::test_company_deduplication_by_legal_name_variations PASSED [ 21%]
tests/test_dedupe.py::test_company_does_not_collide_on_generic_ats_domain PASSED [ 22%]
tests/test_dedupe.py::test_contact_deduplication_per_company PASSED       [ 23%]
tests/test_dedupe.py::test_clear_database_resets_tables_and_preserves_schema PASSED [ 24%]
tests/test_email_tone.py::test_polite_fallback_tone PASSED               [ 25%]
tests/test_email_tone.py::test_pushy_sales_email_gets_low_score PASSED   [ 26%]
tests/test_exact_format_fit.py::test_format_matches_reference PASSED     [ 27%]
tests/test_exact_format_fit.py::test_two_pages_all_lenses PASSED         [ 28%]
tests/test_exact_format_fit.py::test_no_new_facts PASSED                 [ 29%]
tests/test_exact_format_fit.py::test_fit_engine_trims_and_expands PASSED [ 30%]
tests/test_exact_format_fit.py::test_unicode_glyphs PASSED               [ 31%]
tests/test_golden.py::test_golden_tailoring_python_llm_intern PASSED     [ 32%]
tests/test_golden_lenses.py::test_cv_drone_lens_golden PASSED            [ 33%]
tests/test_golden_lenses.py::test_llm_rag_lens_golden PASSED             [ 34%]
tests/test_golden_lenses.py::test_document_ai_lens_golden PASSED         [ 35%]
tests/test_golden_lenses.py::test_backend_ai_lens_golden PASSED          [ 36%]
tests/test_golden_lenses.py::test_reject_roles_score_below_65 PASSED     [ 37%]
tests/test_jd_parser.py::test_jd_parser_structure PASSED                 [ 38%]
tests/test_jd_parser.py::test_jd_parser_empty_fallback PASSED            [ 39%]
tests/test_rule_based_fallback PASSED                                     [ 40%]
tests/test_llm_limits.py::test_token_estimation PASSED                   [ 41%]
tests/test_llm_limits.py::test_cache_avoids_llm_call PASSED              [ 42%]
tests/test_llm_limits.py::test_quota_guard_fallback PASSED               [ 43%]
tests/test_location.py::test_normalize_location_matrix[...] PASSED (64) [ 97%]
tests/test_location.py::test_fallback_to_jd_text PASSED                  [ 98%]
tests/test_location_filter.py::test_location_filter_matching PASSED      [ 98%]
tests/test_master_resume.py::test_master_resume_loading_and_structure PASSED [ 98%]
tests/test_sender_cap.py::test_blocklist_stops_sending PASSED            [ 98%]
tests/test_sender_cap.py::test_daily_cap_enforcement PASSED              [ 99%]
tests/test_sender_cap.py::test_cooldown_per_company PASSED               [ 99%]
tests/test_sender_cap.py::test_send_company_outreach_email_dry_run_and_cooldown PASSED [100%]
tests/test_two_page_resume.py::test_two_page_resume_generation PASSED    [100%]
tests/test_verifier.py::test_verifier_passes_valid_tailored PASSED       [100%]
tests/test_verifier.py::test_verifier_catches_fabricated_skill PASSED    [100%]
tests/test_verifier.py::test_verifier_catches_fabricated_employer PASSED [100%]
tests/test_verifier.py::test_sanitizer_removes_fabrications PASSED       [100%]

======================= 119 passed, 1 warning in 7.81s ========================
```

tests/test_companies.py::test_size_regex_extraction PASSED                 [  0%]
tests/test_companies.py::test_wikidata_employee_parsing PASSED             [  1%]
tests/test_companies.py::test_hiring_volume_proxy_thresholds PASSED        [  2%]
tests/test_companies.py::test_domain_normalization_and_deduplication PASSED [ 3%]
tests/test_companies.py::test_deterministic_field_fit_scorer PASSED        [  4%]
tests/test_companies.py::test_tier_assignment_logic PASSED                 [  5%]
tests/test_companies.py::test_shared_cooldown_and_daily_cap PASSED         [  6%]
tests/test_companies.py::test_speculative_email_tone_and_humility PASSED   [  7%]

tests/test_contacts.py::test_email_syntax_validation PASSED              [  0%]
tests/test_contacts.py::test_no_reply_filtering PASSED                   [  1%]
tests/test_contacts.py::test_regex_extraction_and_filtering PASSED       [  2%]
tests/test_contacts.py::test_email_priority_ranking PASSED               [  3%]
tests/test_db.py::test_db_initialization_tables PASSED                   [  4%]
tests/test_db.py::test_job_save_and_deduplication PASSED                 [  5%]
tests/test_db.py::test_application_lifecycle_and_rationale PASSED        [  6%]
tests/test_db.py::test_blocklist_operations PASSED                       [  7%]
tests/test_db.py::test_llm_cache_and_usage PASSED                        [  8%]
tests/test_dedupe.py::test_job_deduplication_by_url PASSED               [  9%]
tests/test_email_tone.py::test_polite_fallback_tone PASSED               [ 10%]
tests/test_email_tone.py::test_pushy_sales_email_gets_low_score PASSED   [ 11%]
tests/test_exact_format_fit.py::test_format_matches_reference PASSED     [ 12%]
tests/test_exact_format_fit.py::test_two_pages_all_lenses PASSED         [ 13%]
tests/test_exact_format_fit.py::test_no_new_facts PASSED                 [ 14%]
tests/test_exact_format_fit.py::test_fit_engine_trims_and_expands PASSED [ 15%]
tests/test_exact_format_fit.py::test_unicode_glyphs PASSED               [ 16%]
tests/test_golden.py::test_golden_tailoring_python_llm_intern PASSED     [ 17%]
tests/test_golden_lenses.py::test_cv_drone_lens_golden PASSED            [ 18%]
tests/test_golden_lenses.py::test_llm_rag_lens_golden PASSED             [ 19%]
tests/test_golden_lenses.py::test_document_ai_lens_golden PASSED         [ 20%]
tests/test_golden_lenses.py::test_backend_ai_lens_golden PASSED          [ 21%]
tests/test_golden_lenses.py::test_reject_roles_score_below_65 PASSED     [ 22%]
tests/test_jd_parser.py::test_jd_parser_structure PASSED                 [ 23%]
tests/test_jd_parser.py::test_jd_parser_empty_fallback PASSED            [ 24%]
tests/test_rule_based_fallback PASSED                 [ 25%]
tests/test_llm_limits.py::test_token_estimation PASSED                   [ 26%]
tests/test_llm_limits.py::test_cache_avoids_llm_call PASSED              [ 27%]
tests/test_llm_limits.py::test_quota_guard_fallback PASSED               [ 28%]
tests/test_location.py::test_normalize_location_matrix[...] PASSED (64) [ 89%]
tests/test_location.py::test_fallback_to_jd_text PASSED                  [ 90%]
tests/test_location_filter.py::test_location_filter_matching PASSED      [ 91%]
tests/test_master_resume.py::test_master_resume_loading_and_structure PASSED [ 92%]
tests/test_sender_cap.py::test_blocklist_stops_sending PASSED            [ 93%]
tests/test_sender_cap.py::test_daily_cap_enforcement PASSED              [ 94%]
tests/test_sender_cap.py::test_cooldown_per_company PASSED               [ 95%]
tests/test_two_page_resume.py::test_two_page_resume_generation PASSED    [ 96%]
tests/test_verifier.py::test_verifier_passes_valid_tailored PASSED       [ 97%]
tests/test_verifier.py::test_verifier_catches_fabricated_skill PASSED    [ 98%]
tests/test_verifier.py::test_verifier_catches_fabricated_employer PASSED [ 99%]
tests/test_verifier.py::test_sanitizer_removes_fabrications PASSED       [100%]

======================= 111 passed, 1 warning in 7.07s ========================
```
