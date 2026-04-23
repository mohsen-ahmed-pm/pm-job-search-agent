"""
search_jobs.py -- SerpAPI Google Jobs search
Returns raw job listings for all query/employment-type combinations.
"""

import os
import time
import hashlib
from serpapi import GoogleSearch
from dotenv import load_dotenv

load_dotenv()

SERPAPI_KEY = os.environ["SERPAPI_KEY"]

QUERIES = [
    '"Product Manager" remote',
    '"Product Manager" "New York" hybrid',
    '"Senior Product Manager" remote OR hybrid "New York"',
    '"Data Product Manager" remote OR hybrid',
    '"AI Product Manager" remote OR hybrid',
    '"Technical Product Manager" remote',
    '"Product Manager" contract remote OR hybrid "New York"',
    '"Product Owner" remote',
    '"Product Owner" "New York" hybrid',
]

EMPLOYMENT_TYPES = ["FULLTIME", "CONTRACTOR"]


def _make_job_id(job):
    """Return job_id from SerpAPI result, or a stable hash fallback."""
    job_id = job.get("job_id")
    if job_id:
        return job_id
    raw = f"{job.get('title', '')}-{job.get('company_name', '')}-{job.get('location', '')}"
    return hashlib.md5(raw.encode()).hexdigest()


def _extract_source(job):
    """Extract source job board from SerpAPI via field. Returns e.g. 'LinkedIn', 'Indeed'."""
    via = job.get("via", "")
    if via.lower().startswith("via "):
        return via[4:].strip()
    return via.strip()


def search_single(query, employment_type, seed_run=False):
    """Run one SerpAPI Google Jobs query and return raw job list."""
    date_filter = "month" if seed_run else "3days"
    chips = f"employment_type:{employment_type},date_posted:{date_filter}"

    params = {
        "engine": "google_jobs",
        "q": query,
        "chips": chips,
        "hl": "en",
        "gl": "us",
        "api_key": SERPAPI_KEY,
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        jobs = results.get("jobs_results", [])
        for job in jobs:
            job["_job_id"] = _make_job_id(job)
            job["_employment_type_queried"] = employment_type
            job["_source"] = _extract_source(job)
        return jobs
    except Exception as e:
        print(f"[search_jobs] ERROR on query '{query}' ({employment_type}): {e}")
        return []


def search_all(seed_run=False):
    """Run all query x employment_type combinations, return deduplicated raw job list."""
    all_jobs = []
    seen_ids = set()
    seen_composite = set()  # (title.lower(), company.lower()) -- catches cross-query duplicates

    total = len(QUERIES) * len(EMPLOYMENT_TYPES)
    count = 0

    for query in QUERIES:
        for emp_type in EMPLOYMENT_TYPES:
            count += 1
            print(f"[search_jobs] ({count}/{total}) query='{query}' type={emp_type}")
            jobs = search_single(query, emp_type, seed_run=seed_run)
            for job in jobs:
                jid = job["_job_id"]
                composite = (
                    job.get("title", "").lower().strip(),
                    job.get("company_name", "").lower().strip(),
                )
                # Skip if already seen by ID or by (title, company) composite key
                if jid in seen_ids or composite in seen_composite:
                    continue
                seen_ids.add(jid)
                seen_composite.add(composite)
                all_jobs.append(job)
            time.sleep(1.5)

    print(f"[search_jobs] Total raw jobs collected (pre-filter): {len(all_jobs)}")
    return all_jobs


if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="Use month date filter instead of 3days")
    args = parser.parse_args()

    jobs = search_all(seed_run=args.seed)
    print(json.dumps(jobs[:3], indent=2))
    print(f"Total: {len(jobs)} jobs")
    # Show source distribution
    from collections import Counter
    sources = Counter(j.get("_source", "unknown") for j in jobs)
    print("Sources:", dict(sources.most_common()))
