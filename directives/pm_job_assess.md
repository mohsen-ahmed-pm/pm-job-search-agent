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

- On each run, `assess_jobs.py` reads existing Job IDs from column M of "PM Jobs Assessed"
- Only jobs NOT already present are assessed and appended
- This means: regular runs assess only new jobs from Module 1; re-running is safe

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

**Automatic** -- runs as step 6 of the pipeline on every scheduled run. Any rows already flagged "Yes" are moved before the email goes out.

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

---

## Tools / Scripts

| Script | Purpose |
|--------|---------|
| `execution/read_profile.py` | Loads profile docs from `Mohsen Profile/` |
| `execution/assess_jobs.py` | Full assessment pipeline: read -> assess -> write |
| `execution/process_drops.py` | Move Drop Job=Yes rows to Dropped Jobs tab |
| `execution/run_pm_job_search.py` | Calls `assess_jobs()` then `process_drops()` after `update_sheet()` |

---

## Email Summary

Module 2 results are included in the pipeline summary email (sent by `send_email.py`):
- **Subject:** `PM Job Search -- {X} strong matches | {N} new jobs ({date})`
- **Assessment block** (green, at top of email): strong match count, total assessed, link to PM Jobs Assessed
- **Two CTA buttons** at bottom: "View All Jobs" (PM Job Leads) + "View Assessed Jobs" (PM Jobs Assessed)

If assessment is skipped (profile folder empty), the email still sends with Module 1 stats only.

---

## Schedule

Module 2 runs as step 5 of the Module 1 pipeline:
- Every other day at 6 AM EST (Modal cron `0 11 */2 * *`)
- If "Mohsen Profile/" is empty, assessment is skipped gracefully (no pipeline failure)

---

## Error Handling

| Error | Behavior |
|-------|---------|
| Profile folder missing or empty | Skip assessment; log warning; pipeline continues |
| Claude API error on individual job | Log error, score = 0; continue to next job |
| Source sheet not found | Raise exception; pipeline fails |
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
# Assess only (Module 2 standalone)
cd execution
python assess_jobs.py

# Move flagged drops (run after reviewing PM Jobs Assessed)
cd execution
python process_drops.py

# Full pipeline including assessment and drop processing
python run_pm_job_search.py

# Seed run (resets PM Job Leads, assesses all jobs)
python run_pm_job_search.py --seed
```