# PM Job Search Agent

An automated job search pipeline that collects Product Manager and Product Owner listings from major job boards, scores them against a candidate profile, and delivers a ranked email summary every other day.

## What It Does

- **Searches** 18 query/employment-type combinations via SerpAPI (Google Jobs engine)
- **Filters** by title relevance and NYC/NJ commuter zone location rules
- **Enriches** job listings with Responsibilities and Qualifications via Claude Haiku
- **Writes** deduplicated results to a Google Sheet (PM Job Leads)
- **Assesses** each job against a candidate profile via Claude Sonnet (0-100 score)
- **Flags** strong matches (score >= 75) with fit and gap bullets
- **Emails** a ranked summary with strong matches prominently at the top
- **Runs automatically** every other day at 6 AM EST via Modal cron

## Architecture

The system uses a 3-layer architecture:

| Layer | Role | Location |
|-------|------|----------|
| Directive | SOPs defining what each module does | `directives/` |
| Orchestration | Pipeline coordination and error handling | `execution/run_pm_job_search.py` |
| Execution | Deterministic Python scripts | `execution/` |

## Pipeline

The pipeline runs as two independent Modal functions with separate timeouts:

| Stage | Function | Timeout | What it does |
|-------|----------|---------|--------------|
| Stage 1 | `run_daily` | 600s | search → filter → enrich → update_sheet → spawn Stage 2 |
| Stage 2 | `run_assess` | 3600s | assess_jobs → process_drops → send_email |

Stage 1 finishes in ~5 min. Stage 2 runs independently with a 60-min budget, then sends the single summary email with both collection and assessment stats.

## Modules

**Module 1 — Job Search & Enrichment**
Searches SerpAPI, filters results, enriches R&Q via Claude Haiku, writes to PM Job Leads sheet.

**Module 2 — Profile Match Assessment**
Reads candidate profile documents, scores each job 0-100 via Claude Sonnet, flags strong matches, writes to PM Jobs Assessed sheet.

## Stack

- **Python 3.11**
- **Modal** — serverless compute + cron scheduling
- **SerpAPI** — Google Jobs search
- **Anthropic Claude** — Haiku (enrichment) + Sonnet (assessment)
- **Google Sheets + Drive + Gmail APIs** — storage and notifications

## Project Structure

```
execution/          # Pipeline scripts
  run_pm_job_search.py   # Orchestrator + Modal entry points
  search_jobs.py         # SerpAPI search
  filter_jobs.py         # Title + location filtering
  enrich_jobs.py         # Claude Haiku R&Q enrichment
  update_sheet.py        # Google Sheets writer (PM Job Leads)
  assess_jobs.py         # Claude Sonnet job-profile scoring
  process_drops.py       # Move flagged jobs to Dropped Jobs tab
  send_email.py          # Gmail summary email
  read_profile.py        # Load candidate profile documents
  gauth.py               # Shared Google OAuth helper

directives/         # Markdown SOPs
  pm_job_search.md       # Module 1 directive
  pm_job_assess.md       # Module 2 directive

Mohsen Profile/     # Candidate profile documents (not committed)
  # Place resume (.pdf/.docx/.txt), TMAY, and experience narratives here
```

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.template .env
# Fill in your API keys in .env
```

### 3. Google OAuth
Place `credentials.json` (OAuth 2.0 client) in the project root.
Run any script locally once to generate `token.json` via browser auth.

### 4. Add profile documents
Place your resume, TMAY, and experience narratives in `Mohsen Profile/`.
Supported formats: `.pdf`, `.docx`, `.txt`

### 5. Run locally
```bash
# Full pipeline (Stage 1 then Stage 2 sequentially)
python execution/run_pm_job_search.py

# Seed run (backfills last 30 days of jobs)
python execution/run_pm_job_search.py --seed

# Assessment only
python execution/run_pm_job_search.py --assess-only
```

## Modal Deployment

### Create secrets
```bash
# Google credentials
python execution/create_modal_secret.py

# Anthropic
python -m modal secret create anthropic-secret ANTHROPIC_API_KEY="sk-ant-..."

# SerpAPI
python -m modal secret create serpapi-secret SERPAPI_KEY="your-key"
```

### Upload profile documents
```bash
python -m modal volume create pm-profile
python -m modal volume put pm-profile "Mohsen Profile/" /profile/ --force
```

### Deploy
```bash
python -m modal deploy execution/run_pm_job_search.py
```

The cron fires every other day at 6 AM EST (`0 11 */2 * *` UTC).

### Manual Modal runs
```powershell
# Full pipeline (Stage 1 + spawns Stage 2)
python -m modal run execution/run_pm_job_search.py::run_daily

# Assessment only (Stage 2)
python -m modal run execution/run_pm_job_search.py::run_assess

# Process drops only
python -m modal run execution/run_pm_job_search.py::run_drops
```

## Output

| Sheet | Contents |
|-------|----------|
| PM Job Leads | All filtered + enriched job listings |
| PM Jobs Assessed | Scored jobs, sorted by Strong Match then date |
| Dropped Jobs | Audit trail of manually flagged/removed jobs |
