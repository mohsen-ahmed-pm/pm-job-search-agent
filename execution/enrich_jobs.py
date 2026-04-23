"""
enrich_jobs.py -- Enrich job listings with Responsibilities and Qualifications
extracted from the full description using Claude Haiku.

Only calls Claude for jobs where job_highlights returned insufficient R&Q data.
Cost: ~$0.01 per run at 100 jobs.
"""

import os
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

EXTRACTION_PROMPT = """Extract the Responsibilities and Qualifications from this job description.

Return ONLY valid JSON in this exact format:
{
  "responsibilities": ["responsibility 1", "responsibility 2", ...],
  "qualifications": ["qualification 1", "qualification 2", ...]
}

If you cannot find responsibilities or qualifications, return empty lists.
Do not include any text outside the JSON.

Job description:
"""


def _needs_enrichment(job):
    """Return True if job is missing R&Q from job_highlights."""
    highlights = job.get("job_highlights") or []
    has_resp = False
    has_qual = False
    for h in highlights:
        title = (h.get("title") or "").lower()
        items = h.get("items") or []
        if "responsibilit" in title and items:
            has_resp = True
        if ("qualif" in title or "require" in title or "skill" in title) and items:
            has_qual = True
    return not (has_resp and has_qual)


def _extract_rq(description):
    """Call Claude Haiku to extract R&Q from description text. Returns (responsibilities_str, qualifications_str)."""
    if not description or len(description.strip()) < 100:
        return "", ""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": EXTRACTION_PROMPT + description[:4000]}
            ]
        )
        raw = message.content[0].text.strip()
        # Extract JSON even if there's surrounding text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return "", ""
        data = json.loads(raw[start:end])
        responsibilities = " | ".join(data.get("responsibilities") or [])
        qualifications = " | ".join(data.get("qualifications") or [])
        return responsibilities, qualifications
    except Exception as e:
        print(f"[enrich_jobs] Extraction error: {e}")
        return "", ""


def enrich_jobs(filtered_jobs):
    """
    For jobs with missing R&Q, use Claude Haiku to extract from description.
    Injects _responsibilities and _qualifications fields into each job dict.
    Returns the same list (mutated in place).
    """
    needs_enrichment = [j for j in filtered_jobs if _needs_enrichment(j)]
    total = len(filtered_jobs)
    to_enrich = len(needs_enrichment)
    print(f"[enrich_jobs] {to_enrich}/{total} jobs need R&Q enrichment")

    for i, job in enumerate(needs_enrichment, 1):
        description = job.get("description") or ""
        resp, qual = _extract_rq(description)
        job["_enriched_responsibilities"] = resp
        job["_enriched_qualifications"] = qual
        if (i % 10) == 0 or i == to_enrich:
            print(f"[enrich_jobs] Enriched {i}/{to_enrich}")

    print(f"[enrich_jobs] Enrichment complete.")
    return filtered_jobs


if __name__ == "__main__":
    # Quick test
    test_jobs = [
        {
            "title": "Senior Product Manager",
            "company_name": "Test Co",
            "job_highlights": [],
            "description": (
                "We are looking for a Senior PM to join our team. "
                "Responsibilities: Define product roadmap. Work with engineering teams. "
                "Conduct user research. Prioritize features based on business impact. "
                "Qualifications: 5+ years of product management experience. "
                "Strong analytical skills. Experience with agile methodologies. "
                "Excellent communication skills."
            ),
        }
    ]
    result = enrich_jobs(test_jobs)
    print("Responsibilities:", result[0].get("_enriched_responsibilities"))
    print("Qualifications:", result[0].get("_enriched_qualifications"))
