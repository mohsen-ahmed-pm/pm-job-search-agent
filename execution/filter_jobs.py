"""
filter_jobs.py -- Post-call filtering for PM job search.
Applies title allowlist/blocklist, company blocklist, and location rules.
"""

# ---------------------------------------------------------------------------
# Title rules -- simple substring matching (case-insensitive)
# ---------------------------------------------------------------------------

TITLE_KEEP_SUBSTRINGS = [
    "product manager",
    "product owner",
]

TITLE_DISCARD_SUBSTRINGS = [
    "director",
    "vice president",
    "chief ",
    " vp ",
    "vp of",
    "vp,",
    "internship",
    " intern",
    "coordinator",
    "associate product manager",
]

# ---------------------------------------------------------------------------
# Company blocklist -- exact company name matches (case-insensitive)
# Add companies here to exclude them from results permanently.
# ---------------------------------------------------------------------------

COMPANY_BLOCKLIST = [
    "aidoos",
]

# ---------------------------------------------------------------------------
# Location rules -- NYC/NJ Transit commuter zone
# ---------------------------------------------------------------------------

NYC_NJ_ZONE_TERMS = [
    # NYC boroughs
    "new york", "new york city", "nyc", "manhattan", "brooklyn",
    "queens", "bronx", "staten island",
    # NJ Transit corridor
    "jersey city", "hoboken", "newark", "harrison", "secaucus",
    "weehawken", "bayonne", "elizabeth", "kearny", "linden",
    "rahway", "woodbridge", "perth amboy", "new brunswick", "trenton",
    "new jersey", " nj", ", nj",
    # Westchester (Metro-North)
    "westchester", "white plains", "yonkers", "mount vernon",
    # Long Island (LIRR)
    "long island", "nassau", "suffolk",
    # Generic NY state catch-all
    ", ny", " ny,", "new york, ny",
]


def _title_passes(title):
    """Return True if title should be kept."""
    t = title.lower()
    if not any(k in t for k in TITLE_KEEP_SUBSTRINGS):
        return False
    if any(d in t for d in TITLE_DISCARD_SUBSTRINGS):
        return False
    return True


def _company_blocked(company_name):
    """Return True if company is on the blocklist."""
    return company_name.lower().strip() in COMPANY_BLOCKLIST


# Location strings that are generic (not a real city) -- do not trigger Verify flag
GENERIC_LOCATIONS = {
    "", "remote", "anywhere", "united states", "us", "usa",
    "united states of america", "nationwide", "work from home",
}


def _has_specific_nonzone_city(location):
    """Return True if location contains a real city that is NOT in the NYC/NJ zone."""
    loc = location.lower().strip()
    # Strip common remote qualifiers to get the city part
    for qualifier in ["(remote)", "- remote", "remote -", "remote/"]:
        loc = loc.replace(qualifier, "").strip()
    # If what's left is generic, no specific city
    if loc in GENERIC_LOCATIONS or not loc:
        return False
    # If it IS in the NYC/NJ zone, no flag needed
    if any(term in loc for term in NYC_NJ_ZONE_TERMS):
        return False
    # Has content that's not generic and not in zone = specific non-zone city
    return True


def _derive_location_type(job):
    """Derive Remote, Hybrid, Remote (Verify), or OnSite from job data."""
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    description = (job.get("description") or "").lower()[:500]

    has_remote_signal = False
    remote_signals = ["remote", "work from home", "wfh", "fully remote"]
    for sig in remote_signals:
        if sig in location or sig in title:
            has_remote_signal = True
            break

    extensions = job.get("detected_extensions") or {}
    if extensions.get("work_from_home"):
        has_remote_signal = True

    if has_remote_signal:
        # Flag if a specific non-zone city is also present in the location field
        if _has_specific_nonzone_city(location):
            return "Remote (Verify)"
        return "Remote"

    if "hybrid" in location or "hybrid" in title or "hybrid" in description:
        return "Hybrid"

    if location and location.strip() not in GENERIC_LOCATIONS:
        return "OnSite"

    return "Remote"


def _hybrid_in_zone(location):
    """Return True if a Hybrid job location is within NYC/NJ Transit zone."""
    loc = location.lower()
    return any(term in loc for term in NYC_NJ_ZONE_TERMS)


def filter_jobs(raw_jobs):
    """Apply title, company, and location filters. Return qualifying jobs with derived fields."""
    kept = []
    stats = {
        "total": len(raw_jobs),
        "title_dropped": 0,
        "company_blocked": 0,
        "location_dropped": 0,
        "kept": 0,
    }

    for job in raw_jobs:
        title = job.get("title", "")
        company = job.get("company_name", "")
        location = job.get("location", "")

        # Title filter
        if not _title_passes(title):
            stats["title_dropped"] += 1
            continue

        # Company blocklist
        if _company_blocked(company):
            stats["company_blocked"] += 1
            continue

        # Derive location type
        loc_type = _derive_location_type(job)

        # Location filter
        if loc_type == "OnSite":
            stats["location_dropped"] += 1
            continue
        if loc_type == "Hybrid" and not _hybrid_in_zone(location):
            stats["location_dropped"] += 1
            continue

        job["_location_type"] = loc_type
        kept.append(job)
        stats["kept"] += 1

    print(f"[filter_jobs] Stats: {stats}")
    return kept


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_jobs = [
        {"title": "Senior Product Manager", "location": "Remote", "description": "", "detected_extensions": {}, "company_name": "Acme"},
        {"title": "Product Owner", "location": "Jersey City, NJ", "description": "hybrid role", "detected_extensions": {}, "company_name": "TechCo"},
        {"title": "Product Manager", "location": "Denver, CO", "description": "hybrid", "detected_extensions": {}, "company_name": "StartupX"},
        {"title": "Director of Product", "location": "Remote", "description": "", "detected_extensions": {}, "company_name": "Corp"},
        {"title": "VP of Product", "location": "Remote", "description": "", "detected_extensions": {}, "company_name": "Corp"},
        {"title": "AI Product Manager", "location": "New York, NY", "description": "hybrid", "detected_extensions": {}, "company_name": "BigTech"},
        {"title": "Product Manager Intern", "location": "Remote", "description": "", "detected_extensions": {}, "company_name": "Corp"},
        {"title": "Lead Product Owner", "location": "Manhattan, NY", "description": "hybrid position", "detected_extensions": {}, "company_name": "FinServ"},
        {"title": "Senior Product Manager", "location": "Remote", "description": "", "detected_extensions": {}, "company_name": "AiDOOS"},
    ]

    results = filter_jobs(test_jobs)
    print(f"Kept {len(results)} jobs:")
    for j in results:
        print(f"  {j['title']} | {j['company_name']} | {j['location']} | {j['_location_type']}")
    print("AiDOOS should NOT appear above.")
