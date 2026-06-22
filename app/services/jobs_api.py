# """
# app/services/jobs_api.py
# ────────────────────────
# Scrapes the HR admin dashboard at http://65.1.136.77/admin to return a list
# of active job roles.

# Expected return shape (consumed by app/routes/jobs.py → get_cached_jobs):
#     [
#         {
#             "id":           "42",
#             "title":        "Python Developer",
#             "department":   "Engineering",
#             "location":     "Remote",
#             "applications": 7,
#             "status":       "Active",
#             "description":  "...",
#             "postingUrl":   "http://65.1.136.77/jobs/42",
#         },
#         ...
#     ]
# """

# import logging
# import re
# import uuid

# import requests
# from bs4 import BeautifulSoup

# logger = logging.getLogger(__name__)

# # ── Config ────────────────────────────────────────────────────────────────────
# DASHBOARD_BASE   = "http://65.1.136.77"
# DASHBOARD_ADMIN  = f"{DASHBOARD_BASE}/admin"
# REQUEST_TIMEOUT  = 15          # seconds
# SESSION_HEADERS  = {
#     "User-Agent": "TalentFlow/1.0 (internal HR integration)",
#     "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
# }

# # ── Helpers ───────────────────────────────────────────────────────────────────

# def _make_session() -> requests.Session:
#     """Return a requests Session with shared headers."""
#     s = requests.Session()
#     s.headers.update(SESSION_HEADERS)
#     return s


# def _safe_int(text: str, default: int = 0) -> int:
#     """Extract the first integer found in *text*, or return *default*."""
#     if not text:
#         return default
#     match = re.search(r"\d+", text.replace(",", ""))
#     return int(match.group()) if match else default


# def _normalize_role(raw: dict) -> dict:
#     """Ensure every key the caller expects is present."""
#     role_id    = str(raw.get("id") or uuid.uuid4())
#     title      = (raw.get("title") or "").strip()
#     department = (raw.get("department") or "").strip()
#     location   = (raw.get("location") or "").strip()
#     apps       = _safe_int(str(raw.get("applications", 0)))
#     status     = (raw.get("status") or "Active").strip()
#     description = (raw.get("description") or f"Job description for {title}").strip()
#     posting_url = raw.get("postingUrl") or f"{DASHBOARD_BASE}/jobs/{role_id}"

#     return {
#         "id":           role_id,
#         "title":        title,
#         "department":   department,
#         "location":     location,
#         "applications": apps,
#         "status":       status,
#         "description":  description,
#         "postingUrl":   posting_url,
#     }

# # ── Core scraper ──────────────────────────────────────────────────────────────

# def _scrape_dashboard(session: requests.Session) -> list[dict]:
#     """
#     Fetch the admin page and parse job/role rows out of it.

#     The function tries several common table/card layouts in order:
#       1. <table> rows where a cell contains a job title
#       2. Generic card/list-item elements with a heading
#       3. Any <a> or <div> whose text looks like a job posting

#     Returns a list of raw dicts; normalisation happens in get_roles_from_dashboard.
#     """
#     try:
#         resp = session.get(DASHBOARD_ADMIN, timeout=REQUEST_TIMEOUT)
#         resp.raise_for_status()
#     except requests.RequestException as exc:
#         logger.error("Failed to reach HR dashboard at %s: %s", DASHBOARD_ADMIN, exc)
#         return []

#     soup = BeautifulSoup(resp.text, "html.parser")
#     roles: list[dict] = []

#     # ── Strategy 1: HTML <table> ──────────────────────────────────────────────
#     tables = soup.find_all("table")
#     for table in tables:
#         headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

#         # Locate column indices by common header names
#         col = {
#             "title":       _col_index(headers, ["job title", "title", "role", "position", "job"]),
#             "department":  _col_index(headers, ["department", "dept", "team"]),
#             "location":    _col_index(headers, ["location", "loc", "city", "place"]),
#             "applications":_col_index(headers, ["applications", "applicants", "applied", "count", "apps"]),
#             "status":      _col_index(headers, ["status", "state"]),
#             "id":          _col_index(headers, ["id", "job id", "role id"]),
#         }

#         for tr in table.find_all("tr")[1:]:          # skip header row
#             cells = tr.find_all(["td", "th"])
#             if not cells:
#                 continue

#             title = _cell_text(cells, col["title"])
#             if not title:
#                 # Try first non-empty cell as title fallback
#                 title = next((c.get_text(strip=True) for c in cells if c.get_text(strip=True)), "")

#             if not title:
#                 continue

#             # Try to grab a row-level link for posting URL
#             link_tag = tr.find("a", href=True)
#             posting_url = (
#                 link_tag["href"] if link_tag and link_tag["href"].startswith("http")
#                 else (f"{DASHBOARD_BASE}{link_tag['href']}" if link_tag else "")
#             )

#             roles.append({
#                 "id":           _cell_text(cells, col["id"]),
#                 "title":        title,
#                 "department":   _cell_text(cells, col["department"]),
#                 "location":     _cell_text(cells, col["location"]),
#                 "applications": _cell_text(cells, col["applications"]),
#                 "status":       _cell_text(cells, col["status"]) or "Active",
#                 "postingUrl":   posting_url,
#             })

#         if roles:
#             logger.info("Parsed %d role(s) from table layout", len(roles))
#             return roles

#     # ── Strategy 2: Card / list-item layout ───────────────────────────────────
#     cards = (
#         soup.find_all(class_=re.compile(r"(job|role|card|posting|item)", re.I))
#         or soup.find_all("li")
#     )
#     for card in cards:
#         heading = (
#             card.find(["h1", "h2", "h3", "h4", "h5", "strong", "b"])
#             or card.find(class_=re.compile(r"(title|name|heading)", re.I))
#         )
#         title = heading.get_text(strip=True) if heading else card.get_text(strip=True)[:80]
#         if not title or len(title) < 3:
#             continue

#         link_tag = card.find("a", href=True)
#         posting_url = (
#             link_tag["href"] if link_tag and link_tag["href"].startswith("http")
#             else (f"{DASHBOARD_BASE}{link_tag['href']}" if link_tag else "")
#         )

#         # Try to find an applications/count badge inside the card
#         badge = card.find(class_=re.compile(r"(count|badge|num|app)", re.I))
#         apps_text = badge.get_text(strip=True) if badge else "0"

#         roles.append({
#             "id":           "",
#             "title":        title,
#             "department":   "",
#             "location":     "",
#             "applications": apps_text,
#             "status":       "Active",
#             "postingUrl":   posting_url,
#         })

#     if roles:
#         logger.info("Parsed %d role(s) from card/list layout", len(roles))
#         return roles

#     # ── Strategy 3: Raw link scan ─────────────────────────────────────────────
#     job_keywords = re.compile(
#         r"(developer|engineer|designer|analyst|manager|lead|intern|"
#         r"specialist|consultant|architect|devops|qa|tester|scientist)",
#         re.I
#     )
#     for tag in soup.find_all(["a", "div", "span", "p"]):
#         text = tag.get_text(strip=True)
#         if job_keywords.search(text) and 5 < len(text) < 120:
#             link_tag = tag if tag.name == "a" else tag.find("a", href=True)
#             posting_url = ""
#             if link_tag and link_tag.get("href"):
#                 href = link_tag["href"]
#                 posting_url = href if href.startswith("http") else f"{DASHBOARD_BASE}{href}"

#             roles.append({
#                 "id":           "",
#                 "title":        text,
#                 "department":   "",
#                 "location":     "",
#                 "applications": 0,
#                 "status":       "Active",
#                 "postingUrl":   posting_url,
#             })

#     # Deduplicate by title
#     seen: set[str] = set()
#     unique: list[dict] = []
#     for r in roles:
#         key = r["title"].lower()
#         if key not in seen:
#             seen.add(key)
#             unique.append(r)

#     if unique:
#         logger.info("Parsed %d role(s) via link-scan fallback", len(unique))
#     else:
#         logger.warning("No roles found at %s — page structure may have changed", DASHBOARD_ADMIN)

#     return unique


# # ── Column-index helpers ──────────────────────────────────────────────────────

# def _col_index(headers: list[str], candidates: list[str]) -> int | None:
#     """Return the first header index whose text matches one of *candidates*."""
#     for i, h in enumerate(headers):
#         if any(c in h for c in candidates):
#             return i
#     return None


# def _cell_text(cells: list, index: int | None) -> str:
#     """Safely return stripped text from *cells[index]*, or empty string."""
#     if index is None or index >= len(cells):
#         return ""
#     return cells[index].get_text(strip=True)


# # ── Public API ────────────────────────────────────────────────────────────────

# def get_roles_from_dashboard() -> list[dict]:
#     """
#     Scrape the HR admin dashboard and return a normalised list of job role dicts.

#     Returns an empty list (never raises) so callers can safely fall back to the
#     database without extra try/except wrapping.
#     """
#     try:
#         session = _make_session()
#         raw_roles = _scrape_dashboard(session)
#         normalised = [_normalize_role(r) for r in raw_roles]
#         # Drop rows with no usable title
#         valid = [r for r in normalised if r["title"]]
#         logger.info("get_roles_from_dashboard → %d valid role(s)", len(valid))
#         return valid
#     except Exception as exc:
#         logger.exception("Unexpected error in get_roles_from_dashboard: %s", exc)
#         return []
"""
app/services/jobs_api.py
────────────────────────
Fetches active job roles from the HR portal (http://13.233.81.136.nip.io).

The portal is a React SPA, so plain HTML scraping returns an empty shell.
This module therefore uses a layered approach:

  Layer 1 — JSON REST API  (fastest, most reliable)
            Tries common API endpoints that React frontends typically call.
  Layer 2 — Embedded JSON  (Next.js / SSR hydration data in <script> tags)
            Parses __NEXT_DATA__ or similar JSON blobs baked into the HTML.
  Layer 3 — Admin page scrape  (http://65.1.136.77/admin, server-rendered)
            Falls back to HTML scraping of the admin backend if accessible.

Return shape (matches what app/routes/jobs.py → get_cached_jobs expects):
    [
        {
            "id":           "1",
            "title":        "python developer",
            "department":   "frotend",
            "location":     "hyderabad",
            "applications": 0,
            "status":       "Active",
            "description":  "Job description for python developer",
            "postingUrl":   "https://3.109.201.45.nip.io/",
        },
        ...
    ]
"""

import json
import logging
import re
import uuid

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
# Public-facing React frontend (careers page visible in screenshot)
CAREERS_BASE = "https://hrmgcvclone-production.up.railway.app"

# Internal admin backend (original scraping target)
ADMIN_BASE = "https://hrmgcvclone-production.up.railway.app"

REQUEST_TIMEOUT = 15  # seconds per request

_JSON_HEADERS = {
    "User-Agent": "TalentFlow/1.0 (internal HR integration)",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}
_HTML_HEADERS = {
    "User-Agent": "TalentFlow/1.0 (internal HR integration)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# JSON API endpoint candidates — tried in order
_API_CANDIDATES = [
    f"{CAREERS_BASE}/api/jobs",
    f"{CAREERS_BASE}/api/roles",
    f"{CAREERS_BASE}/api/job-listings",
    f"{CAREERS_BASE}/api/positions",
    f"{CAREERS_BASE}/api/careers",
    f"{ADMIN_BASE}/api/jobs",
    f"{ADMIN_BASE}/api/roles",
    f"{ADMIN_BASE}/api/positions",
    f"{ADMIN_BASE}/admin/api/jobs",
    f"{ADMIN_BASE}/admin/roles",
]

# HTML pages to try for embedded JSON / server-rendered content
_HTML_CANDIDATES = [
    f"{CAREERS_BASE}/careers",
    f"{CAREERS_BASE}/jobs",
    f"{CAREERS_BASE}/",
    f"{ADMIN_BASE}/admin",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _session(json_mode: bool = True) -> requests.Session:
    s = requests.Session()
    s.headers.update(_JSON_HEADERS if json_mode else _HTML_HEADERS)
    return s


def _safe_int(value, default: int = 0) -> int:
    try:
        text = str(value).replace(",", "")
        m = re.search(r"\d+", text)
        return int(m.group()) if m else default
    except Exception:
        return default


def _normalize(raw: dict) -> dict:
    """Fill in all keys the caller expects, with safe defaults."""
    role_id = str(
        raw.get("id") or raw.get("job_id") or raw.get("_id") or uuid.uuid4()
    )
    title = str(
        raw.get("title") or raw.get("name") or raw.get("role") or
        raw.get("position") or ""
    ).strip()
    department = str(
        raw.get("department") or raw.get("dept") or raw.get("team") or
        raw.get("category") or ""
    ).strip()
    location = str(
        raw.get("location") or raw.get("city") or raw.get("place") or ""
    ).strip()
    apps = _safe_int(
        raw.get("applications") or raw.get("applicants") or raw.get("applied") or 0
    )
    status = str(raw.get("status") or raw.get("state") or "Active").strip() or "Active"
    desc = str(
        raw.get("description") or raw.get("summary") or raw.get("details") or
        f"Job description for {title}"
    ).strip()
    url = str(
        raw.get("postingUrl") or raw.get("url") or raw.get("link") or
        raw.get("posting_url") or f"{CAREERS_BASE}/jobs/{role_id}"
    ).strip()
    return {
        "id":           role_id,
        "title":        title,
        "department":   department,
        "location":     location,
        "applications": apps,
        "status":       status,
        "description":  desc,
        "postingUrl":   url,
    }


# ── Layer 1: JSON REST API ─────────────────────────────────────────────────────

def _try_json_api() -> list[dict]:
    """
    Hit common REST endpoints and try to interpret the response as a list of jobs.
    """
    session = _session(json_mode=True)
    for url in _API_CANDIDATES:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            ct = resp.headers.get("Content-Type", "")
            if "json" not in ct and not resp.text.lstrip().startswith(("[", "{")):
                continue

            data = resp.json()

            if isinstance(data, list):
                candidates = data
            elif isinstance(data, dict):
                candidates = (
                    data.get("jobs") or data.get("roles") or data.get("data") or
                    data.get("positions") or data.get("results") or
                    data.get("items") or []
                )
            else:
                continue

            if not isinstance(candidates, list) or not candidates:
                continue

            roles = []
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                normalised = _normalize(item)
                if normalised["title"]:
                    roles.append(normalised)

            if roles:
                logger.info("Layer 1 (JSON API) → %d role(s) from %s", len(roles), url)
                return roles

        except Exception as exc:
            logger.debug("JSON API attempt failed for %s: %s", url, exc)

    logger.debug("Layer 1 (JSON API) → no results from any endpoint")
    return []


# ── Layer 2: Embedded JSON in HTML (Next.js / SSR) ────────────────────────────

def _try_embedded_json() -> list[dict]:
    """
    Fetch the React/Next.js HTML and look for job data embedded in:
      - window.__NEXT_DATA__  (Next.js hydration blob)
      - <script type="application/json"> blocks
      - Inline JS variables that look like a jobs array
    """
    session = _session(json_mode=False)
    for url in _HTML_CANDIDATES:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # 2a. Next.js __NEXT_DATA__
            next_tag = soup.find("script", id="__NEXT_DATA__")
            if next_tag and next_tag.string:
                try:
                    roles = _extract_from_json_tree(json.loads(next_tag.string))
                    if roles:
                        logger.info(
                            "Layer 2a (__NEXT_DATA__) → %d role(s) from %s",
                            len(roles), url
                        )
                        return roles
                except Exception:
                    pass

            # 2b. <script type="application/json">
            for tag in soup.find_all("script", {"type": "application/json"}):
                try:
                    roles = _extract_from_json_tree(json.loads(tag.string or ""))
                    if roles:
                        logger.info(
                            "Layer 2b (script JSON) → %d role(s) from %s",
                            len(roles), url
                        )
                        return roles
                except Exception:
                    pass

            # 2c. Inline JS variable scan
            for tag in soup.find_all("script"):
                script = tag.string or ""
                for pattern in [
                    r'"jobs"\s*:\s*(\[.*?\])',
                    r'"roles"\s*:\s*(\[.*?\])',
                    r'"positions"\s*:\s*(\[.*?\])',
                    r'"data"\s*:\s*(\[.*?\])',
                    r'(?:var|let|const)\s+\w*[Jj]obs\w*\s*=\s*(\[.*?\])\s*[;,]',
                ]:
                    for match in re.findall(pattern, script, re.DOTALL):
                        try:
                            roles = _extract_from_json_tree(json.loads(match))
                            if roles:
                                logger.info(
                                    "Layer 2c (inline JS) → %d role(s) from %s",
                                    len(roles), url
                                )
                                return roles
                        except Exception:
                            pass

        except Exception as exc:
            logger.debug("Embedded JSON attempt failed for %s: %s", url, exc)

    logger.debug("Layer 2 (embedded JSON) → no results")
    return []


def _extract_from_json_tree(data) -> list[dict]:
    """
    Recursively walk a JSON blob looking for a list of job-like dicts.
    """
    JOB_KEYS = {"title", "role", "position", "name", "job_title"}

    if isinstance(data, list) and data and all(isinstance(i, dict) for i in data):
        if any(k in data[0] for k in JOB_KEYS):
            roles = [_normalize(item) for item in data]
            roles = [r for r in roles if r["title"]]
            if roles:
                return roles
        for item in data:
            result = _extract_from_json_tree(item)
            if result:
                return result

    elif isinstance(data, dict):
        for key in ["jobs", "roles", "positions", "data", "items", "results",
                    "listings", "careers", "openings"]:
            if key in data and isinstance(data[key], list):
                result = _extract_from_json_tree(data[key])
                if result:
                    return result
        for val in data.values():
            if isinstance(val, (dict, list)):
                result = _extract_from_json_tree(val)
                if result:
                    return result

    return []


# ── Layer 3: Plain HTML scraping ──────────────────────────────────────────────

def _try_html_scrape() -> list[dict]:
    """
    Last resort: scrape server-rendered HTML. Handles table rows and
    the card layout visible in the screenshot.
    """
    session = _session(json_mode=False)
    for url in _HTML_CANDIDATES:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            roles = _parse_table(soup) or _parse_cards(soup)
            if roles:
                logger.info("Layer 3 (HTML scrape) → %d role(s) from %s", len(roles), url)
                return roles
        except Exception as exc:
            logger.debug("HTML scrape failed for %s: %s", url, exc)

    logger.debug("Layer 3 (HTML scrape) → no results")
    return []


def _parse_table(soup: BeautifulSoup) -> list[dict]:
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        col = {
            "id":          _col_idx(headers, ["id", "job id"]),
            "title":       _col_idx(headers, ["job title", "title", "role", "position", "job"]),
            "department":  _col_idx(headers, ["department", "dept", "team"]),
            "location":    _col_idx(headers, ["location", "city"]),
            "applications":_col_idx(headers, ["applications", "applicants", "applied", "apps"]),
            "status":      _col_idx(headers, ["status", "state"]),
        }
        roles = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            title = _cell(cells, col["title"]) or cells[0].get_text(strip=True)
            if not title:
                continue
            link = tr.find("a", href=True)
            href = link["href"] if link else ""
            posting_url = (
                href if href.startswith("http")
                else (f"{CAREERS_BASE}{href}" if href else "")
            )
            roles.append(_normalize({
                "id":           _cell(cells, col["id"]),
                "title":        title,
                "department":   _cell(cells, col["department"]),
                "location":     _cell(cells, col["location"]),
                "applications": _cell(cells, col["applications"]),
                "status":       _cell(cells, col["status"]) or "Active",
                "postingUrl":   posting_url,
            }))
        if roles:
            return roles
    return []


def _parse_cards(soup: BeautifulSoup) -> list[dict]:
    """
    Parse the card grid layout from the screenshot:
      each card → title heading, department text, location (pin icon), badge.
    """
    roles = []
    card_groups = [
        soup.find_all("div",     class_=re.compile(r"(job|role|card|posting|position|listing)", re.I)),
        soup.find_all("article", class_=re.compile(r"(job|role|card|posting)", re.I)),
        soup.find_all("li",      class_=re.compile(r"(job|role|card|posting)", re.I)),
        soup.find_all("a",       class_=re.compile(r"(job|role|card|posting)", re.I)),
    ]
    cards = next((c for c in card_groups if c), [])

    for card in cards:
        heading = (
            card.find(["h1", "h2", "h3", "h4", "h5"])
            or card.find("strong")
            or card.find(class_=re.compile(r"(title|name|heading|role)", re.I))
        )
        title = heading.get_text(strip=True) if heading else ""
        if not title or len(title) < 2:
            continue

        dept_el = card.find(class_=re.compile(r"(department|dept|team|category)", re.I))
        dept = dept_el.get_text(strip=True) if dept_el else ""

        loc_el = card.find(class_=re.compile(r"(location|city|place|loc)", re.I))
        location = loc_el.get_text(strip=True) if loc_el else ""

        badge_el = card.find(class_=re.compile(r"(badge|tag|type|contract|full|part)", re.I))
        emp_type = badge_el.get_text(strip=True) if badge_el else "Full-time"

        link = card.find("a", href=True) or (card if card.name == "a" else None)
        href = link.get("href", "") if link else ""
        posting_url = (
            href if href.startswith("http")
            else (f"{CAREERS_BASE}{href}" if href else "")
        )

        roles.append(_normalize({
            "title":      title,
            "department": dept,
            "location":   location,
            "status":     emp_type if emp_type in ("Full-time", "Part-time", "Contract") else "Active",
            "postingUrl": posting_url,
        }))

    seen: set[str] = set()
    unique = []
    for r in roles:
        key = r["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _col_idx(headers: list[str], candidates: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if any(c in h for c in candidates):
            return i
    return None


def _cell(cells: list, idx: int | None) -> str:
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx].get_text(strip=True)


# ── Public API ─────────────────────────────────────────────────────────────────

def get_roles_from_dashboard() -> list[dict]:
    """
    Return a list of active job roles from the HR portal.

    Tries three layers in order:
      1. JSON REST API endpoints  — works if React app exposes /api/jobs
      2. Embedded JSON in HTML   — works for Next.js / SSR apps
      3. Plain HTML scraping     — works for server-rendered admin pages

    Always returns a list (never raises), so the caller falls back to the
    database automatically when all layers return [].
    """
    try:
        roles = _try_json_api()
        if roles:
            return roles

        roles = _try_embedded_json()
        if roles:
            return roles

        roles = _try_html_scrape()
        if roles:
            return roles

        logger.warning(
            "get_roles_from_dashboard → all 3 layers returned nothing. "
            "The site likely serves jobs via a private/authenticated API. "
            "Open browser DevTools → Network tab on the careers page, "
            "find the XHR/fetch call that loads job cards, and add that "
            "endpoint + any auth headers to _API_CANDIDATES / _JSON_HEADERS."
        )
        return []

    except Exception as exc:
        logger.exception("Unexpected error in get_roles_from_dashboard: %s", exc)
        return []