# JobPilot v2: End-to-End Pipeline

The JobPilot v2 pipeline transforms discovered job listings from multi-source feeds into tailored, verified, and route-specific application packets.

```
Multi-Source Discovery (API / ATS / IT Parks / Manual)
                    │
                    ▼
          [ 1. Location Normalizer ]  ──> Reject foreign / non-target
                    │
                    ▼
          [ 2. Zero-Token Prescreen ] ──> Reject senior / 3+ yrs exp
                    │
                    ▼
          [ 3. Canonical Dedupe ]     ──> Skip existing / duplicate jobs
                    │
                    ▼
          [ 4. Route Resolver ]       ──> Classify into Email / ATS / Packet
                    │
                    ▼
          [ 5. Role & Lens Matcher ]  ──> Classify into 6 Canonical Lenses
                    │
                    ▼
          [ 6. Resume Tailor ]        ──> Re-order bullets & skills
                    │
                    ▼
          [ 7. Zero-Fabrication ]     ──> Ground against master_resume.json
                    │
                    ▼
          [ 8. 2-Page Fit Engine ]    ──> Render PDF with 93-100% target fill
                    │
                    ▼
      ┌─────────────┼─────────────┐
      ▼             ▼             ▼
  Route: Email  Route: ATS   Route: Packet
  (Cold Email) (Playwright)  (LinkedIn/Naukri)
      │             │             │
      └─────────────┼─────────────┘
                    ▼
          [ 9. Candidate Approval ]   ──> Human approval required
                    │
                    ▼
          [ 10. Multi-Route Apply ]   ──> SMTP:465 / Visible Browser / Copy Packet
                    │
                    ▼
          [ 11. 6-Day Follow-up ]     ──> Max 1 follow-up at 6+ days
```

---

## Stage Descriptions

### Stage 1: Location Normalizer (`jobpilot.pipeline.location`)
- Maps listings to target locations:
  - **Bangalore** (Bengaluru, Whitefield, Koramangala, Electronic City, HSR Layout, etc.)
  - **Thiruvananthapuram** (Trivandrum, Technopark, Kazhakkoottam, etc.)
  - **Kochi** (Cochin, Infopark, Kakkanad, SmartCity, etc.)
  - **Kozhikode** (Calicut, Cyberpark, etc.)
  - **Remote India** (Pan-India remote, Anywhere in India)
- Instantly rejects foreign-only locations (US, UK, Germany, Canada, Australia) and non-target metros.

### Stage 2: Zero-Token Prescreen (`jobpilot.pipeline.prescreen`)
- Uses fast regex matching to discard senior titles (Senior, Lead, Staff, Principal, Architect, Director, Manager).
- Discards explicit 3+, 4+, 5+ years experience demands.
- Preserves fresher, entry-level, junior, intern, graduate, trainee, associate, and 0-1 year roles.

### Stage 3: Canonical Deduplication (`jobpilot.pipeline.dedupe`)
- Calculates canonical key: `{clean_company}__{clean_title}`.
- Normalizes URLs by stripping tracking parameters (`utm_*`, `ref`, `gh_src`, etc.).
- Uses `difflib.SequenceMatcher` to avoid cross-board duplicate scraping.

### Stage 4: Route Resolver (`jobpilot.pipeline.route`)
- Inspects destination domain and job description:
  - Valid Recruiter/HR email found $\rightarrow$ **`email` route**.
  - ATS portal (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) $\rightarrow$ **`ats_assist` route**.
  - LinkedIn, Naukri, Indeed, or other web forms $\rightarrow$ **`packet` route**.

### Stage 5: 6-Lens Classifier & Matcher (`jobpilot.pipeline.match`)
1. **Computer Vision / Drone / Aerial Perception**
2. **LLM Applications / RAG / Agentic AI**
3. **Document AI / OCR / Information Extraction**
4. **Federated Learning / Graph Neural Networks**
5. **Python Backend / FastAPI / Scalable Systems**
6. **Generic ML / Data Science**

### Stage 6 & 7: Tailoring & Verification (`jobpilot.tailor`)
- Reorders experience bullets and project pool according to the lens.
- Verifies every skill against `master_resume.json` with `verify_no_fabrication`.
- Strips any unearned or ungrounded technical claims.

### Stage 8: 2-Page Fit Engine (`jobpilot.tailor.pdf_builder`)
- Dynamically tests typography scale (9.5pt to 10.0pt) and section spacing.
- Measures second page fill using PyMuPDF (`fitz`), guaranteeing 93%–100% target fill.

### Stage 9: Candidate Approval & Multi-Route Apply (`jobpilot.apply`)
- **Email Route**: Validates MX records, checks daily cap (15/day), verifies 09:00–18:00 IST window, checks 30-day cooldown, and dispatches via Gmail SMTP SSL:465 with 60–180s delay.
- **ATS Assist Route**: Launches visible Chromium browser with Playwright, fills form fields from `answers.json`, uploads tailored PDF, and pauses for candidate review.
- **Packet Route**: Saves markdown packet with direct URL, tailored cover note, and copyable screener answers.
