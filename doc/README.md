# 📖 JobPilot Documentation Hub

Welcome to the comprehensive documentation for **JobPilot** — an autonomous, human-in-the-loop job discovery, resume tailoring, and outreach platform designed for early-career AI/ML and software engineers.

JobPilot is configured specifically for **Aswin P T** (M.Sc. Computer Science in Machine Intelligence, 2026), specializing in **Computer Vision & Drone Analytics, LLM / Agentic RAG, Document AI, Federated / Graph ML, and FastAPI/Django backends**, seeking roles in **Bangalore**, **Thiruvananthapuram (TVM)**, **Kozhikode (KKD)**, **Kochi**, and **Remote India**.

---

## 📑 Documentation Structure

| Document | Purpose |
| :--- | :--- |
| **[ARCHITECTURE.md](file:///d:/project%20JOB%20HUNT/doc/ARCHITECTURE.md)** | System design, component diagrams, database schema, role lenses, technology stack, and security boundaries. |
| **[PIPELINE.md](file:///d:/project%20JOB%20HUNT/doc/PIPELINE.md)** | Step-by-step pipeline execution, location normalization, HR contact mandatory qualification, weighted scoring, and dispatch. |
| **[WORK_DONE.md](file:///d:/project%20JOB%20HUNT/doc/WORK_DONE.md)** | Chronological log of all milestones, diagnostic audit findings, Kerala park scrapers, tone engineering, resume-fit updates, and test suite expansion (98 tests). |
| **[USER_GUIDE.md](file:///d:/project%20JOB%20HUNT/doc/USER_GUIDE.md)** | Practical user handbook for CLI commands (including `diagnose`), Streamlit Web UI controls, configuration customization, and troubleshooting. |

---

## 🎯 Core Principles & Constraints

- **100% Free Technology Stack**: Operates completely on zero-cost infrastructure: Google Gemini free tier (with automatic model cascading and SQLite prompt caching), pure-Python `xhtml2pdf` + Jinja2, SQLite3, `dnspython`, and Gmail SMTP SSL.
- **Strict Target Locations Only**: Exclusively filters jobs for **Bangalore / Bengaluru**, **Thiruvananthapuram (TVM / Trivandrum)**, **Kozhikode (KKD / Calicut)**, **Kochi / Cochin**, and **Remote India**. All foreign or non-target cities (Mumbai, Delhi, Pune, US, UK) are automatically skipped via word-boundary canonical matching.
- **Strict Experience Tier**: Tailored exclusively for **Freshers and under 1 year of experience** (0–1 years, interns, entry-level, junior, trainees). Automatically rejects 2+ year requirements and senior/lead/manager titles.
- **Role Tiering & Role Lenses**:
  - **Tier A (Core Fit)**: Computer Vision, Drone Analytics, AI/ML Engineer, Applied ML, GenAI / RAG / Agent Developer.
  - **Tier B (Good Fit)**: Document AI, Medical AI, Junior Data Scientist, AI Research Assistant, Federated / Graph ML.
  - **Tier C (Acceptable)**: Python Backend (FastAPI / Django) with AI integration, Software Engineer (AI team).
  - **Reject**: Pure frontend, QA/testing, SAP/ERP, DevOps-only, non-technical roles, or 2+ years experience.
  - **6 Dynamic Lenses**: Reorders projects and bullet points to match the exact role type (`computer_vision_drone`, `genai_rag_agent`, `document_ai_nlp`, `federated_graph_ml`, `backend_ai_fastapi`, `generic_ai_ml`).
- **Strict HR Contact Mandate**: Any job listing lacking a verified recruiter or HR contact email is **strictly avoided and marked `skipped`**. Resumes and emails are never drafted for contact-less postings, saving tokens and ensuring every queued application has a direct recipient.
- **Humble Fresher Tone Engineering**: Cold outreach emails read like a polite, humble, genuine fresher writing to a real person (90–140 words, specific project citation, no pushy sales pitches, mandatory opt-out footer).
- **Pixel-Perfect 2-Page ATS Resume**: Produces pixel-faithful clones of candidate's reference resume (`Aswin_P_T_Reference.pdf`) using Times-Roman / Times-Bold typography. An adaptive fit engine guarantees both pages achieve vertical fills in **[0.93, 1.00]** with 2 real experiences (Quantumweave & Synbrains), 6 skill groups, and all 7 key projects with zero overflow.
- **Human-in-the-Loop Safeguard**: Resumes and cold emails are queued for review in the Streamlit Web UI. Nothing is dispatched without explicit candidate approval.
