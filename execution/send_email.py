"""
send_email.py -- Gmail summary / error email for PM job search runs.
Uses Gmail API via Google OAuth (same credentials as Sheets/Drive).
"""

import os
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from gauth import get_creds
from googleapiclient.discovery import build


TO_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "consultmohsen@gmail.com")





def _send(subject, html_body):
    creds = get_creds()
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = TO_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"[send_email] Sent: {subject}")


def send_summary(new_count, breakdown, top_jobs, sheet_url, run_date,
                 assessed_count=0, strong_match_count=0, assessed_url=None):
    """
    Send run summary email with Module 2 assessment stats (prominent) and Module 1 stats.

    breakdown: dict with keys remote, hybrid, fulltime, contract
    top_jobs: list of dicts with keys title, company, apply_link (up to 5)
    assessed_count: total jobs assessed in this run
    strong_match_count: jobs scoring >= 75
    assessed_url: URL to PM Jobs Assessed sheet
    """
    subject = f"PM Job Search -- {strong_match_count} strong matches | {new_count} new jobs ({run_date})"

    # Module 2 section — only shown if assessment ran
    assessment_section = ""
    assessed_btn = ""
    if assessed_url:
        assessment_section = f"""
    <div style='background:#e6f4ea;border-left:4px solid #34a853;padding:16px 20px;border-radius:4px;margin-bottom:24px'>
      <h2 style='margin:0 0 12px 0;color:#1e7e34'>Profile Match Assessment</h2>
      <table style='border-collapse:collapse'>
        <tr>
          <td style='padding:4px 16px 4px 0;font-size:28px;font-weight:bold;color:#1e7e34'>{strong_match_count}</td>
          <td style='padding:4px 0;color:#555;font-size:15px'>Strong Matches (score &ge; 75)</td>
        </tr>
        <tr>
          <td style='padding:4px 16px 4px 0;font-size:22px;font-weight:bold;color:#555'>{assessed_count}</td>
          <td style='padding:4px 0;color:#555;font-size:15px'>Total Jobs Assessed</td>
        </tr>
      </table>
      <br>
      <a href='{assessed_url}' style='background:#34a853;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;font-weight:bold'>View Strong Matches &rarr;</a>
    </div>
    """

    top_rows = ""
    for j in top_jobs[:5]:
        link = j.get("apply_link", "#")
        top_rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{j.get('title','')}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{j.get('company','')}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>"
            f"<a href='{link}'>Apply</a></td>"
            f"</tr>"
        )

    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333;max-width:640px;margin:0 auto;padding:24px'>
    <h2 style='color:#1a73e8;margin-bottom:4px'>PM Job Search Run</h2>
    <p style='color:#888;margin-top:0'>{run_date}</p>

    {assessment_section}

    <div style='background:#f8f9fa;border-left:4px solid #1a73e8;padding:16px 20px;border-radius:4px;margin-bottom:24px'>
      <h3 style='margin:0 0 12px 0;color:#1a73e8'>New Jobs Collected</h3>
      <p style='margin:0 0 10px 0'><strong>{new_count}</strong> new jobs added to PM Job Leads</p>
      <table style='border-collapse:collapse'>
        <tr><td style='padding:3px 16px 3px 0;color:#555'>Remote</td><td style='padding:3px 0'><strong>{breakdown.get('remote',0)}</strong></td></tr>
        <tr><td style='padding:3px 16px 3px 0;color:#555'>Hybrid</td><td style='padding:3px 0'><strong>{breakdown.get('hybrid',0)}</strong></td></tr>
        <tr><td style='padding:3px 16px 3px 0;color:#555'>Full-time</td><td style='padding:3px 0'><strong>{breakdown.get('fulltime',0)}</strong></td></tr>
        <tr><td style='padding:3px 16px 3px 0;color:#555'>Contract</td><td style='padding:3px 0'><strong>{breakdown.get('contract',0)}</strong></td></tr>
      </table>
    </div>

    <h3>Top New Listings</h3>
    <table style='border-collapse:collapse;width:100%'>
      <tr style='background:#f1f3f4'>
        <th style='padding:8px 12px;text-align:left'>Title</th>
        <th style='padding:8px 12px;text-align:left'>Company</th>
        <th style='padding:8px 12px;text-align:left'>Link</th>
      </tr>
      {top_rows}
    </table>
    <br>
    <p>
      <a href='{sheet_url}' style='background:#1a73e8;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;margin-right:12px'>View All Jobs</a>
      {"<a href='" + assessed_url + "' style='background:#34a853;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px'>View Assessed Jobs</a>" if assessed_url else ""}
    </p>
    </body></html>
    """

    _send(subject, html)


def send_error(error_message, run_date):
    """Send error notification email when the run fails."""
    subject = f"PM Job Search -- ERROR on {run_date}"
    html = f"""
    <html><body style='font-family:Arial,sans-serif;color:#333'>
    <h2 style='color:#d93025'>PM Job Search -- Run Failed</h2>
    <p><strong>Date:</strong> {run_date}</p>
    <p>The daily job search run encountered an error and did not complete.</p>
    <h3>Error Details</h3>
    <pre style='background:#f8f9fa;padding:16px;border-radius:4px;overflow-x:auto'>{error_message}</pre>
    <p>Please check the execution logs and rerun manually if needed.</p>
    </body></html>
    """
    _send(subject, html)


if __name__ == "__main__":
    from datetime import date
    print("Sending test summary email...")
    send_summary(
        new_count=7,
        breakdown={"remote": 5, "hybrid": 2, "fulltime": 4, "contract": 3},
        top_jobs=[
            {"title": "Senior Product Manager", "company": "Acme Corp", "apply_link": "https://example.com"},
            {"title": "AI Product Manager", "company": "Tech Co", "apply_link": "https://example.com"},
        ],
        sheet_url="https://docs.google.com/spreadsheets/d/test",
        run_date=date.today().strftime("%Y-%m-%d")
    )
    print("Done -- check your inbox.")
