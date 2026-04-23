"""
process_drops.py -- Move flagged rows from PM Jobs Assessed Jobs tab to Dropped Jobs tab.
Rows where col K (Drop Job) = Yes are moved to the Dropped Jobs tab.
Safe to run multiple times -- deduplicates by Job ID.
Manual: cd execution && python process_drops.py
Auto:   called by run_pm_job_search.py as step 6 of pipeline.
"""

import os, time
from googleapiclient.discovery import build
from dotenv import load_dotenv
from gauth import get_creds
load_dotenv()

FOLDER_ID = "1uTzfVqvPcS4ROh1F0dM4CQkmGj_CzwYH"
OUTPUT_SHEET_NAME = "PM Jobs Assessed"
DROPPED_TAB_NAME = "Dropped Jobs"
COL_DROP_JOB = 10
COL_JOB_ID   = 12
HEADERS = [
    "Job Opened", "Position Name", "Company Name", "Employment Type",
    "Location Type", "Location", "Assessment Score", "Strong Match",
    "Assessment Description", "Apply Link", "Drop Job", "Drop Reason", "Job ID"
]
DATE_FMT = {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}





def _find_spreadsheet(drive_svc, name):
    q = "name='" + name + "' and mimeType='application/vnd.google-apps.spreadsheet' and '" + FOLDER_ID + "' in parents and trashed=false"
    results = drive_svc.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def _get_tab_id(sheets_svc, spreadsheet_id, tab_name):
    meta = sheets_svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == tab_name:
            return s["properties"]["sheetId"]
    return None


def _ensure_dropped_tab(sheets_svc, spreadsheet_id):
    tab_id = _get_tab_id(sheets_svc, spreadsheet_id, DROPPED_TAB_NAME)
    if tab_id is not None:
        return tab_id
    resp = sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": DROPPED_TAB_NAME}}}]}
    ).execute()
    tab_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=DROPPED_TAB_NAME + "!A1",
        valueInputOption="RAW",
        body={"values": [HEADERS]}
    ).execute()
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [
            {"updateSheetProperties": {
                "properties": {"sheetId": tab_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": tab_id, "dimension": "COLUMNS", "startIndex": 12, "endIndex": 13},
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser"
            }}
        ]}
    ).execute()
    print("[process_drops] Created Dropped Jobs tab.")
    return tab_id


def _get_dropped_job_ids(sheets_svc, spreadsheet_id):
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=DROPPED_TAB_NAME + "!M2:M"
    ).execute()
    return {r[0] for r in result.get("values", []) if r}


def _pad(row, n=13):
    return list(row) + [""] * (n - len(row))


def process_drops():
    creds = get_creds()
    sheets_svc = build("sheets", "v4", credentials=creds)
    drive_svc  = build("drive",  "v3", credentials=creds)

    spreadsheet_id = _find_spreadsheet(drive_svc, OUTPUT_SHEET_NAME)
    if not spreadsheet_id:
        print("[process_drops] PM Jobs Assessed not found. Skipping.")
        return 0, 0

    _ensure_dropped_tab(sheets_svc, spreadsheet_id)

    all_rows = sheets_svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range="Jobs!A2:M"
    ).execute().get("values", [])

    if not all_rows:
        print("[process_drops] Jobs tab is empty.")
        return 0, 0

    already_dropped = _get_dropped_job_ids(sheets_svc, spreadsheet_id)
    drop_rows, keep_rows = [], []
    for row in all_rows:
        p = _pad(row)
        flagged = p[COL_DROP_JOB].strip().lower() == "yes"
        jid = p[COL_JOB_ID].strip()
        if flagged and jid not in already_dropped:
            drop_rows.append(p)
        elif not flagged:
            keep_rows.append(p)

    if drop_rows:
        sheets_svc.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=DROPPED_TAB_NAME + "!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": drop_rows}
        ).execute()
        dtid = _get_tab_id(sheets_svc, spreadsheet_id, DROPPED_TAB_NAME)
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"repeatCell": {
                "range": {"sheetId": dtid, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1},
                "cell": {"userEnteredFormat": DATE_FMT},
                "fields": "userEnteredFormat.numberFormat"
            }}]}
        ).execute()

    sheets_svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range="Jobs!A2:M"
    ).execute()

    if keep_rows:
        sheets_svc.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id, range="Jobs!A1",
            valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
            body={"values": keep_rows}
        ).execute()
        time.sleep(0.5)
        jtid = _get_tab_id(sheets_svc, spreadsheet_id, "Jobs")
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [
                {"sortRange": {
                    "range": {"sheetId": jtid, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 13},
                    "sortSpecs": [
                        {"dimensionIndex": 7, "sortOrder": "DESCENDING"},
                        {"dimensionIndex": 0, "sortOrder": "DESCENDING"},
                    ]
                }},
                {"repeatCell": {
                    "range": {"sheetId": jtid, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1},
                    "cell": {"userEnteredFormat": DATE_FMT},
                    "fields": "userEnteredFormat.numberFormat"
                }},
            ]}
        ).execute()

    print("[process_drops] Dropped " + str(len(drop_rows)) + " rows. Remaining: " + str(len(keep_rows)) + ".")
    return len(drop_rows), len(keep_rows)


if __name__ == "__main__":
    d, r = process_drops()
    print("Done. " + str(d) + " rows moved to Dropped Jobs. " + str(r) + " rows remain.")