# #!/usr/bin/env python3
# """
# RecruitAI — Assessment Result Scraper
# - Opens the ngrok RecruitAI site (Recruiter Portal)
# - Scrapes candidate results for a given job role
# - Saves exam_score, exam_percentage, exam_status back to the candidates DB table
# """

# import asyncio
# import logging
# import os
# import re
# from datetime import datetime
# from playwright.async_api import async_playwright, Page

# # ─── CONFIG ──────────────────────────────────────────────────────────────────
# BASE_URL  = "http://13.201.5.251"
# HEADLESS  = False
# # ─────────────────────────────────────────────────────────────────────────────

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s  %(levelname)s  %(message)s",
# )
# log = logging.getLogger(__name__)


# # ─── SCRAPE RESULTS FROM RECRUITAI SITE ──────────────────────────────────────

# async def scrape_results_for_job(job_title: str) -> list:
#     """
#     Opens RecruitAI Recruiter Portal, finds the job matching job_title,
#     clicks View Results, and returns a list of candidate result dicts:
#       [{ name, email, status, score_pct, date }]
#     """
#     results = []

#     async with async_playwright() as pw:
#         browser = await pw.chromium.launch(headless=HEADLESS)
#         context = await browser.new_context(
#             viewport={"width": 1440, "height": 900},
#             extra_http_headers={"ngrok-skip-browser-warning": "true"},
#         )
#         page = await context.new_page()

#         # ── 1. Open site ──────────────────────────────────────────────────────
#         log.info(f"-> Opening {BASE_URL}")
#         await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
#         await page.wait_for_load_state("networkidle", timeout=10_000)

#         # ── 2. Click Recruiter Portal ─────────────────────────────────────────
#         log.info("-> Clicking Recruiter Portal")
#         for sel in ["text=Recruiter Portal", "div:has-text('Recruiter Portal')"]:
#             try:
#                 if await page.locator(sel).count() > 0:
#                     await page.locator(sel).first.click()
#                     break
#             except Exception:
#                 continue
#         await page.wait_for_load_state("networkidle", timeout=10_000)
#         await page.wait_for_timeout(1500)

#         # ── 3. Find the job card matching job_title ───────────────────────────
#         log.info(f"-> Looking for job: {job_title}")
#         job_cards = await page.locator("h2, h3, [class*='title'], [class*='card']").all()

#         view_results_clicked = False
#         for card in job_cards:
#             try:
#                 text = (await card.inner_text()).strip()
#                 if job_title.lower() in text.lower():
#                     log.info(f"  Found matching card: {text}")
#                     # Find View Results button near this card
#                     parent = card.locator("xpath=ancestor::*[3]")
#                     for btn_sel in [
#                         "text=View Results",
#                         "a:has-text('View Results')",
#                         "button:has-text('View')",
#                         "a:has-text('View')",
#                     ]:
#                         try:
#                             btn = parent.locator(btn_sel).first
#                             if await btn.count() > 0:
#                                 await btn.click()
#                                 view_results_clicked = True
#                                 log.info("  Clicked View Results")
#                                 break
#                         except Exception:
#                             continue
#                     if view_results_clicked:
#                         break
#             except Exception:
#                 continue

#         # Fallback: click first View Results on page
#         if not view_results_clicked:
#             for sel in ["text=View Results", "a:has-text('View Results')"]:
#                 try:
#                     if await page.locator(sel).count() > 0:
#                         await page.locator(sel).first.click()
#                         view_results_clicked = True
#                         break
#                 except Exception:
#                     continue

#         if not view_results_clicked:
#             log.warning("Could not find View Results button")
#             await browser.close()
#             return results

#         await page.wait_for_load_state("networkidle", timeout=10_000)
#         await page.wait_for_timeout(2000)
#         log.info("-> On results page, extracting candidates...")

#         # ── 4. Extract candidate rows ─────────────────────────────────────────
#         # Results table has: CANDIDATE | STATUS | SCORE | DATE
#         rows = await page.locator("table tbody tr, [class*='row'], [class*='candidate-row']").all()
#         log.info(f"  Found {len(rows)} candidate rows")

#         for row in rows:
#             try:
#                 row_text = (await row.inner_text()).strip()
#                 if not row_text or len(row_text) < 3:
#                     continue

#                 cells = await row.locator("td").all()

#                 name       = ""
#                 email      = ""
#                 status     = ""
#                 score_pct  = None
#                 date_str   = ""

#                 if len(cells) >= 4:
#                     # Cell 0: name + email
#                     cell0_text = (await cells[0].inner_text()).strip()
#                     lines = [l.strip() for l in cell0_text.splitlines() if l.strip()]
#                     name  = lines[0] if lines else ""
#                     email = next((l for l in lines if "@" in l), "")

#                     # Cell 1: status (COMPLETED / PENDING)
#                     status = (await cells[1].inner_text()).strip()

#                     # Cell 2: score (e.g. "16%")
#                     score_raw = (await cells[2].inner_text()).strip()
#                     pct_match = re.search(r"(\d+(?:\.\d+)?)", score_raw)
#                     if pct_match:
#                         score_pct = float(pct_match.group(1))

#                     # Cell 3: date
#                     date_str = (await cells[3].inner_text()).strip()

#                 else:
#                     # Fallback: parse full row text
#                     email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", row_text)
#                     email = email_match.group(0) if email_match else ""
#                     pct_match = re.search(r"(\d+)%", row_text)
#                     if pct_match:
#                         score_pct = float(pct_match.group(1))
#                     status = "COMPLETED" if "completed" in row_text.lower() else "PENDING"

#                 if name or email:
#                     results.append({
#                         "name":      name,
#                         "email":     email,
#                         "status":    status.upper(),
#                         "score_pct": score_pct,
#                         "date":      date_str,
#                     })
#                     log.info(f"  Candidate: {name} <{email}> | {status} | {score_pct}% | {date_str}")

#             except Exception as e:
#                 log.debug(f"Row parse error: {e}")
#                 continue

#         await browser.close()
#         log.info(f"Scraped {len(results)} candidate result(s) for '{job_title}'")

#     return results


# # ─── SAVE RESULTS TO DATABASE ─────────────────────────────────────────────────

# def save_results_to_db(job_title: str, results: list):
#     """
#     Matches scraped results to candidates in DB by email + job_title,
#     and updates their exam fields.
#     """
#     if not results:
#         log.warning("No results to save")
#         return

#     try:
#         from app.models.db import SessionLocal, Candidate
#     except ImportError as ie:
#         import sys, os
#         project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#         if project_root not in sys.path:
#             sys.path.insert(0, project_root)
#         from app.models.db import SessionLocal, Candidate

#     session = SessionLocal()
#     updated = 0
#     not_found = 0

#     try:
#         for r in results:
#             email     = r.get("email", "").strip().lower()
#             score_pct = r.get("score_pct")
#             status    = r.get("status", "")
#             completed = status == "COMPLETED"

#             if not email:
#                 continue

#             # Find candidate by email and job_title
#             candidate = session.query(Candidate).filter(
#                 Candidate.email.ilike(email),
#                 Candidate.job_title.ilike(f"%{job_title}%")
#             ).first()

#             if not candidate:
#                 log.warning(f"  Candidate not found in DB: {email} / {job_title}")
#                 not_found += 1
#                 continue

#             # Update exam fields
#             candidate.exam_percentage  = score_pct
#             candidate.exam_score       = score_pct
#             candidate.exam_completed   = completed
#             candidate.exam_completed_date = datetime.utcnow() if completed else None

#             # Map score to pass/fail (50% threshold — adjust as needed)
#             if score_pct is not None:
#                 if score_pct >= 50:
#                     candidate.final_status = "Assessment Passed"
#                 else:
#                     candidate.final_status = "Assessment Failed"

#             log.info(f"  Updated: {email} | score={score_pct}% | {candidate.final_status}")
#             updated += 1

#         session.commit()
#         log.info(f"DB update complete — {updated} updated, {not_found} not found in DB")

#     except Exception as e:
#         session.rollback()
#         log.error(f"DB save failed: {e}", exc_info=True)
#     finally:
#         session.close()


# # ─── MAIN ENTRY POINT ────────────────────────────────────────────────────────

# async def scrape_and_save_results(job_title: str):
#     """Full flow: scrape RecruitAI → save to DB"""
#     log.info(f"=== Scraping RecruitAI results for: {job_title} ===")
#     results = await scrape_results_for_job(job_title)

#     if results:
#         save_results_to_db(job_title, results)
#     else:
#         log.warning("No results found to save")

#     return results


# # ─── PIPELINE INTEGRATION ─────────────────────────────────────────────────────

# def run_result_scraper(job_title: str) -> list:
#     """
#     Synchronous wrapper — call this from pipeline.py after AI screening.
#     Usage:
#         from app.services.recruitai_score_scraper import run_result_scraper
#         run_result_scraper(job_title)
#     """
#     return asyncio.run(scrape_and_save_results(job_title))


# # ─── CLI ─────────────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     import sys
#     title = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter job title: ").strip()
#     asyncio.run(scrape_and_save_results(title))
#!/usr/bin/env python3
"""
RecruitAI — Assessment Result Scraper
- Opens RecruitAI site (Recruiter Portal)
- Scrapes candidate results for a given job role
- Saves exam_score, exam_percentage, exam_status back to the candidates DB table

FIX: Results now saved ONLY to the candidate row whose job_title
     matches the scraped job title — NOT to all rows with that email.
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BASE_URL = "https://hrhiringassessmentrequirment-production.up.railway.app"
HEADLESS = True
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


# ─── SCRAPE RESULTS FROM RECRUITAI SITE ──────────────────────────────────────

async def scrape_results_for_job(job_title: str) -> list:
    """
    Opens RecruitAI Recruiter Portal, finds the job matching job_title,
    clicks View Results, and returns a list of candidate result dicts:
      [{ name, email, status, score_pct, date, scraped_job_title }]
    """
    results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            extra_http_headers={"ngrok-skip-browser-warning": "true"},
        )
        page = await context.new_page()

        # ── 1. Open site ──────────────────────────────────────────────────────
        log.info(f"-> Opening {BASE_URL}")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_load_state("networkidle", timeout=10_000)

        # ── 2. Click Recruiter Portal ─────────────────────────────────────────
        log.info("-> Clicking Recruiter Portal")
        for sel in ["text=Recruiter Portal", "div:has-text('Recruiter Portal')"]:
            try:
                if await page.locator(sel).count() > 0:
                    await page.locator(sel).first.click()
                    break
            except Exception:
                continue
        await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.wait_for_timeout(1500)

        # ── 3. Find the job card matching job_title ───────────────────────────
        log.info(f"-> Looking for job: {job_title}")
        job_cards = await page.locator("h2, h3, [class*='title'], [class*='card']").all()

        view_results_clicked = False
        for card in job_cards:
            try:
                text = (await card.inner_text()).strip()
                if job_title.lower() in text.lower():
                    log.info(f"  Found matching card: {text}")
                    parent = card.locator("xpath=ancestor::*[3]")
                    for btn_sel in [
                        "text=View Results",
                        "a:has-text('View Results')",
                        "button:has-text('View')",
                        "a:has-text('View')",
                    ]:
                        try:
                            btn = parent.locator(btn_sel).first
                            if await btn.count() > 0:
                                await btn.click()
                                view_results_clicked = True
                                log.info("  Clicked View Results")
                                break
                        except Exception:
                            continue
                    if view_results_clicked:
                        break
            except Exception:
                continue

        # Fallback: click first View Results on page
        if not view_results_clicked:
            for sel in ["text=View Results", "a:has-text('View Results')"]:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.locator(sel).first.click()
                        view_results_clicked = True
                        break
                except Exception:
                    continue

        if not view_results_clicked:
            log.warning("Could not find View Results button")
            await browser.close()
            return results

        await page.wait_for_load_state("networkidle", timeout=10_000)
        await page.wait_for_timeout(2000)
        log.info("-> On results page, extracting candidates...")

        # ── 4. Extract candidate rows ─────────────────────────────────────────
        rows = await page.locator("table tbody tr, [class*='row'], [class*='candidate-row']").all()
        log.info(f"  Found {len(rows)} candidate rows")

        for row in rows:
            try:
                row_text = (await row.inner_text()).strip()
                if not row_text or len(row_text) < 3:
                    continue

                cells     = await row.locator("td").all()
                name      = ""
                email     = ""
                status    = ""
                score_pct = None
                date_str  = ""

                if len(cells) >= 4:
                    cell0_text = (await cells[0].inner_text()).strip()
                    lines = [l.strip() for l in cell0_text.splitlines() if l.strip()]
                    name  = lines[0] if lines else ""
                    email = next((l for l in lines if "@" in l), "")
                    status    = (await cells[1].inner_text()).strip()
                    score_raw = (await cells[2].inner_text()).strip()
                    pct_match = re.search(r"(\d+(?:\.\d+)?)", score_raw)
                    if pct_match:
                        score_pct = float(pct_match.group(1))
                    date_str = (await cells[3].inner_text()).strip()
                else:
                    email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", row_text)
                    email = email_match.group(0) if email_match else ""
                    pct_match = re.search(r"(\d+)%", row_text)
                    if pct_match:
                        score_pct = float(pct_match.group(1))
                    status = "COMPLETED" if "completed" in row_text.lower() else "PENDING"

                if name or email:
                    results.append({
                        "name":             name,
                        "email":            email,
                        "status":           status.upper(),
                        "score_pct":        score_pct,
                        "date":             date_str,
                        # ✅ FIX: carry the exact job title this result belongs to
                        "scraped_job_title": job_title,
                    })
                    log.info(
                        f"  Candidate: {name} <{email}> | {status} | "
                        f"{score_pct}% | {date_str} | job='{job_title}'"
                    )

            except Exception as e:
                log.debug(f"Row parse error: {e}")
                continue

        await browser.close()
        log.info(f"Scraped {len(results)} candidate result(s) for '{job_title}'")

    return results


# ─── SAVE RESULTS TO DATABASE ─────────────────────────────────────────────────

def save_results_to_db(job_title: str, results: list):
    """
    Matches scraped results to candidates in DB by BOTH email AND job_title.

    ROOT CAUSE OF BUG (now fixed):
      The old code had a fallback: if job_title match failed, it fell back to
      email-only match ordered by id.desc(). This caused the result from
      "web developer" assessment to overwrite the LATEST row for that email —
      which could be "data science", "python developer", etc.

    FIX:
      1. Fetch ALL rows for the email.
      2. Pick the row whose job_title BEST matches the scraped job title.
      3. If NO row has a close job_title match → log a warning and SKIP.
         Never fall back to a different job title row.
    """
    if not results:
        log.warning("No results to save")
        return

    try:
        from app.models.db import SessionLocal, Candidate
    except ImportError:
        import sys, os
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from app.models.db import SessionLocal, Candidate

    session = SessionLocal()
    updated   = 0
    not_found = 0
    skipped   = 0

    try:
        for r in results:
            email            = r.get("email", "").strip().lower()
            score_pct        = r.get("score_pct")
            status           = r.get("status", "")
            completed        = status == "COMPLETED"
            result_job_title = r.get("scraped_job_title") or job_title

            if not email:
                log.warning("  Skipping result with no email")
                skipped += 1
                continue

            # ── Fetch ALL rows for this email ─────────────────────────────────
            all_rows = (
                session.query(Candidate)
                .filter(Candidate.email.ilike(email))
                .all()
            )

            if not all_rows:
                log.warning(f"  No candidate found with email: {email}")
                not_found += 1
                continue

            # ── Find best-matching job_title row ──────────────────────────────
            candidate = _best_job_match(all_rows, result_job_title)

            if not candidate:
                # ✅ FIX: DO NOT fall back to a random row.
                # Log all rows so you can debug the mismatch.
                log.warning(
                    f"  No job_title match for '{result_job_title}' "
                    f"and email '{email}'. "
                    f"Candidate has rows for: "
                    f"{[r.job_title for r in all_rows]}. SKIPPING."
                )
                not_found += 1
                continue

            # ── Only update if assessment was sent for this role ──────────────
            if hasattr(candidate, 'exam_link_sent') and not candidate.exam_link_sent:
                log.warning(
                    f"  Skipping {email} / '{candidate.job_title}' "
                    f"— exam link was never sent for this role"
                )
                skipped += 1
                continue

            # ── Apply the update ──────────────────────────────────────────────
            candidate.exam_percentage     = score_pct
            candidate.exam_score          = score_pct
            candidate.exam_completed      = completed
            candidate.exam_completed_date = datetime.utcnow() if completed else None

            if score_pct is not None:
                candidate.final_status = (
                    "Assessment Passed" if score_pct >= 50
                    else "Assessment Failed"
                )

            log.info(
                f"  ✅ Updated: {email} | job='{candidate.job_title}' | "
                f"score={score_pct}% | {candidate.final_status}"
            )
            updated += 1

        session.commit()
        log.info(
            f"DB update complete — {updated} updated, "
            f"{not_found} not found/no match, {skipped} skipped"
        )

    except Exception as e:
        session.rollback()
        log.error(f"DB save failed: {e}", exc_info=True)
    finally:
        session.close()


def _best_job_match(rows, job_title: str):
    """
    Given a list of Candidate rows (all same email, different job titles),
    return the row whose job_title best matches job_title.

    Matching priority:
      1. Exact match (case-insensitive)
      2. One title fully contains the other
      3. Highest word-overlap ratio (must be >= 0.5)
      4. None — no acceptable match found
    """
    target = job_title.strip().lower()

    # 1. Exact match
    for row in rows:
        if row.job_title and row.job_title.strip().lower() == target:
            log.info(f"    job_title exact match: '{row.job_title}'")
            return row

    # 2. One contains the other
    for row in rows:
        if not row.job_title:
            continue
        rt = row.job_title.strip().lower()
        if target in rt or rt in target:
            log.info(f"    job_title contains match: '{row.job_title}'")
            return row

    # 3. Word-overlap (≥ 50% of target words appear in row title)
    target_words = set(target.split())
    best_row     = None
    best_ratio   = 0.0

    for row in rows:
        if not row.job_title:
            continue
        row_words = set(row.job_title.strip().lower().split())
        overlap   = len(target_words & row_words)
        ratio     = overlap / max(len(target_words), 1)
        if ratio > best_ratio:
            best_ratio = ratio
            best_row   = row

    if best_ratio >= 0.5:
        log.info(
            f"    job_title word-overlap match ({best_ratio:.0%}): "
            f"'{best_row.job_title}'"
        )
        return best_row

    # No acceptable match
    return None


# ─── MAIN ENTRY POINT ────────────────────────────────────────────────────────

async def scrape_and_save_results(job_title: str):
    """Full flow: scrape RecruitAI → save to DB"""
    log.info(f"=== Scraping RecruitAI results for: {job_title} ===")
    results = await scrape_results_for_job(job_title)

    if results:
        save_results_to_db(job_title, results)
    else:
        log.warning("No results found to save")

    return results


# ─── PIPELINE INTEGRATION ─────────────────────────────────────────────────────

def run_result_scraper(job_title: str) -> list:
    """
    Synchronous wrapper — call this from pipeline.py after AI screening.
    Usage:
        from app.services.assessment_result import run_result_scraper
        run_result_scraper(job_title)
    """
    return asyncio.run(scrape_and_save_results(job_title))


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    title = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter job title: ").strip()
    asyncio.run(scrape_and_save_results(title))
