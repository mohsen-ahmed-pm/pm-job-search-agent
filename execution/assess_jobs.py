"""
assess_jobs.py -- Module 2: Job-Profile Match Assessor.
Reads 'PM Job Leads' sheet, scores each job against the user's profile via Claude Sonnet,
and writes results to 'PM Jobs Assessed' sheet. Only assesses new jobs (deduplication by Job ID).
"""

import os
import json
import ssl
import time
from datetime import date
from anthropic import Anthropic
from googleapiclient.discovery import build
from dotenv import load_dotenv
from gauth import get_creds

from read_profile import load_profile

load_dotenv()


FOLDER_ID = "1uTzfVqvPcS4ROh1F0dM4CQkmGj_CzwYH"
SOURCE_SHEET_NAME = "PM Job Leads"
OUTPUT_SHEET_NAME = "PM Jobs Assessed"

HEADERS = [
    "Job Opened", "Position Name", "Company Name", "Employment Type",
    "Location Type", "Location", "Assessment Score", "Strong Match",
    "Assessment Description", "Apply Link", "Drop Job", "Drop Reason", "Job ID"
]
# Column M = index 12 = Job ID (hidden, dedup key)
DEDUP_RANGE = "Jobs!M2:M"

STRONG_MATCH_THRESHOLD = 75

# PM Job Leads column indices (0-based, from A2:N read)
COL_JOB_OPENED    = 0   # A
COL_TITLE         = 1   # B
COL_COMPANY       = 2   # C
COL_EMP_TYPE      = 3   # D
COL_LOC_TYPE      = 4   # E
COL_LOCATION      = 5   # F
COL_SUMMARY       = 6   # G
COL_RESP          = 7   # H
COL_QUAL          = 8   # I
COL_SALARY        = 9   # J
COL_BATCH_DATE    = 10  # K
COL_APPLY_LINK    = 11  # L
COL_SOURCE        = 12  # M
COL_JOB_ID        = 13  # N





def _find_spreadsheet(drive_svc, name):
    """Find a spreadsheet by name in FOLDER_ID. Returns spreadsheet_id or None."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.spreadsheet' "
        f"and '{FOLDER_ID}' in parents and trashed=false"
    )
    results = drive_svc.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def _get_or_create_output_sheet(drive_svc, sheets_svc):
    """Find or create 'PM Jobs Assessed' spreadsheet."""
    spreadsheet_id = _find_spreadsheet(drive_svc, OUTPUT_SHEET_NAME)
    if spreadsheet_id:
        print(f"[assess_jobs] Found existing output sheet: {spreadsheet_id}")
        return spreadsheet_id

    spreadsheet = sheets_svc.spreadsheets().create(body={
        "properties": {"title": OUTPUT_SHEET_NAME},
        "sheets": [{"properties": {"title": "Jobs"}}]
    }).execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]
    sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]

    drive_svc.files().update(
        fileId=spreadsheet_id,
        addParents=FOLDER_ID,
        removeParents="root",
        fields="id, parents"
    ).execute()

    _init_output_headers(sheets_svc, spreadsheet_id, sheet_id)
    print(f"[assess_jobs] Created new output sheet: {spreadsheet_id}")
    return spreadsheet_id


def _get_sheet_id(sheets_svc, spreadsheet_id):
    meta = sheets_svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == "Jobs":
            return s["properties"]["sheetId"]
    return 0


def _init_output_headers(sheets_svc, spreadsheet_id, sheet_id):
    """Write headers, freeze row 1, hide Job ID column (M = index 12)."""
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Jobs!A1",
        valueInputOption="RAW",
        body={"values": [HEADERS]}
    ).execute()
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 12, "endIndex": 13},
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser"
            }}
        ]}
    ).execute()


def _get_existing_job_ids(sheets_svc, spreadsheet_id):
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=DEDUP_RANGE
    ).execute()
    values = result.get("values", [])
    return {row[0] for row in values if row}


def _read_source_jobs(sheets_svc, spreadsheet_id):
    """Read all job rows from 'PM Job Leads' sheet."""
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="Jobs!A2:N"
    ).execute()
    return result.get("values", [])


def _assess_job(client, profile_text, job_row):
    """Call Claude Sonnet to assess job fit. Returns dict with score, fit_bullets, gap_bullets."""
    def safe(idx):
        return job_row[idx] if idx < len(job_row) else ""

    title        = safe(COL_TITLE)
    company      = safe(COL_COMPANY)
    emp_type     = safe(COL_EMP_TYPE)
    loc_type     = safe(COL_LOC_TYPE)
    location     = safe(COL_LOCATION)
    summary      = safe(COL_SUMMARY)
    resp         = safe(COL_RESP)
    qual         = safe(COL_QUAL)
    salary       = safe(COL_SALARY)

    prompt = f"""You are assessing fit between a job posting and a candidate's professional profile.

CANDIDATE PROFILE:
{profile_text}

JOB POSTING:
Title: {title}
Company: {company}
Employment Type: {emp_type}
Location Type: {loc_type}
Location: {location}
Salary: {salary}
Responsibilities: {resp}
Qualifications: {qual}
Summary: {summary}

Score this match 0-100 based on how well the candidate's background aligns with the role.
Consider: relevant experience, skills match, industry fit, seniority alignment, and location/type preferences.

If score >= {STRONG_MATCH_THRESHOLD}, provide exactly 3 concise fit bullets and 3 concise gap bullets.
If score < {STRONG_MATCH_THRESHOLD}, return empty lists for both.

Return ONLY valid JSON with no extra text:
{{
  "score": <integer 0-100>,
  "fit_bullets": ["bullet 1", "bullet 2", "bullet 3"],
  "gap_bullets": ["bullet 1", "bullet 2", "bullet 3"]
}}"""

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}]
            )
            break
        except Exception as e:
            if "overloaded" in str(e).lower() and attempt < 2:
                print(f"[assess_jobs] API overloaded, waiting 30s (attempt {attempt+1}/3)...")
                time.sleep(10)
            else:
                raise
    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[assess_jobs] JSON parse error for '{title}' at {company}. Raw: {raw[:200]}")
        return {"score": 0, "fit_bullets": [], "gap_bullets": []}

    score = int(result.get("score", 0))
    fit = result.get("fit_bullets", [])
    gaps = result.get("gap_bullets", [])

    # Enforce: only populate bullets for strong matches
    if score < STRONG_MATCH_THRESHOLD:
        fit, gaps = [], []

    return {"score": score, "fit_bullets": fit, "gap_bullets": gaps}


def _format_description(fit_bullets, gap_bullets):
    """Format fit + gap bullets into a readable cell string."""
    if not fit_bullets and not gap_bullets:
        return ""
    lines = ["Good Fit:"]
    for b in fit_bullets:
        lines.append(f"• {b}")
    lines.append("Potential Gaps:")
    for b in gap_bullets:
        lines.append(f"• {b}")
    return "\n".join(lines)


def _build_output_row(job_row, assessment):
    """Build the 13-column output row for PM Jobs Assessed."""
    def safe(idx):
        return job_row[idx] if idx < len(job_row) else ""

    score = assessment["score"]
    strong = "Strong Match" if score >= STRONG_MATCH_THRESHOLD else ""
    description = _format_description(assessment["fit_bullets"], assessment["gap_bullets"])

    return [
        safe(COL_JOB_OPENED),   # A Job Opened
        safe(COL_TITLE),         # B Position Name
        safe(COL_COMPANY),       # C Company Name
        safe(COL_EMP_TYPE),      # D Employment Type
        safe(COL_LOC_TYPE),      # E Location Type
        safe(COL_LOCATION),      # F Location
        score,                   # G Assessment Score
        strong,                  # H Strong Match
        description,             # I Assessment Description
        safe(COL_APPLY_LINK),    # J Apply Link
        "",                      # K Drop Job (user fills)
        "",                      # L Drop Reason (user fills)
        safe(COL_JOB_ID),        # M Job ID (hidden)
    ]


def _sort_output_sheet(sheets_svc, spreadsheet_id, sheet_id):
    """Sort by Strong Match then Job Opened; format col A as yyyy-mm-dd date."""
    date_fmt = {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [
            {"sortRange": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,  # skip header
                    "startColumnIndex": 0,
                    "endColumnIndex": 13,
                },
                "sortSpecs": [
                    {"dimensionIndex": 7, "sortOrder": "DESCENDING"},  # Strong Match first
                    {"dimensionIndex": 0, "sortOrder": "DESCENDING"},  # then newest first
                ]
            }},
            {"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1},
                "cell": {"userEnteredFormat": date_fmt},
                "fields": "userEnteredFormat.numberFormat"
            }},
        ]}
    ).execute()


def assess_jobs():
    """
    Main entry point. Reads PM Job Leads, assesses new jobs, writes to PM Jobs Assessed.
    Returns (assessed_count, sheet_url).
    """
    profile_text = load_profile()
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    creds = get_creds()
    sheets_svc = build("sheets", "v4", credentials=creds)
    drive_svc = build("drive", "v3", credentials=creds)

    # Find source sheet
    source_id = _find_spreadsheet(drive_svc, SOURCE_SHEET_NAME)
    if not source_id:
        raise ValueError(f"Source sheet '{SOURCE_SHEET_NAME}' not found in Drive folder.")

    # Find or create output sheet
    output_id = _get_or_create_output_sheet(drive_svc, sheets_svc)
    sheet_url = f"https://docs.google.com/spreadsheets/d/{output_id}"

    # Load existing assessed job IDs (dedup)
    existing_ids = _get_existing_job_ids(sheets_svc, output_id)
    print(f"[assess_jobs] Already assessed: {len(existing_ids)} jobs")

    # Read all jobs from PM Job Leads
    all_rows = _read_source_jobs(sheets_svc, source_id)
    print(f"[assess_jobs] Jobs in PM Job Leads: {len(all_rows)}")

    # Filter to only new jobs (by job_id, then by title+company to catch upstream duplicates)
    new_rows = [r for r in all_rows if len(r) > COL_JOB_ID and r[COL_JOB_ID] not in existing_ids]
    seen_title_company = {}
    deduped_rows = []
    for row in new_rows:
        title = (row[COL_TITLE] if len(row) > COL_TITLE else "").strip().lower()
        company = (row[COL_COMPANY] if len(row) > COL_COMPANY else "").strip().lower()
        key = (title, company)
        if key not in seen_title_company:
            seen_title_company[key] = True
            deduped_rows.append(row)
        else:
            t = row[COL_TITLE] if len(row) > COL_TITLE else "?"
            c = row[COL_COMPANY] if len(row) > COL_COMPANY else "?"
            print(f"[assess_jobs] Skipping duplicate: {t} @ {c}")
    new_rows = deduped_rows
    print(f"[assess_jobs] New jobs to assess: {len(new_rows)}")

    if not new_rows:
        print("[assess_jobs] Nothing to assess.")
        return 0, sheet_url

    # Assess each new job, writing to Sheets in batches to avoid large payload errors
    WRITE_BATCH_SIZE = 20
    output_rows = []
    total_written = 0
    strong_match_count = 0

    for i, row in enumerate(new_rows, 1):
        title = row[COL_TITLE] if len(row) > COL_TITLE else "?"
        company = row[COL_COMPANY] if len(row) > COL_COMPANY else "?"
        print(f"[assess_jobs] ({i}/{len(new_rows)}) Assessing: {title} @ {company}")

        assessment = _assess_job(client, profile_text, row)
        if assessment["score"] >= STRONG_MATCH_THRESHOLD:
            strong_match_count += 1
        output_rows.append(_build_output_row(row, assessment))

        # Flush to Sheets every WRITE_BATCH_SIZE rows (and on the last row)
        if len(output_rows) == WRITE_BATCH_SIZE or i == len(new_rows):
            for attempt in range(3):
                try:
                    sheets_svc.spreadsheets().values().append(
                        spreadsheetId=output_id,
                        range="Jobs!A1",
                        valueInputOption="USER_ENTERED",
                        insertDataOption="INSERT_ROWS",
                        body={"values": output_rows}
                    ).execute()
                    break
                except ssl.SSLEOFError:
                    if attempt < 2:
                        print(f"[assess_jobs] SSL connection dropped, rebuilding client (attempt {attempt+1}/3)...")
                        sheets_svc = build("sheets", "v4", credentials=creds)
                    else:
                        raise
            total_written += len(output_rows)
            print(f"[assess_jobs] Written {total_written}/{len(new_rows)} rows to sheet.")
            output_rows = []
            time.sleep(1)  # brief pause between batch writes

        time.sleep(0.5)  # be gentle with the API

    # Sort: Strong Match first, then Job Opened descending
    sheet_id = _get_sheet_id(sheets_svc, output_id)
    _sort_output_sheet(sheets_svc, output_id, sheet_id)

    print(f"[assess_jobs] Done. Assessed {total_written} new jobs. Strong matches: {strong_match_count}")
    return total_written, strong_match_count, sheet_url


if __name__ == "__main__":
    count, url = assess_jobs()
    print(f"\nAssessed {count} jobs. Sheet: {url}")
