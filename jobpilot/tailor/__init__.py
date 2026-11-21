"""
JobPilot Tailoring & Document Generation Package
"""
from jobpilot.tailor.verifier import verify_no_fabrication, sanitize_tailored_resume
from jobpilot.tailor.resume_tailor import tailor_resume_for_job
from jobpilot.tailor.pdf_builder import generate_tailored_pdf
from jobpilot.tailor.cover_note import generate_cover_note
from jobpilot.tailor.email_writer import generate_tailored_email

__all__ = [
    "verify_no_fabrication",
    "sanitize_tailored_resume",
    "tailor_resume_for_job",
    "generate_tailored_pdf",
    "generate_cover_note",
    "generate_tailored_email"
]

