import sys
import argparse
import logging
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("jobpilot")


def main():
    parser = argparse.ArgumentParser(description="JobPilot v2: Multi-Source Application Assistant")
    subparsers = parser.add_subparsers(dest="command")

    # Command: run (default)
    run_parser = subparsers.add_parser("run", help="Start the FastAPI web server & background scheduler")
    run_parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    run_parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    run_parser.add_argument("--reload", action="store_true", help="Enable uvicorn autoreload")

    # Command: discover
    subparsers.add_parser("discover", help="Run all enabled job discovery sources once")

    # Command: send-approved
    subparsers.add_parser("send-approved", help="Process and send pending approved cold email applications")

    # Command: diagnose
    subparsers.add_parser("diagnose", help="Read-only health diagnosis of funnel, database, and credentials")

    # Command: draft-gmail
    draft_parser = subparsers.add_parser("draft-gmail", help="1-Click: Tailor resumes and save cold email drafts directly into your Gmail Drafts folder")
    draft_parser.add_argument("--min-score", type=float, default=75.0, help="Minimum match score threshold (default: 75.0)")
    draft_parser.add_argument("--limit", type=int, default=30, help="Maximum number of drafts to generate (default: 30)")

    args = parser.parse_args()
    cmd = args.command or "run"

    if cmd == "run":
        logger.info("Starting JobPilot v2 web application on http://%s:%d", args.host, args.port)
        uvicorn.run("jobpilot.app.main:app", host=args.host, port=args.port, reload=args.reload)

    elif cmd == "discover":
        from jobpilot.sources.base import run_all_enabled_sources
        logger.info("Executing multi-source job discovery...")
        results = run_all_enabled_sources()
        print("\nDiscovery Results:")
        for src, res in results.items():
            print(f"  - {src}: {res}")

    elif cmd == "send-approved":
        from jobpilot.apply.email_sender import process_approved_queue
        logger.info("Processing approved queue within IST window...")
        sent = process_approved_queue(limit=5)
        print(f"\nDispatched {sent} approved emails.")

    elif cmd == "draft-gmail":
        from jobpilot.apply.gmail_drafts import draft_all_qualified_jobs_to_gmail
        print("=" * 60)
        print(f" JOBPILOT v2: GMAIL 1-CLICK BATCH DRAFT AUTOMATION")
        print(f" Criteria: Match Score >= {args.min_score}%, Has Verified HR Email")
        print("=" * 60)
        logger.info("Executing 1-click batch draft creation into Gmail Drafts folder...")
        res = draft_all_qualified_jobs_to_gmail(min_score=args.min_score, max_jobs=args.limit)
        if res.get("success"):
            print(f"\nSUCCESS! Created {res['drafted_count']} cold email drafts in your Gmail Drafts folder.")
            for j in res.get("jobs", []):
                print(f"  ✓ {j['company']} ({j['title']}) -> {j['recruiter_email']} [Match: {j['match_score']:.1f}%]")
            print("\n👉 Open https://mail.google.com/mail/u/0/#drafts to review and send!")
        else:
            print(f"\nFAILED: {res.get('error')}")

    elif cmd == "diagnose":
        from jobpilot.core.config import settings
        from jobpilot.core.db import get_pipeline_counts, get_today_llm_usage
        from jobpilot.apply.email_sender import get_sent_count_today, is_within_sending_hours

        print("=" * 60)
        print(" JOBPILOT v2 PRODUCTION DIAGNOSTIC REPORT")
        print("=" * 60)
        in_hours, hour_msg = is_within_sending_hours()
        print(f"Sending Window:   {hour_msg}")
        print(f"Emails Sent Today: {get_sent_count_today()} / {settings.daily_send_cap} (Daily Cap)")
        print(f"Gemini LLM Key:    {'CONFIGURED' if settings.gemini_api_key else 'MISSING'}")
        print(f"Gemini Model:      {settings.gemini_model}")
        print(f"SMTP User:         {settings.smtp_user or 'NOT CONFIGURED'}")
        print(f"SMTP Host:Port:    {settings.smtp_host}:{settings.smtp_port}")

        llm_usage = get_today_llm_usage()
        print(f"Today's Tokens:    {llm_usage['total_tokens']} tokens ({llm_usage['request_count']} calls)")

        counts = get_pipeline_counts()
        print("\nPipeline Funnel Counts:")
        for status, count in counts.items():
            print(f"  {status.capitalize():<15}: {count}")
        print("=" * 60)


if __name__ == "__main__":
    main()

