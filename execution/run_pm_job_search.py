"""
run_pm_job_search.py -- Orchestrator + Modal cron entry point.

Pipeline (two stages with independent timeouts):
  Stage 1 - run_daily  (~5 min, 600s timeout):
    1. search_jobs     -- SerpAPI calls (18 queries)
    2. filter_jobs     -- title + location filtering
    3. enrich_jobs     -- Claude Haiku R&Q extraction
    4. update_sheet    -- dedup + append to Google Sheets (PM Job Leads)
    5. saves stats to modal.Dict, spawns run_assess

  Stage 2 - run_assess  (up to 60 min, 3600s timeout):
    5. assess_jobs     -- Claude Sonnet job-profile match scoring (PM Jobs Assessed)
    6. process_drops   -- move Drop Job=Yes rows to Dropped Jobs tab
    7. send_email      -- one summary email with both collection + assessment stats

Schedule: 0 11 */2 * * UTC = 6:00 AM EST every other day

Usage:
  Local test:           python execution/run_pm_job_search.py
  Seed run:             python execution/run_pm_job_search.py --seed
  Assess only (local):  python execution/run_pm_job_search.py --assess-only
  Modal deploy:         modal deploy execution/run_pm_job_search.py
  Modal full run:       modal run execution/run_pm_job_search.py::run_full
  Modal assess only:    modal run execution/run_pm_job_search.py::run_assess
  Modal drops only:     modal run execution/run_pm_job_search.py::run_drops
"""

import sys
import os
import argparse
import traceback
from datetime import date

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

serpapi_secret = modal.Secret.from_name("serpapi-secret")
google_secret = modal.Secret.from_name("google-oauth-secret")
anthropic_secret = modal.Secret.from_name("anthropic-secret")

profile_vol = modal.Volume.from_name("pm-profile", create_if_missing=True)

# Shared state between Stage 1 and Stage 2 (Modal serverless key-value store)
run_state = modal.Dict.from_name("pm-job-search-state", create_if_missing=True)


# ---------------------------------------------------------------------------
# Stage 1: Collect (search + sheet)
# ---------------------------------------------------------------------------

def _run_collect(seed_run: bool = False):
    """Steps 1-4: search, filter, enrich, write to PM Job Leads. Saves stats for Stage 2."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    from search_jobs import search_all
    from filter_jobs import filter_jobs
    from enrich_jobs import enrich_jobs
    from update_sheet import update_sheet
    from send_email import send_error

    run_date = date.today().strftime("%Y-%m-%d")
    print(f"[run_pm_job_search] Stage 1: collect. Date={run_date} seed={seed_run}")

    try:
        raw_jobs = search_all(seed_run=seed_run)
        filtered = filter_jobs(raw_jobs)
        filtered = enrich_jobs(filtered)
        new_count, sheet_url = update_sheet(filtered, do_reset=seed_run)

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
            if "contract" in emp.lower():
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

        # Save for Stage 2 to include in the single summary email
        run_state["collect"] = {
            "new_count": new_count,
            "sheet_url": sheet_url,
            "breakdown": breakdown,
            "top_jobs": top_jobs[:5],
            "run_date": run_date,
        }

        print(f"[run_pm_job_search] Stage 1 complete. New jobs: {new_count}")
        return {"status": "ok", "new_count": new_count, "sheet_url": sheet_url}

    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"[run_pm_job_search] Stage 1 ERROR: {error_msg}", file=sys.stderr)
        try:
            send_error(error_message=error_msg, run_date=date.today().strftime("%Y-%m-%d"))
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Stage 2: Assess (Claude scoring + drops + email)
# ---------------------------------------------------------------------------

def _run_assess():
    """Steps 5-7: assess new jobs, process drops, send one full summary email."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    from assess_jobs import assess_jobs
    from process_drops import process_drops
    from send_email import send_summary, send_error

    run_date = date.today().strftime("%Y-%m-%d")
    print(f"[run_pm_job_search] Stage 2: assess. Date={run_date}")

    # Load Stage 1 stats (may be absent on standalone assess-only run)
    collect = run_state.get("collect") or {}
    new_count  = collect.get("new_count", 0)
    sheet_url  = collect.get("sheet_url", "")
    breakdown  = collect.get("breakdown", {"remote": 0, "hybrid": 0, "fulltime": 0, "contract": 0})
    top_jobs   = collect.get("top_jobs", [])
    run_date   = collect.get("run_date", run_date)

    try:
        assessed_count, strong_match_count, assessed_url = assess_jobs()
        print(f"[run_pm_job_search] Assessed {assessed_count} jobs. Strong matches: {strong_match_count}")

        try:
            dropped_count, _ = process_drops()
            if dropped_count:
                print(f"[run_pm_job_search] Moved {dropped_count} dropped jobs.")
        except Exception as drop_err:
            print(f"[run_pm_job_search] process_drops warning: {drop_err}")

        send_summary(
            new_count=new_count,
            breakdown=breakdown,
            top_jobs=top_jobs,
            sheet_url=sheet_url,
            run_date=run_date,
            assessed_count=assessed_count,
            strong_match_count=strong_match_count,
            assessed_url=assessed_url,
        )

        print(f"[run_pm_job_search] Stage 2 complete.")
        return {"assessed_count": assessed_count, "strong_match_count": strong_match_count}

    except ValueError as e:
        print(f"[run_pm_job_search] Skipping assessment: {e}")
        send_summary(
            new_count=new_count,
            breakdown=breakdown,
            top_jobs=top_jobs,
            sheet_url=sheet_url,
            run_date=run_date,
        )
        return {"assessed_count": 0, "strong_match_count": 0}
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"[run_pm_job_search] Stage 2 ERROR: {error_msg}", file=sys.stderr)
        try:
            send_error(error_message=error_msg, run_date=run_date)
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Modal entry points
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=[serpapi_secret, google_secret, anthropic_secret],
    volumes={"/profile": profile_vol},
    schedule=modal.Cron("0 11 */2 * *"),
    timeout=600,
)
def run_daily():
    """Scheduled run: collect jobs (Stage 1), then spawn assessment as a separate function."""
    _run_collect(seed_run=False)
    run_assess.spawn()


@app.function(
    image=image,
    secrets=[serpapi_secret, google_secret, anthropic_secret],
    volumes={"/profile": profile_vol},
    timeout=600,
)
def run_seed():
    """One-time seed run: collect with date_posted:month, then spawn assessment."""
    _run_collect(seed_run=True)
    run_assess.spawn()


@app.function(
    image=image,
    secrets=[google_secret, anthropic_secret],
    volumes={"/profile": profile_vol},
    timeout=3600,
)
def run_assess():
    """Assess unscored jobs and process drops. Runs independently with 60-min timeout."""
    return _run_assess()


@app.function(
    image=image,
    secrets=[serpapi_secret, google_secret, anthropic_secret],
    volumes={"/profile": profile_vol},
    timeout=4200,
)
def run_full():
    """Manual end-to-end run: Stage 1 + Stage 2 in one session (avoids spawn cancellation)."""
    _run_collect(seed_run=False)
    _run_assess()


@app.function(
    image=image,
    secrets=[google_secret],
    timeout=300,
)
def run_drops():
    """Move Drop Job=Yes rows from PM Jobs Assessed to the Dropped Jobs tab."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from process_drops import process_drops
    dropped, remaining = process_drops()
    print(f"[run_drops] Done. Dropped: {dropped}, Remaining: {remaining}")
    return {"dropped": dropped, "remaining": remaining}


# ---------------------------------------------------------------------------
# Local CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PM Job Search pipeline")
    parser.add_argument("--seed", action="store_true", help="Seed run: use date_posted:month")
    parser.add_argument("--assess-only", action="store_true", help="Run assessment stage only")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    if args.assess_only:
        result = _run_assess()
    else:
        result = _run_collect(seed_run=args.seed)
        print("Collection done. Run --assess-only to run assessment separately.")
    print(f"Result: {result}")
