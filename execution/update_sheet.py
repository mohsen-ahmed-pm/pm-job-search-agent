"""
update_sheet.py -- Google Sheets write for PM Job Leads.
Creates sheet if not found, reads existing Job IDs, appends new rows only.
"""

import os
from datetime import date
from gauth import get_creds
from googleapiclient.discovery import build

SHEET_NAME = "PM Job Leads"
FOLDER_ID = "1uTzfVqvPcS4ROh1F0dM4CQkmGj_CzwYH"

HEADERS = [
    "Job Opened", "Position Name", "Company Name", "Employment Type",
    "Location Type", "Location", "Summary", "Responsibilities",
    "Qualifications", "Salary", "Batch Date", "Apply Link", "Source", "Job ID"
]

# Column N = index 13 = Job ID (dedup key)
DEDUP_RANGE = "Jobs!N2:N"





def _get_or_create_spreadsheet(drive_svc, sheets_svc):
    query = (
        f"name='{SHEET_NAME}' and mimeType='application/vnd.google-apps.spreadsheet' "
        f"and '{FOLDER_ID}' in parents and trashed=false"
    )
    results = drive_svc.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        spreadsheet_id = files[0]["id"]
        print(f"[update_sheet] Found existing sheet: {spreadsheet_id}")
        return spreadsheet_id

    spreadsheet = sheets_svc.spreadsheets().create(body={
        "properties": {"title": SHEET_NAME},
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

    _init_headers(sheets_svc, spreadsheet_id, sheet_id)
    print(f"[update_sheet] Created new sheet: {spreadsheet_id}")
    return spreadsheet_id


def _get_sheet_id(sheets_svc, spreadsheet_id):
    """Get the actual sheetId for the Jobs tab."""
    meta = sheets_svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == "Jobs":
            return s["properties"]["sheetId"]
    return 0


def _init_headers(sheets_svc, spreadsheet_id, sheet_id):
    """Write headers, freeze row 1, and hide Job ID column (N = index 13)."""
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
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 13, "endIndex": 14},
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser"
            }}
        ]}
    ).execute()


def reset_sheet(sheets_svc, spreadsheet_id):
    """Clear all data rows and rewrite headers with current 14-column schema."""
    print("[update_sheet] Resetting sheet to new schema...")
    sheet_id = _get_sheet_id(sheets_svc, spreadsheet_id)
    sheets_svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range="Jobs!A1:Z"
    ).execute()
    _init_headers(sheets_svc, spreadsheet_id, sheet_id)
    print("[update_sheet] Sheet reset complete.")

def _get_existing_job_ids(sheets_svc, spreadsheet_id):
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=DEDUP_RANGE
    ).execute()
    values = result.get("values", [])
    return {row[0] for row in values if row}


def _parse_relative_date(posted_at):
    """Convert SerpAPI relative date string to ISO date (YYYY-MM-DD).
    Examples: '3 days ago' -> '2026-04-12', '2 weeks ago' -> '2026-04-01'
    Returns empty string if unparseable.
    """
    import re
    from datetime import date, timedelta
    if not posted_at:
        return ""
    text = posted_at.lower().strip()
    if text in ("today", "just posted", "active today"):
        return date.today().strftime("%Y-%m-%d")
    m = re.search(r"(\d+)\s*(hour|day|week|month)", text)
    if not m:
        return ""
    n = int(m.group(1))
    unit = m.group(2)
    delta_map = {"hour": timedelta(hours=n), "day": timedelta(days=n),
                 "week": timedelta(weeks=n), "month": timedelta(days=n * 30)}
    result = date.today() - delta_map[unit]
    return result.strftime("%Y-%m-%d")


def _job_to_row(job, batch_date):
    ext = job.get("detected_extensions") or {}
    highlights = job.get("job_highlights") or []
    responsibilities = ""
    qualifications = ""
    for h in highlights:
        title = (h.get("title") or "").lower()
        items = h.get("items") or []
        text = " | ".join(items)
        if "responsibilit" in title:
            responsibilities = text
        elif "qualif" in title or "require" in title or "skill" in title:
            qualifications = text

    apply_links = job.get("apply_options") or []
    apply_link = apply_links[0].get("link", "") if apply_links else ""
    if not apply_link:
        related = job.get("related_links") or []
        apply_link = related[0].get("link", "") if related else ""

    # Use enriched R&Q if job_highlights were blank
    if not responsibilities:
        responsibilities = job.get("_enriched_responsibilities", "")
    if not qualifications:
        qualifications = job.get("_enriched_qualifications", "")

    return [
        _parse_relative_date(ext.get("posted_at", "")),              # A Job Opened (ISO date)
        job.get("title", ""),                                         # B Position Name
        job.get("company_name", ""),                                  # C Company Name
        ext.get("schedule_type") or job.get("_employment_type_queried", ""),  # D Employment Type
        job.get("_location_type", ""),                                # E Location Type
        job.get("location", ""),                                      # F Location
        (job.get("description") or "")[:500],                        # G Summary
        responsibilities,                                             # H Responsibilities
        qualifications,                                               # I Qualifications
        ext.get("salary", ""),                                        # J Salary
        batch_date,                                                   # K Batch Date
        apply_link,                                                   # L Apply Link
        job.get("_source", ""),                                       # M Source
        job.get("_job_id", ""),                                       # N Job ID (hidden)
    ]


def update_sheet(filtered_jobs, do_reset=False):
    creds = get_creds()
    sheets_svc = build("sheets", "v4", credentials=creds)
    drive_svc = build("drive", "v3", credentials=creds)

    spreadsheet_id = _get_or_create_spreadsheet(drive_svc, sheets_svc)
    sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    if do_reset:
        reset_sheet(sheets_svc, spreadsheet_id)
    existing_ids = _get_existing_job_ids(sheets_svc, spreadsheet_id)
    print(f"[update_sheet] Existing job IDs in sheet: {len(existing_ids)}")

    batch_date = date.today().strftime("%Y-%m-%d")
    new_rows = []
    seen_title_company = set()
    for job in filtered_jobs:
        jid = job.get("_job_id", "")
        if jid and jid in existing_ids:
            continue
        key = (job.get("title", "").strip().lower(), job.get("company_name", "").strip().lower())
        if key in seen_title_company:
            print(f"[update_sheet] Skipping duplicate: {job.get('title','')} @ {job.get('company_name','')}")
            continue
        seen_title_company.add(key)
        new_rows.append(_job_to_row(job, batch_date))

    if new_rows:
        sheets_svc.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Jobs!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": new_rows}
        ).execute()
        # Sort by Job Opened (col A) descending; format date columns A and K as yyyy-mm-dd
        sheet_id = _get_sheet_id(sheets_svc, spreadsheet_id)
        date_fmt = {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [
                {"sortRange": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 14,
                    },
                    "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "DESCENDING"}]
                }},
                {"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1},
                    "cell": {"userEnteredFormat": date_fmt},
                    "fields": "userEnteredFormat.numberFormat"
                }},
                {"repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 10, "endColumnIndex": 11},
                    "cell": {"userEnteredFormat": date_fmt},
                    "fields": "userEnteredFormat.numberFormat"
                }},
            ]}
        ).execute()

    print(f"[update_sheet] Appended {len(new_rows)} new rows.")
    return len(new_rows), sheet_url


if __name__ == "__main__":
    fake = [{"_job_id": "test-001", "title": "Senior Product Manager", "company_name": "Acme",
             "location": "Remote", "_location_type": "Remote", "_employment_type_queried": "FULLTIME",
             "description": "Lead product strategy.", "detected_extensions": {"schedule_type": "Full-time",
             "salary": "$150k-$180k", "posted_at": "3 days ago"},
             "job_highlights": [{"title": "Responsibilities", "items": ["Define roadmap"]},
                                 {"title": "Qualifications", "items": ["5+ years PM"]}],
             "apply_options": [{"link": "https://example.com/apply"}]}]
    count, url = update_sheet(fake)
    print(f"Added {count} rows. Sheet: {url}")
