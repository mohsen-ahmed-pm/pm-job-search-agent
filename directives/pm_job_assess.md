# Directive: PM Job-Profile Match Assessor (Module 2)

## Purpose

After Module 1 populates "PM Job Leads" with filtered, enriched job listings, Module 2 scores
each job against the user's professional profile and writes results to "PM Jobs Assessed".
Jobs scoring >= 75/100 are flagged as "Strong Match" with fit and gap bullets.

---

## Inputs

1. **"PM Job Leads"** Google Sheet -- source of all job listings (Module 1 output)
2. **`Mohsen Profile/`** folder -- user's professional documents (resume, TMAY, experience narratives)

## Output

**"PM Jobs Assessed"** Google Sheet in the same Drive folder, with 13 columns (Job ID hidden):

| Col | Field | Notes |
|-----|-------|-------|
| A | Job Opened | ISO date |
| B | Position Name | |
| C | Company Name | |
| D | Employment Type | |
| E | Location Type | |
| F | Location | |
| G | Assessment Score | 0-100 |
| H | Strong Match | "Strong Match" or "" |
| I | Assessment Description | 6 bullets for >= 75 jobs; blank otherwise |
| J | Apply Link | |
| K | Drop Job | User enters "Yes" to flag for removal |
| L | Drop Reason | User enters reason when dropping |
| M | Job ID | Hidden, dedup key |

### Tabs in this spreadsheet

- **Jobs** -- active job assessments (the main working tab)
- **Dropped Jobs** -- audit trail of rows flagged and removed via the Drop Workflow

---

## Assessment Scoring Rules

- **Score 0-100**: Claude Sonnet evaluates fit based on experience, skills, industry, seniority, and location/type preferences
- **Score >= 75**: "Strong Match" flag set; 3 fit bullets + 3 gap bullets populated
- **Score < 75**: Flag blank; Assessment Description blank

### Assessment Description Format (Strong Match only)
```
Good Fit:
* [bullet 1]
* [bullet 2]
* [bullet 3]
Potential Gaps:
* [bullet 1]
* [bullet 2]
* [bullet 3]
```

---

## Sort Order

1. Primary: Strong Match descending -- all "Strong Match" rows at the top
2. Secondary: Job Opened descending -- newest first within each group

---

## Deduplication

Two layers of deduplication prevent duplicate rows:

1. **Job ID dedup** -- `assess_jobs.py` reads existing Job IDs from column M of "PM Jobs Assessed" at the start of each run and skips already-assessed jobs
2. **Title + Company dedup** -- if the same (title, company) appears multiple times in PM Job Leads with different job_ids (e.g. from FULLTIME vs CONTRACTOR queries), only the first occurrence is assessed

Both layers mean re-running is safe and idempotent.

---

## Drop Workflow

Use this to remove jobs that don't belong (e.g., hybrid roles outside NYC/NJ, wrong seniority).

### How to flag a job for removal:
1. Open "PM Jobs Assessed" -> "Jobs" tab
2. Enter **Yes** in column K (Drop Job) for the row you want to remove
3. Optionally enter a reason in column L (Drop Reason)

### How to move flagged rows to Dropped Jobs:

**Manual** -- run anytime after reviewing the sheet:
```bash
cd execution
python process_drops.py
```

**On Modal:**
```powershell
python -m modal run execution/run_pm_job_search.py::run_drops
```

**Automatic** -- runs as part of Stage 2 on every scheduled run. Any rows already flagged "Yes" are moved after assessment completes.

### What happens when process_drops runs:
- Rows with Drop Job = "Yes" are moved to the "Dropped Jobs" tab (preserving all columns including Drop Reason)
- The "Jobs" tab is cleaned and re-sorted
- Rows already present in "Dropped Jobs" (by Job ID) are not duplicated
- Returns (dropped_count, remaining_count) -- safe to run multiple times

---

## Profile Document Requirements

Place in `Mohsen Profile/` folder (project root):
- Resume (`.docx`, `.pdf`, or `.txt`)
- TMAY -- Tell Me About Yourself narrative
- Professional experience narratives

All files are concatenated into a single profile string passed to Claude.
Supported formats: `.txt`, `.docx`, `.pdf`.
Nested subdirectories are supported (Modal Volume may nest files under `/profile/profile/`).

---

## Tools / Scripts

| Script | Purpose |
|--------|---------|
| `execution/read_profile.py` | Loads profile docs from `Mohsen Profile/` or Modal Volume `/profile` |
| `execution/assess_jobs.py` | Full assessment pipeline: read -> assess -> write (Stage 2) |
| `execution/process_drops.py` | Move Drop Job=Yes rows to Dropped Jobs tab |
| `execution/run_pm_job_search.py` | Orchestrator: `run_assess` Modal function calls `assess_jobs()` then `process_drops()` |

---

## Email Summary

One email is sent per pipeline run, after assessment completes (Stage 2):
- **Subject:** `PM Job Search -- {X} strong matches | {N} new jobs ({date})`
- **Assessment block** (green, at top): strong match count, total assessed, link to PM Jobs Assessed
- **Collection block**: new jobs added count, breakdown by remote/hybrid/full-time/contract
- **Top 5 new listings** table
- **Two buttons**: "View All Jobs" (PM Job Leads) + "View Assessed Jobs" (PM Jobs Assessed)

---

## Schedule & Pipeline Architecture

The pipeline runs as two independent Modal functions, each with its own timeout:

| Stage | Function | Timeout | Steps |
|-------|----------|---------|-------|
| Stage 1 | `run_daily` | 600s | search → filter → enrich → update_sheet → spawn Stage 2 |
| Stage 2 | `run_assess` | 3600s | assess_jobs → process_drops → send_email |

- Schedule: every other day at 6 AM EST (Modal cron `0 11 */2 * *`)
- Stage 1 completes in ~5 minutes and fires Stage 2 asynchronously
- Stage 2 has a 60-minute budget -- handles up to ~150 jobs before timing out
- If "Mohsen Profile/" is empty, assessment is skipped gracefully (no pipeline failure)

---

## Error Handling

| Error | Behavior |
|-------|---------|
| Profile folder missing or empty | Skip assessment; log warning; pipeline continues |
| Claude API overloaded (529) | Retry up to 3x with 10s wait between attempts |
| SSL connection dropped mid-run | Rebuild Sheets API client and retry up to 3x |
| Claude API error on individual job | Log error, score = 0; continue to next job |
| Source sheet not found | Raise exception; pipeline fails with error email |
| JSON parse error from Claude | Log raw response, score = 0, continue |
| process_drops error | Log warning; pipeline continues (non-fatal) |

---

## Model

- **`claude-sonnet-4-6`** for all assessments
- Cost estimate: ~$0.01-$0.05 per run (only new jobs assessed after seed)
- Seed run (first time): ~$1.50 for ~93 jobs

---

## Running Manually

```bash
# Assess only (Module 2 standalone, local)
cd execution
python assess_jobs.py

# Assess only with assess-only flag
python run_pm_job_search.py --assess-only

# Move flagged drops (run after reviewing PM Jobs Assessed)
cd execution
python process_drops.py

# Full pipeline (local -- runs both stages sequentially)
python run_pm_job_search.py

# Seed run (resets PM Job Leads, assesses all jobs)
python run_pm_job_search.py --seed
```

```powershell
# On Modal -- run full pipeline (Stage 1 + spawns Stage 2)
python -m modal run execution/run_pm_job_search.py::run_daily

# On Modal -- run assessment only (Stage 2)
python -m modal run execution/run_pm_job_search.py::run_assess

# On Modal -- run drops only
python -m modal run execution/run_pm_job_search.py::run_drops
```
