#!/usr/bin/env python3
"""
MGCV Clone HR Dashboard — Resume Auto-Downloader
- Skips candidates already downloaded in previous runs
- Only downloads NEW candidates each time
- Tracks downloads in downloaded_resumes/download_history.json
"""

import asyncio
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, Page, BrowserContext

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BASE_URL      = "http://65.1.136.77"
ADMIN_URL     = f"{BASE_URL}/admin"
DOWNLOAD_DIR  = Path("./downloaded_resumes")
HISTORY_FILE  = DOWNLOAD_DIR / "download_history.json"
HEADLESS      = False
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("hr_scraper.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── HISTORY HELPERS ─────────────────────────────────────────────────────────

def load_history() -> dict:
    """Load download history from JSON file.
    Structure: { "Role Name": ["email1@x.com", "email2@x.com"] }
    """
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_history(history: dict):
    """Save download history to JSON file."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def already_downloaded(history: dict, role: str, email: str) -> bool:
    """Check if a candidate (identified by email) was already downloaded for this role."""
    key = role.strip().lower()
    downloaded_emails = [e.strip().lower() for e in history.get(key, [])]
    return email.strip().lower() in downloaded_emails


def mark_downloaded(history: dict, role: str, email: str):
    """Mark a candidate as downloaded in the history."""
    key = role.strip().lower()
    if key not in history:
        history[key] = []
    if email.strip().lower() not in [e.strip().lower() for e in history[key]]:
        history[key].append(email.strip())


# ─── UTILS ───────────────────────────────────────────────────────────────────

def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^\w\-]", "_", text.strip())
    return cleaned[:60]


async def close_modal(page: Page):
    for sel in [
        "button:has-text('Close')",
        "button[aria-label='Close']",
        "[data-dismiss='modal']",
        "button.close",
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.click()
                await page.wait_for_timeout(800)
                return
        except Exception:
            pass
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(800)


async def wait_for_modal_open(page: Page, timeout: int = 8000) -> bool:
    modal_selectors = [
        "dialog[open]",
        "[role='dialog']",
        ".modal.show",
        "[class*='modal'][class*='open']",
        "text=CANDIDATES FOR THIS ROLE",
    ]
    deadline = asyncio.get_event_loop().time() + timeout / 1000
    while asyncio.get_event_loop().time() < deadline:
        for sel in modal_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        await page.wait_for_timeout(200)
    return False


async def download_via_request(context: BrowserContext, href: str, save_path: Path) -> bool:
    try:
        url = href if href.startswith("http") else BASE_URL + href
        resp = await context.request.get(url)
        if resp.ok:
            save_path.write_bytes(await resp.body())
            return True
        log.warning(f"    Direct request returned HTTP {resp.status}")
    except Exception as e:
        log.warning(f"    Direct request failed: {e}")
    return False


async def get_candidate_info(btn) -> tuple:
    """Extract candidate name and email from the row containing the Download button."""
    skip_words = {
        "Preview", "Download", "↓ Download", "CANDIDATES FOR THIS ROLE",
        "Apply Now", "Close", "JOB DESCRIPTION", "Engineering", "Product",
        "Design", "Remote", "New York", "San Francisco", "Full-time",
        "Full time", "Contract", "Part-time",
    }
    try:
        for levels in range(2, 10):
            try:
                ancestor = btn.locator(f"xpath=ancestor::*[{levels}]")
                if not await ancestor.count():
                    continue
                raw = (await ancestor.inner_text()).strip()
                lines = [
                    l.strip() for l in raw.splitlines()
                    if l.strip() and l.strip() not in skip_words
                    and not any(l.strip().startswith(w) for w in skip_words)
                ]
                email_line = next((l for l in lines if "@" in l and "." in l), None)
                if email_line:
                    email_idx = lines.index(email_line)
                    name = lines[email_idx - 1] if email_idx > 0 else lines[0]
                    if len(name) > 1 and name not in skip_words:
                        return name.strip(), email_line.strip()
            except Exception:
                continue
    except Exception as e:
        log.debug(f"Could not extract candidate info: {e}")
    return None, None


# ─── ROLE LISTING (used by jobs.py) ─────────────────────────────────────────

async def _fetch_roles_from_dashboard() -> list:
    """
    Opens http://65.0.3.172/admin, reads the jobs table and returns
    a list of dicts:
      { "id": "1", "title": "Python Developer", "applications": 3 }
    """
    history = load_history()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)  # headless — just reading the table
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page    = await context.new_page()

        log.info(f"-> [get_roles] Opening {ADMIN_URL}")
        await page.goto(ADMIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.wait_for_selector("table tbody tr", timeout=10_000)

        rows = await page.locator("table tbody tr").all()
        roles = []
        for idx, row in enumerate(rows, start=1):
            tds = await row.locator("td").all()
            if not tds:
                continue
            title = (await tds[0].inner_text()).strip()
            if not title:
                continue

            # Count candidates already downloaded for this role
            role_key = title.strip().lower()
            app_count = len(history.get(role_key, []))

            roles.append({
                "id":           str(idx),
                "title":        title,
                "applications": app_count,
                "status":       "Active",
                "department":   "",
                "location":     "",
                "description":  f"Job description for {title}",
                "postingUrl":   "",
            })

        await browser.close()
        log.info(f"[get_roles] Found {len(roles)} role(s) on dashboard")
        return roles


def get_roles_from_dashboard() -> list:
    """
    Synchronous wrapper — call this from jobs.py.
    Returns list of role dicts scraped from http://65.0.3.172/admin.
    """
    try:
        return asyncio.run(_fetch_roles_from_dashboard())
    except Exception as e:
        log.error(f"get_roles_from_dashboard failed: {e}")
        return []


# ─── CORE SCRAPER ────────────────────────────────────────────────────────────

async def process_role(page: Page, context: BrowserContext, role: str,
                       role_idx: int, history: dict) -> list:
    """Open role modal, skip already-downloaded candidates, download new ones."""
    results = []
    log.info(f"\n== [{role_idx}] {role} ==")

    # Click row by index
    await page.wait_for_selector("table tbody tr", timeout=10_000)
    row = page.locator("table tbody tr").nth(role_idx - 1)
    if not await row.count():
        log.warning(f"  Row {role_idx} not found, skipping")
        return results

    await row.scroll_into_view_if_needed()
    await row.click()
    log.info(f"  Clicked row {role_idx} for '{role}'")

    # Wait for modal
    modal_opened = await wait_for_modal_open(page, timeout=8000)
    if not modal_opened:
        log.warning(f"  Modal did not open for '{role}'")
        await page.screenshot(path=f"debug_{safe_name(role)}_no_modal.png")
        return results

    await page.wait_for_timeout(2500)

    # Find Download buttons
    dl_buttons = []
    for sel in [
        "a:has-text('Download')",
        "button:has-text('Download')",
        "a[href*='download']",
        "a[href*='resume']",
        "a[href*='.pdf']",
        "[class*='download']",
    ]:
        found = await page.locator(sel).all()
        if found:
            dl_buttons = found
            log.info(f"  Found {len(found)} candidate(s) [selector: {sel}]")
            break

    if not dl_buttons:
        log.warning(f"  No download buttons for '{role}'")
        await page.screenshot(path=f"debug_{safe_name(role)}_modal.png", full_page=True)
        await close_modal(page)
        return results

    role_dir = DOWNLOAD_DIR / safe_name(role)
    role_dir.mkdir(parents=True, exist_ok=True)

    for idx, btn in enumerate(dl_buttons, start=1):
        candidate_name, email = await get_candidate_info(btn)

        if not candidate_name or candidate_name in ("Preview", "Download"):
            candidate_name = f"candidate_{idx}"
        if not email:
            email = f"unknown_{idx}"

        # ── SKIP CHECK ────────────────────────────────────────────────────
        if already_downloaded(history, role, email):
            log.info(f"  [{idx}] SKIPPED (already downloaded)  {candidate_name}  <{email}>")
            results.append(dict(
                role=role, candidate=candidate_name, email=email,
                file="", ok=True, skipped=True,
            ))
            continue
        # ─────────────────────────────────────────────────────────────────

        log.info(f"  [{idx}] NEW candidate — downloading  {candidate_name}  <{email}>")

        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = role_dir / f"{safe_name(candidate_name)}_{ts}.pdf"
        downloaded = False

        # Method 1: Playwright download event
        try:
            async with page.expect_download(timeout=12_000) as dl_info:
                await btn.click()
            dl = await dl_info.value
            suggested = dl.suggested_filename
            if suggested:
                ext = Path(suggested).suffix or ".pdf"
                save_path = role_dir / f"{safe_name(candidate_name)}_{ts}{ext}"
            await dl.save_as(save_path)
            size = save_path.stat().st_size
            log.info(f"    SUCCESS  {save_path.name}  ({size:,} bytes)")
            downloaded = True
        except Exception as e:
            log.warning(f"    Download-event failed: {e}")

        # Method 2: Direct HTTP fetch
        if not downloaded:
            try:
                href = await btn.get_attribute("href") or ""
                if href:
                    downloaded = await download_via_request(context, href, save_path)
                    if downloaded:
                        log.info(f"    SUCCESS  {save_path.name}  [direct fetch]")
            except Exception as e2:
                log.error(f"    Both methods failed: {e2}")

        if downloaded:
            # Record in history so we skip next time
            mark_downloaded(history, role, email)
            save_history(history)

        results.append(dict(
            role=role, candidate=candidate_name, email=email,
            file=str(save_path) if downloaded else "",
            ok=downloaded, skipped=False,
        ))

    await close_modal(page)
    await page.wait_for_timeout(1000)
    return results


async def scrape(target_role: str = None):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing download history
    history = load_history()
    log.info(f"Loaded history: {sum(len(v) for v in history.values())} previously downloaded candidate(s)")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        page = await context.new_page()

        log.info(f"-> Opening {ADMIN_URL}")
        await page.goto(ADMIN_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_load_state("networkidle", timeout=10_000)

        await page.wait_for_selector("table tbody tr", timeout=10_000)
        rows = await page.locator("table tbody tr").all()
        role_names = []
        for row in rows:
            tds = await row.locator("td").all()
            if tds:
                name = (await tds[0].inner_text()).strip()
                if name:
                    role_names.append(name)

        log.info(f"Found {len(role_names)} roles: {role_names}")

        if target_role:
            roles_to_process = [
                (i + 1, r) for i, r in enumerate(role_names)
                if target_role.lower() in r.lower()
            ]
            if not roles_to_process:
                print(f"\n  No role matching '{target_role}' found.")
                print(f"  Available roles: {role_names}")
                await browser.close()
                return [], 0, 0, 0
        else:
            roles_to_process = [(i + 1, r) for i, r in enumerate(role_names)]

        all_results = []
        for role_idx, role in roles_to_process:
            results = await process_role(page, context, role, role_idx, history)
            all_results.extend(results)

        await browser.close()

        new_dl   = sum(1 for r in all_results if r["ok"] and not r.get("skipped"))
        skipped  = sum(1 for r in all_results if r.get("skipped"))
        failed   = sum(1 for r in all_results if not r["ok"] and not r.get("skipped"))

        print("\n" + "=" * 55)
        print("FINAL SUMMARY")
        print("=" * 55)
        print(f"  NEW downloads  : {new_dl}")
        print(f"  Skipped        : {skipped}  (already downloaded before)")
        print(f"  Failed         : {failed}")
        print(f"  Saved to       : {DOWNLOAD_DIR.resolve()}")
        print("")
        for item in all_results:
            if item.get("skipped"):
                print(f"  [SKIP]  [{item['role']}]  {item['candidate']}  ({item['email']})")
            elif item["ok"]:
                print(f"  [NEW ]  [{item['role']}]  {item['candidate']}  ({item['email']})")
                print(f"          -> {item['file']}")
            else:
                print(f"  [FAIL]  [{item['role']}]  {item['candidate']}  ({item['email']})")

        return all_results, new_dl, skipped, failed


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  MGCV Clone HR Dashboard - Resume Auto-Downloader")
    print("=" * 55)
    print(f"  Target  : {ADMIN_URL}")
    print(f"  Output  : {DOWNLOAD_DIR.resolve()}")
    print("=" * 55)

    print("\nOptions:")
    print("  1. Download ALL job roles")
    print("  2. Download a specific job role")
    choice = input("\nEnter choice (1 or 2): ").strip()

    target = None
    if choice == "2":
        target = input("Enter job title (e.g. 'Product Manager'): ").strip()
        print(f"\n  Downloading resumes for: {target}")
    else:
        print("\n  Downloading resumes for ALL roles")

    results, new_dl, skipped, failed = asyncio.run(scrape(target_role=target))

    print(f"\nDone — {new_dl} new, {skipped} skipped, {failed} failed.")
    print(f"Files: {DOWNLOAD_DIR.resolve()}")