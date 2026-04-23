"""
run_pm_job_search.py -- Orchestrator + Modal cron entry point.

Pipeline:
  1. search_jobs     -- SerpAPI calls (18 queries)
  2. filter_jobs     -- title + location filtering
  3. enrich_jobs     -- Claude Haiku R&Q extraction
  4. update_sheet    -- dedup + append to Google Sheets (PM Job Leads)
  5. assess_jobs     -- Claude Sonnet job-profile match scoring (PM Jobs Assessed)
  6. process_drops   -- move Drop Job=Yes rows to Dropped Jobs tab
  7. send_email      -- summary or error email

Schedule: 0 11 */2 * * UTC = 6:00 AM EST every other day

Usage:
  Local test:      python execution/run_pm_job_search.py
  Seed run:        python execution/run_pm_job_search.py --seed
  Modal deploy:    modal deploy execution/run_pm_job_search.py
  Modal seed run:  modal run execution/run_pm_job_search.py::run_seed
"""

import sys
import os
import argparse
import traceback
from datetime import date, datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Modal setup
# ---------------------------------------------------------------------------
import modal

app = modal.App("pm-job-search")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "google-api-python-client",
        "google-auth-httplib2",
        "google-auth-oauthlib",
        "google-search-results",
        "anthropic",
        "python-dotenv",
        "python-docx",
        "pdfplumber",
    )
    .add_local_dir("execution", remote_path="/root")
)

# Secrets -- set these in Modal dashboard or via `modal secret create`
serpapi_secret = modal.Secret.from_name("serpapi-secret")
google_secret = modal.Secret.from_name("google-oauth-secret")
anthropic_secret = modal.Secret.from_name("anthropic-secret")

profile_vol = modal.Volume.from_name("pm-profile", create_if_missing=True)


# ---------------------------------------------------------------------------
# Core pipeline (runs locally or inside Modal)
# ---------------------------------------------------------------------------

def _run_pipeline(seed_run: bool = False):
    """Execute the full job search pipeline. Returns summary dict."""
    # Local imports (works both locally and inside Modal container)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    from search_jobs import search_all
    from filter_jobs import filter_jobs
    from enrich_jobs import enrich_jobs
    from update_sheet import update_sheet
    from assess_jobs import assess_jobs
    from process_drops import process_drops
    from send_email import send_summary, send_error

    run_date = date.today().strftime("%Y-%m-%d")
    print(f"[run_pm_job_search] Starting pipeline. Date={run_date} seed={seed_run}")

    try:
        # Step 1: Search
        raw_jobs = search_all(seed_run=seed_run)

        # Step 2: Filter
        filtered = filter_jobs(raw_jobs)

        # Step 3: Enrich R&Q via Claude Haiku
        filtered = enrich_jobs(filtered)

        # Step 4: Update sheet
        new_count, sheet_url = update_sheet(filtered, do_reset=seed_run)

        # Step 5: Assess jobs (Module 2)
        assessed_count = 0
        strong_match_count = 0
        assessed_url = None
        try:
            assessed_count, strong_match_count, assessed_url = assess_jobs()
            print(f"[run_pm_job_search] Assessed {assessed_count} new jobs. Strong matches: {strong_match_count}. Sheet: {assessed_url}")
        except ValueError as e:
            # Profile folder missing or empty — skip assessment, don't fail the pipeline
            print(f"[run_pm_job_search] Skipping assessment: {e}")

        # Step 6a: Build breakdown for email
        breakdown = {"remote": 0, "hybrid": 0, "fulltime": 0, "contract": 0}
        top_jobs = []
        for job in filtered:
            loc = (job.get("_location_type") or "").lower()
            if loc == "remote":
                breakdown["remote"] += 1
            elif loc == "hybrid":
                breakdown["hybrid"] += 1
            emp = (job.get("detected_extensions") or {}).get("schedule_type", "")
            if not emp:
                emp = job.get("_employment_type_queried", "")
            emp_lower = emp.lower()
            if "contract" in emp_lower:
                breakdown["contract"] += 1
            else:
                breakdown["fulltime"] += 1

            apply_links = job.get("apply_options") or []
            apply_link = apply_links[0].get("link", "") if apply_links else ""
            top_jobs.append({
                "title": job.get("title", ""),
                "company": job.get("company_name", ""),
                "apply_link": apply_link,
            })

        # Step 6: Process drops (move flagged rows to Dropped Jobs tab)
        try:
            dropped_count, _ = process_drops()
            if dropped_count:
                print(f"[run_pm_job_search] Moved {dropped_count} dropped jobs to Dropped Jobs tab.")
        except Exception as drop_err:
            print(f"[run_pm_job_search] process_drops warning: {drop_err}")

        # Step 7: Send summary email
        send_summary(
            new_count=new_count,
            breakdown=breakdown,
            top_jobs=top_jobs[:5],
            sheet_url=sheet_url,
            run_date=run_date,
            assessed_count=assessed_count,
            strong_match_count=strong_match_count,
            assessed_url=assessed_url,
        )

        print(f"[run_pm_job_search] Pipeline complete. New jobs: {new_count}")
        return {"status": "ok", "new_count": new_count, "sheet_url": sheet_url}

    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"[run_pm_job_search] ERROR: {error_msg}", file=sys.stderr)
        try:
            from send_email import send_error
            send_error(error_message=error_msg, run_date=run_date)
        except Exception as email_err:
            print(f"[run_pm_job_search] Could not send error email: {email_err}", file=sys.stderr)
        raise


# ---------------------------------------------------------------------------
# Modal entry points
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=[serpapi_secret, google_secret, anthropic_secret],
    volumes={"/profile": profile_vol},
    schedule=modal.Cron("0 11 */2 * *"),  # 6:00 AM EST every other day (UTC-5)
    timeout=1800,
)
def run_daily():
    """Scheduled daily run at 6 AM EST."""
    return _run_pipeline(seed_run=False)


@app.function(
    image=image,
    secrets=[serpapi_secret, google_secret, anthropic_secret],
    volumes={"/profile": profile_vol},
    timeout=1800,
)
def run_seed():
    """One-time seed run using date_posted:month to backfill existing listings."""
    return _run_pipeline(seed_run=True)


# ---------------------------------------------------------------------------
# Local CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PM Job Search pipeline")
    parser.add_argument("--seed", action="store_true", help="Seed run: use date_posted:month")
    args = parser.parse_args()

    # Load .env for local runs
    from dotenv import load_dotenv
    load_dotenv()

    result = _run_pipeline(seed_run=args.seed)
    print(f"Result: {result}")
