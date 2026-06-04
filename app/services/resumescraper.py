"""
MGCV Clone HR Dashboard — Resume Auto-Downloader (Fixed v3)
Key fix: Added S0 — direct fetch of BASE_URL+href using browser session cookies.
The /uploads/ path IS served by the backend, but requires session auth via cookies,
not a Bearer token. context.request.get() carries those cookies automatically.
"""

import asyncio
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, Page, BrowserContext, Request, Response

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BASE_URL      = "http://localhost:3000"
ADMIN_URL     = f"{BASE_URL}/admin"
LOGIN_URL     = f"{BASE_URL}/login"
DOWNLOAD_DIR  = Path("./downloaded_resumes")
HISTORY_FILE  = DOWNLOAD_DIR / "download_history.json"
HEADLESS      = False

LOGIN_EMAIL    = "ankanisairam07100@gmail.com"
LOGIN_PASSWORD = "934791"
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler("hr_scraper.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── HISTORY HELPERS ─────────────────────────────────────────────────────────

def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_history(history: dict):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def already_downloaded(history: dict, role: str, unique_key: str) -> bool:
    key = role.strip().lower()
    return unique_key.strip().lower() in [e.strip().lower() for e in history.get(key, [])]


def mark_downloaded(history: dict, role: str, unique_key: str):
    key = role.strip().lower()
    if key not in history:
        history[key] = []
    if unique_key.strip().lower() not in [e.strip().lower() for e in history[key]]:
        history[key].append(unique_key.strip())


# ─── UTILS ───────────────────────────────────────────────────────────────────

def safe_name(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text.strip())[:60]


def ext_from_content_type(ct: str, fallback_url: str = "") -> str:
    ct = ct.lower()
    if "pdf" in ct:
        return ".pdf"
    if "wordprocessingml" in ct or "docx" in ct:
        return ".docx"
    if "msword" in ct:
        return ".doc"
    for ext in [".pdf", ".docx", ".doc"]:
        if fallback_url.lower().endswith(ext):
            return ext
    return ".pdf"


def is_real_file(body: bytes, ct: str) -> bool:
    """Return True if the response looks like an actual file, not an HTML error page."""
    if len(body) < 500:
        return False
    if b"<!doctype" in body[:200].lower() or b"<html" in body[:200].lower():
        return False
    if "html" in ct.lower():
        return False
    return True


async def close_modal(page: Page):
    for sel in ["button:has-text('Close')", "button[aria-label='Close']", "[data-dismiss='modal']"]:
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


async def wait_for_modal_open(page: Page, timeout: int = 12000) -> bool:
    modal_selectors = [
        "[role='dialog']", "dialog[open]", "[aria-modal='true']",
        "[class*='backdrop']", "[class*='overlay']",
        "div[class*='fixed'][class*='inset']", "div[class*='fixed'][class*='z-']",
        "text=CANDIDATES", "text=Add Candidate",
    ]
    deadline = asyncio.get_event_loop().time() + timeout / 1000
    while asyncio.get_event_loop().time() < deadline:
        for sel in modal_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    log.info(f"  Modal detected via: {sel}")
                    return True
            except Exception:
                pass
        await page.wait_for_timeout(250)
    return False


# ─── DISCOVER REAL DOWNLOAD URL ───────────────────────────────────────────────

async def discover_real_download_url(page: Page, btn) -> str:
    captured_request_urls: list[str] = []
    captured_binary_urls: list[str] = []

    async def on_request(req: Request):
        url = req.url
        if any(kw in url.lower() for kw in ["/upload", "/resume", "/download", "/file", "/media", "/asset", "/blob"]):
            if not any(kw in url for kw in [".js", ".css", ".woff", ".png", ".ico", "sockjs", "hot-update"]):
                captured_request_urls.append(url)
                log.info(f"  [intercept-req] {url}")

    async def on_response(resp: Response):
        ct = resp.headers.get("content-type", "")
        if any(kw in ct for kw in ["pdf", "octet-stream", "msword", "wordprocessing"]):
            captured_binary_urls.append(resp.url)
            log.info(f"  [intercept-bin] {resp.url}  ct={ct}")

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        await btn.click()
        await page.wait_for_timeout(3000)
    except Exception as e:
        log.warning(f"  [intercept] click error: {e}")
    finally:
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)

    if captured_binary_urls:
        return captured_binary_urls[0]
    if captured_request_urls:
        return captured_request_urls[0]
    return ""


# ─── PROBE KNOWN API PATTERNS ────────────────────────────────────────────────

async def probe_api_endpoints(context: BrowserContext, resume_name: str, auth_token: str = None) -> tuple:
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}

    candidates = []
    for ext in [".pdf", ".docx", ""]:
        n = resume_name + ext
        candidates += [
            f"{BASE_URL}/api/resumes/{n}",
            f"{BASE_URL}/api/resumes/{n}/download",
            f"{BASE_URL}/api/uploads/{n}",
            f"{BASE_URL}/api/uploads/{n}/download",
            f"{BASE_URL}/api/files/{n}",
            f"{BASE_URL}/api/files/{n}/download",
            f"{BASE_URL}/api/candidates/resume/{n}",
            f"{BASE_URL}/static/uploads/{n}",
            f"{BASE_URL}/static/resumes/{n}",
            f"{BASE_URL}/media/resumes/{n}",
            f"{BASE_URL}/files/{n}",
            f"{BASE_URL}/resumes/{n}",
        ]

    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = await context.request.get(url, headers=headers)
            body = await resp.body()
            ct = resp.headers.get("content-type", "")
            if resp.ok and is_real_file(body, ct):
                log.info(f"  [probe] ✓ {url}  ({len(body):,} bytes, {ct})")
                return url, body
        except Exception as e:
            log.debug(f"  [probe] {url}: {e}")

    return "", None


# ─── DOWNLOAD ONE RESUME ─────────────────────────────────────────────────────

async def download_resume(
    page: Page, context: BrowserContext,
    btn, href: str, save_path: Path,
    auth_token: str = None,
) -> tuple:
    """
    Returns (success: bool, final_path: Path).

    Strategy order:
    0. Direct fetch of BASE_URL+href using browser session cookies  ← NEW KEY FIX
    1. Intercept real network request when Download is clicked
    2. Probe known API endpoint patterns (with Bearer token)
    3. Probe with Authorization header variants
    4. Playwright download event (last resort)
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    resume_name = href.rstrip("/").split("/")[-1].split("?")[0]
    resume_name_bare = re.sub(r"\.(pdf|docx|doc)$", "", resume_name, flags=re.I)

    # ── S0: Direct fetch using session cookies (THE MAIN FIX) ────────────────
    # The /uploads/ endpoint IS a real backend route but needs session auth.
    # context.request.get() automatically sends the browser's session cookies.
    log.info(f"    [S0] Direct fetch with session cookies...")

    direct_urls = []
    if href:
        direct_url = BASE_URL + href if href.startswith("/") else href
        direct_urls.append(direct_url)

    # Also try common backend static-file paths
    for ext in [".pdf", ".docx", ".doc", ""]:
        direct_urls += [
            f"{BASE_URL}/uploads/{resume_name_bare}{ext}",
            f"{BASE_URL}/api/uploads/{resume_name_bare}{ext}",
        ]

    # Remove duplicates while preserving order
    seen_s0 = set()
    for url in direct_urls:
        if url in seen_s0:
            continue
        seen_s0.add(url)
        try:
            # First try with session cookies only (no explicit auth header)
            resp = await context.request.get(url)
            body = await resp.body()
            ct = resp.headers.get("content-type", "")
            log.info(f"    [S0] {url} → {resp.status}, {len(body)}b, ct={ct}")

            if resp.ok and is_real_file(body, ct):
                ext_final = ext_from_content_type(ct, url)
                final_path = save_path.with_suffix(ext_final)
                final_path.write_bytes(body)
                log.info(f"    ✓ [S0] Saved {final_path.name} ({len(body):,} bytes)")
                return True, final_path

            # If that failed, retry with Bearer token header
            if auth_token:
                resp2 = await context.request.get(
                    url, headers={"Authorization": f"Bearer {auth_token}"}
                )
                body2 = await resp2.body()
                ct2 = resp2.headers.get("content-type", "")
                log.info(f"    [S0+token] {url} → {resp2.status}, {len(body2)}b, ct={ct2}")
                if resp2.ok and is_real_file(body2, ct2):
                    ext_final = ext_from_content_type(ct2, url)
                    final_path = save_path.with_suffix(ext_final)
                    final_path.write_bytes(body2)
                    log.info(f"    ✓ [S0+token] Saved {final_path.name} ({len(body2):,} bytes)")
                    return True, final_path

        except Exception as e:
            log.warning(f"    [S0] {url}: {e}")

    # ── S1: Intercept real network request ───────────────────────────────────
    log.info(f"    [S1] Intercepting network request on click...")
    real_url = await discover_real_download_url(page, btn)

    if real_url:
        try:
            resp = await context.request.get(real_url)
            body = await resp.body()
            ct = resp.headers.get("content-type", "")
            log.info(f"    [S1] {resp.status}  {len(body)}b  ct={ct}")
            if resp.ok and is_real_file(body, ct):
                ext_final = ext_from_content_type(ct, real_url)
                final_path = save_path.with_suffix(ext_final)
                final_path.write_bytes(body)
                log.info(f"    ✓ [S1] Saved {final_path.name} ({len(body):,} bytes)")
                return True, final_path
        except Exception as e:
            log.warning(f"    [S1] Fetch failed: {e}")

    # ── S2: Probe API endpoint patterns ──────────────────────────────────────
    log.info(f"    [S2] Probing API endpoints for '{resume_name_bare}'...")
    found_url, body = await probe_api_endpoints(context, resume_name_bare, auth_token)
    if body:
        ext_final = ext_from_content_type("", found_url)
        final_path = save_path.with_suffix(ext_final)
        final_path.write_bytes(body)
        log.info(f"    ✓ [S2] Saved {final_path.name} ({len(body):,} bytes)")
        return True, final_path

    # ── S3: Playwright download event ────────────────────────────────────────
    log.info(f"    [S3] Trying Playwright download event...")
    try:
        async with page.expect_download(timeout=15_000) as dl_info:
            await btn.click()
        dl = await dl_info.value
        suggested = dl.suggested_filename or ""
        ext_final = Path(suggested).suffix if suggested else ".pdf"
        stem = safe_name(Path(suggested).stem) if suggested else safe_name(resume_name_bare)
        final_path = save_path.parent / f"{stem}_{ts}{ext_final}"
        await dl.save_as(final_path)
        size = final_path.stat().st_size
        content = final_path.read_bytes()
        if is_real_file(content, ""):
            log.info(f"    ✓ [S3] Saved {final_path.name} ({size:,} bytes)")
            return True, final_path
        log.warning(f"    [S3] Tiny/HTML file ({size}b)")
        final_path.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"    [S3] Download event failed: {e}")

    return False, save_path


# ─── AUTO LOGIN ──────────────────────────────────────────────────────────────

async def auto_login(page: Page, context: BrowserContext) -> tuple:
    """Returns (success: bool, auth_token: str | None)."""
    auth_token = None

    async def capture_token(response: Response):
        nonlocal auth_token
        try:
            if response.status == 200 and "login" in response.url:
                body = await response.json()
                token = (
                    body.get("token") or body.get("access_token") or body.get("accessToken")
                    or (body.get("data") or {}).get("token")
                )
                if token:
                    auth_token = token
                    log.info(f"  Captured auth token from {response.url}")
        except Exception:
            pass

    page.on("response", capture_token)

    log.info(f"-> Navigating to login page: {LOGIN_URL}")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_load_state("networkidle", timeout=10_000)
    await page.wait_for_timeout(1500)

    log.info("  Trying direct API login...")
    for endpoint in ["/api/auth/login", "/api/login", "/auth/login"]:
        try:
            resp = await page.request.post(
                BASE_URL + endpoint,
                data=json.dumps({"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD}),
                headers={"Content-Type": "application/json"},
            )
            if resp.ok:
                try:
                    body = await resp.json()
                    token = body.get("token") or body.get("access_token") or body.get("accessToken")
                    if token:
                        auth_token = token
                except Exception:
                    pass
                log.info(f"  API login succeeded at {endpoint}")
                await page.goto(ADMIN_URL, wait_until="domcontentloaded", timeout=20_000)
                await page.wait_for_timeout(2000)
                if "/login" not in page.url:
                    log.info(f"  Logged in via API — now at: {page.url}")
                    return True, auth_token
        except Exception as e:
            log.debug(f"  {endpoint}: {e}")

    log.info("  Trying JS fill + Enter...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_load_state("networkidle", timeout=10_000)
    await page.wait_for_timeout(1500)

    await page.evaluate(
        """([email, password]) => {
            const ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            const ei = document.querySelector('input[type="email"],input[name="email"]');
            const pi = document.querySelector('input[type="password"]');
            if (ei) { ns.call(ei,email); ei.dispatchEvent(new Event('input',{bubbles:true})); ei.dispatchEvent(new Event('change',{bubbles:true})); }
            if (pi) { ns.call(pi,password); pi.dispatchEvent(new Event('input',{bubbles:true})); pi.dispatchEvent(new Event('change',{bubbles:true})); }
        }""",
        [LOGIN_EMAIL, LOGIN_PASSWORD],
    )
    await page.wait_for_timeout(400)

    pass_loc = page.locator("input[type='password']").first
    if await pass_loc.count():
        await pass_loc.click()
        await page.wait_for_timeout(200)
        await page.keyboard.press("Enter")
        log.info("  Pressed Enter on password field")

    await page.wait_for_timeout(5000)
    if "/login" not in page.url:
        log.info(f"  Login successful — now at: {page.url}")
        return True, auth_token

    log.error("  All login strategies failed.")
    await page.screenshot(path="debug_login_failed.png")
    return False, None


# ─── CANDIDATE INFO ───────────────────────────────────────────────────────────

async def get_candidate_info(btn) -> tuple:
    for levels in range(2, 7):
        try:
            ancestor = btn.locator(f"xpath=ancestor::*[{levels}]")
            if not await ancestor.count():
                continue
            raw = (await ancestor.inner_text()).strip()
            if len(raw) > 400:
                continue
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            skip = {"Preview", "Download", "↓ Download", "Add Candidate", "Close",
                    "JOB DESCRIPTION", "CANDIDATES", "HR Dashboard", "Careers",
                    "Sign out", "hr admin", "MGCV Clone"}
            lines = [l for l in lines if l not in skip and not l.startswith("CANDIDATES (")]
            email_line = next((l for l in lines if "@" in l and "." in l and len(l) < 80), None)
            if not email_line:
                continue
            email_idx = lines.index(email_line)
            name = lines[email_idx - 1] if email_idx > 0 else None
            if name and len(name) > 1 and name not in skip:
                return name.strip(), email_line.strip()
        except Exception:
            continue
    try:
        href = await btn.get_attribute("href") or ""
        if href:
            fname = re.sub(r"\.(pdf|docx|doc)$", "", href.rstrip("/").split("/")[-1].split("?")[0], flags=re.I)
            if fname:
                return fname, f"unknown_{fname}"
    except Exception:
        pass
    return None, None


# ─── PROCESS ONE ROLE ────────────────────────────────────────────────────────

async def process_role(
    page: Page, context: BrowserContext,
    role: str, role_idx: int,
    history: dict, auth_token: str = None,
) -> list:
    results = []
    log.info(f"\n== [{role_idx}] {role} ==")

    if page.url != ADMIN_URL:
        await page.goto(ADMIN_URL, wait_until="domcontentloaded", timeout=20_000)
        await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.wait_for_timeout(1000)

    await page.wait_for_selector("table tbody tr", timeout=10_000)
    row = page.locator("table tbody tr").nth(role_idx - 1)
    if not await row.count():
        log.warning(f"  Row {role_idx} not found")
        return results

    await row.scroll_into_view_if_needed()
    await page.wait_for_timeout(500)

    try:
        first_cell = row.locator("td").first
        if await first_cell.count():
            await first_cell.click()
        else:
            await row.click()
    except Exception:
        await row.click()

    if not await wait_for_modal_open(page):
        log.warning(f"  Modal did not open for '{role}'")
        await page.screenshot(path=f"debug_{safe_name(role)}_no_modal.png")
        return results

    await page.wait_for_timeout(2000)

    dl_buttons = []
    for sel in [
        "a:has-text('Download')", "button:has-text('Download')",
        "a[href*='/uploads/']", "a[href*='resume']", "a[href*='.pdf']",
    ]:
        try:
            found = [b for b in await page.locator(sel).all() if await b.is_visible()]
            if found:
                dl_buttons = found
                log.info(f"  Found {len(found)} Download button(s) via: {sel}")
                break
        except Exception:
            pass

    if not dl_buttons:
        log.warning(f"  No Download buttons found for '{role}'")
        await page.screenshot(path=f"debug_{safe_name(role)}_modal.png", full_page=True)
        await close_modal(page)
        return results

    log.info("  Download button hrefs:")
    for i, b in enumerate(dl_buttons):
        try:
            h = await b.get_attribute("href") or ""
            log.info(f"    [{i+1}] {h}")
        except Exception:
            pass

    role_dir = DOWNLOAD_DIR / safe_name(role)
    role_dir.mkdir(parents=True, exist_ok=True)

    for idx, btn in enumerate(dl_buttons, start=1):
        candidate_name, email = await get_candidate_info(btn)
        href = ""
        try:
            href = await btn.get_attribute("href") or ""
        except Exception:
            pass

        unique_key = href.strip() if href.strip() else f"pos_{idx}"
        if not candidate_name or candidate_name in ("Preview", "Download", "HR Dashboard"):
            candidate_name = f"candidate_{idx}"
        if not email or email == LOGIN_EMAIL:
            email = unique_key

        log.info(f"  [{idx}] '{candidate_name}'  href='{href}'")

        if already_downloaded(history, role, unique_key):
            log.info(f"  [{idx}] SKIPPED (already downloaded)")
            results.append(dict(role=role, candidate=candidate_name, email=unique_key,
                                file="", ok=True, skipped=True))
            continue

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = role_dir / f"{safe_name(candidate_name)}_{ts}.pdf"

        downloaded, final_path = await download_resume(
            page, context, btn, href, save_path, auth_token
        )

        if not downloaded:
            log.error(f"    ✗ All strategies failed for '{candidate_name}'")
        else:
            mark_downloaded(history, role, unique_key)
            save_history(history)

        results.append(dict(
            role=role, candidate=candidate_name, email=unique_key,
            file=str(final_path) if downloaded else "",
            ok=downloaded, skipped=False,
        ))

    await close_modal(page)
    await page.wait_for_timeout(1500)
    return results


# ─── MAIN ────────────────────────────────────────────────────────────────────

async def scrape(target_role: str = None):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    history = load_history()
    log.info(f"Loaded history: {sum(len(v) for v in history.values())} previously downloaded candidate(s)")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = await context.new_page()

        login_ok, auth_token = await auto_login(page, context)
        if not login_ok:
            log.error("Login failed — aborting.")
            await browser.close()
            return [], 0, 0, 0

        log.info(f"-> Navigating to admin panel: {ADMIN_URL}")
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
            roles_to_process = [(i+1, r) for i, r in enumerate(role_names) if target_role.lower() in r.lower()]
            if not roles_to_process:
                print(f"\n  No role matching '{target_role}'. Available: {role_names}")
                await browser.close()
                return [], 0, 0, 0
        else:
            roles_to_process = [(i+1, r) for i, r in enumerate(role_names)]

        all_results = []
        for role_idx, role in roles_to_process:
            results = await process_role(page, context, role, role_idx, history, auth_token)
            all_results.extend(results)

        await browser.close()

        new_dl  = sum(1 for r in all_results if r["ok"] and not r.get("skipped"))
        skipped = sum(1 for r in all_results if r.get("skipped"))
        failed  = sum(1 for r in all_results if not r["ok"] and not r.get("skipped"))

        print("\n" + "=" * 55)
        print("FINAL SUMMARY")
        print("=" * 55)
        print(f"  NEW downloads  : {new_dl}")
        print(f"  Skipped        : {skipped}  (already downloaded before)")
        print(f"  Failed         : {failed}")
        print(f"  Saved to       : {DOWNLOAD_DIR.resolve()}")
        print()
        for item in all_results:
            tag = "SKIP" if item.get("skipped") else ("NEW " if item["ok"] else "FAIL")
            print(f"  [{tag}]  [{item['role']}]  {item['candidate']}")
            if item["ok"] and not item.get("skipped"):
                print(f"          -> {item['file']}")

        return all_results, new_dl, skipped, failed


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  MGCV Clone HR Dashboard - Resume Auto-Downloader (Fixed v3)")
    print("=" * 55)
    print(f"  Target  : {ADMIN_URL}")
    print(f"  Output  : {DOWNLOAD_DIR.resolve()}")
    print("=" * 55)

    print("\nOptions:")
    print("  1. Download ALL job roles")
    print("  2. Download a specific job role")
    print("  3. Clear download history (re-download everything)")
    choice = input("\nEnter choice (1, 2, or 3): ").strip()

    if choice == "3":
        if HISTORY_FILE.exists():
            HISTORY_FILE.unlink()
            print("\n  ✓ History cleared.")
        else:
            print("\n  No history file found.")
        exit(0)

    target = None
    if choice == "2":
        target = input("Enter job title (e.g. 'AI/ML'): ").strip()
        print(f"\n  Downloading resumes for: {target}")
    else:
        print("\n  Downloading resumes for ALL roles")

    results, new_dl, skipped, failed = asyncio.run(scrape(target_role=target))
    print(f"\nDone — {new_dl} new, {skipped} skipped, {failed} failed.")
    print(f"Files: {DOWNLOAD_DIR.resolve()}")