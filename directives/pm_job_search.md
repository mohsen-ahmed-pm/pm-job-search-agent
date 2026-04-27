# PM Job Search -- Directive

## Purpose
Automated collection of Product Manager and Product Owner job listings from major job boards via SerpAPI (Google Jobs engine). Filters for relevant opportunities, deduplicates, enriches R&Q via Claude Haiku, and writes to Google Sheets. Runs every other day at 6 AM EST via Modal cron.

This is Module 1 of 2. Module 2 (Job-Profile Match Assessor) runs as a separate Modal function immediately after and scores jobs against the user profile. One summary email is sent after Module 2 completes.

---

## Inputs
- SERPAPI_KEY environment variable
- Google OAuth credentials (credentials.json + token.json in project root)
- NOTIFICATION_EMAIL environment variable (consultmohsen@gmail.com)

## Outputs
- Google Sheet: "PM Job Leads" in folder ID 1uTzfVqvPcS4ROh1F0dM4CQkmGj_CzwYH
- Email summary sent by Module 2 after assessment completes (includes both collection + assessment stats)

---

## Search Queries

Run each query twice: once with employment_type:FULLTIME, once with employment_type:CONTRACTOR.
Total: 18 API calls/run (~270/month at every-other-day cadence, within 1,000/month Starter plan).

Date filter: date_posted:3days on all daily runs. date_posted:month on seed run only (--seed flag).

Queries:
1. "Product Manager" remote
2. "Product Manager" "New York" hybrid
3. "Senior Product Manager" remote OR hybrid "New York"
4. "Data Product Manager" remote OR hybrid
5. "AI Product Manager" remote OR hybrid
6. "Technical Product Manager" remote
7. "Product Manager" contract remote OR hybrid "New York"
8. "Product Owner" remote
9. "Product Owner" "New York" hybrid

---

## Post-Call Filters

### Title Filter -- KEEP if title contains (case-insensitive):
- Product Manager, Senior Product Manager, Principal Product Manager
- Lead Product Manager, Group Product Manager, Staff Product Manager
- Sr. PM, Sr PM
- Product Owner, Senior Product Owner, Lead Product Owner, Sr. PO, Sr PO

### Title Filter -- DISCARD if title contains:
- Director, VP, Vice President, Chief, Intern, Internship, Coordinator
- Associate Product Manager, APM

### Location Filter:
- Remote: KEEP regardless of stated location
- Hybrid: KEEP only if location is within the NYC/NJ Transit commuter zone:
  - NYC 5 boroughs: Manhattan, Brooklyn, Queens, Bronx, Staten Island
  - NJ Transit corridor: Jersey City, Hoboken, Newark, Harrison, Secaucus,
    Weehawken, Bayonne, Elizabeth, Kearny, Linden, Rahway, Woodbridge,
    Perth Amboy, New Brunswick, Trenton
  - Westchester County: White Plains, Yonkers, Mount Vernon
  - Long Island: any city/town on Long Island (Nassau, Suffolk counties)
- Hybrid outside above zones: DISCARD

---

## Google Sheet Schema

Sheet name: PM Job Leads
Drive folder ID: 1uTzfVqvPcS4ROh1F0dM4CQkmGj_CzwYH
Sorted by Job Opened descending (newest first).

Columns:
A  - Job Opened      (ISO date YYYY-MM-DD, converted from relative "X days ago")
B  - Position Name   (title)
C  - Company Name    (company_name)
D  - Employment Type (detected_extensions.schedule_type)
E  - Location Type   (derived: Remote / Hybrid / Remote (Verify))
F  - Location        (location)
G  - Summary         (description, first 500 chars)
H  - Responsibilities (job_highlights[Responsibilities] or Claude Haiku enrichment)
I  - Qualifications  (job_highlights[Qualifications] or Claude Haiku enrichment)
J  - Salary          (detected_extensions.salary)
K  - Batch Date      (run date YYYY-MM-DD)
L  - Apply Link      (apply_options[0].link)
M  - Source          (extracted from SerpAPI "via" field, e.g. "LinkedIn")
N  - Job ID          (job_id -- dedup key, hidden col)

---

## Deduplication

Two layers prevent duplicate entries:

1. **Job ID dedup** -- on each run, read all Job IDs from column N into a set; skip any incoming job whose job_id already exists
2. **Title + Company dedup** -- within each batch, skip any job whose (title, company) pair was already seen; prevents duplicates from FULLTIME vs CONTRACTOR query variants of the same listing

---

## Email Notification
To: NOTIFICATION_EMAIL
Subject: PM Job Search -- {X} strong matches | {N} new jobs ({date})

Sent by Module 2 after assessment completes. Body (in order):
1. **Module 2 Assessment block (green, prominent):**
   - Strong Matches count (score >= 75)
   - Total jobs assessed
   - Button: "View Strong Matches" -> PM Jobs Assessed sheet
2. **Module 1 block:**
   - New jobs added count
   - Breakdown: Remote / Hybrid / Full-time / Contract
3. Top 5 new listings table
4. Two buttons: "View All Jobs" (PM Job Leads) + "View Assessed Jobs" (PM Jobs Assessed)

On failure: send error email with exception details.

---

## Error Handling & Self-Annealing Notes

### SerpAPI rate limits
- Starter plan: 1,000 searches/month
- Add 1-2 second sleep between API calls to avoid hitting burst limits
- On 429 error: wait 60 seconds and retry once

### Google Sheets API
- Quota: 60 requests/minute per user
- Batch append rows rather than one-by-one to stay under quota

### Known edge cases
- Some jobs have no salary field -- write empty string, do not fail
- Some jobs have no job_highlights -- write empty string for Responsibilities/Qualifications
- job_id may be None for some results -- fall back to hash of (title + company + location)

---

## Learnings (updated after each run)
_To be populated after first run._
