"""
app/services/post_assessment_automation.py

24/7 BACKGROUND SERVICE:
  Every 15 min:
    1. Find candidates: exam_link_sent=True, exam_completed=False/None
    2. Scrape RecruitAI ngrok site for their results
    3. Save score to DB
    4. score >= 50%  →  generate interview link + send interview email
    5. score <  50%  →  send rejection email

Starts automatically when Flask starts.
"""

import os
import time
import uuid
import asyncio
import logging
import threading
import importlib
from datetime import datetime, timedelta
from sqlalchemy import and_, or_

from app.models.db import SessionLocal, Candidate

try:
    from app.utils.email_util import send_interview_link_email, send_rejection_email
except Exception:
    def send_interview_link_email(**kw):
        logging.getLogger(__name__).warning(f"[EMAIL SHIM] interview -> {kw.get('candidate_email')}")
    def send_rejection_email(c):
        logging.getLogger(__name__).warning(f"[EMAIL SHIM] rejection -> {c.email}")

log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
CHECK_INTERVAL = int(os.getenv("POST_ASSESSMENT_INTERVAL", "900"))    # 15 min default
PASS_THRESHOLD = float(os.getenv("ASSESSMENT_PASS_THRESHOLD", "50"))  # 50% default
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:3000")
COMPANY_NAME   = os.getenv("COMPANY_NAME", "TalentFlow AI")
# ─────────────────────────────────────────────────────────────────────────────


class PostAssessmentAutomation:

    def __init__(self):
        self.is_running = False
        self._thread    = None
        self._lock      = threading.Lock()

    # ── LIFECYCLE ─────────────────────────────────────────────────────────────

    def start(self):
        with self._lock:
            if self.is_running:
                log.warning("PostAssessmentAutomation already running")
                return
            self.is_running = True
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="post_assessment_automation"
            )
            self._thread.start()
            log.info(
                "PostAssessmentAutomation started | interval=%ds | pass_threshold=%.0f%%",
                CHECK_INTERVAL, PASS_THRESHOLD
            )

    def stop(self):
        self.is_running = False
        log.info("PostAssessmentAutomation stopped")

    @property
    def status(self):
        return {
            "is_running":     self.is_running,
            "interval_sec":   CHECK_INTERVAL,
            "pass_threshold": PASS_THRESHOLD,
            "thread_alive":   bool(self._thread and self._thread.is_alive()),
        }

    # ── LOOP ──────────────────────────────────────────────────────────────────

    def _loop(self):
        log.info("[PostAssessment] Waiting 2 min before first check...")
        time.sleep(120)  # let Flask fully boot first
        while self.is_running:
            try:
                log.info("[PostAssessment] ---- cycle start ----")
                self._cycle()
                log.info("[PostAssessment] ---- cycle done | sleeping %ds ----", CHECK_INTERVAL)
            except Exception as e:
                log.error("[PostAssessment] Cycle error: %s", e, exc_info=True)
            time.sleep(CHECK_INTERVAL)

    # ── CYCLE ─────────────────────────────────────────────────────────────────

    def _cycle(self):
        session = SessionLocal()
        try:
            pending = session.query(Candidate).filter(
                and_(
                    Candidate.exam_link_sent == True,
                    or_(
                        Candidate.exam_completed == False,
                        Candidate.exam_completed == None,
                    )
                )
            ).all()

            if not pending:
                log.info("[PostAssessment] No pending candidates")
                return

            log.info("[PostAssessment] %d pending candidate(s) found", len(pending))

            # Group by job_title — one scrape call per job
            jobs = {}
            for c in pending:
                jobs.setdefault(c.job_title or "Unknown", []).append(c)

            for job_title, candidates in jobs.items():
                try:
                    self._process_job(job_title, candidates, session)
                except Exception as e:
                    log.error("[PostAssessment] Error for '%s': %s", job_title, e, exc_info=True)

            session.commit()

        except Exception as e:
            session.rollback()
            log.error("[PostAssessment] DB error: %s", e, exc_info=True)
        finally:
            session.close()

    # ── PER-JOB ───────────────────────────────────────────────────────────────

    def _process_job(self, job_title: str, candidates: list, session):
        # Import scraper — supports both filenames
        scrape_fn = None
        for mod_name in ("app.services.assessment_result",
                         "app.services.recruitai_score_scraper"):
            try:
                mod = importlib.import_module(mod_name)
                scrape_fn = mod.scrape_results_for_job
                break
            except Exception:
                continue

        if not scrape_fn:
            log.error("[PostAssessment] scrape_results_for_job not found — check file name")
            return

        # Run async scraper
        try:
            scraped = asyncio.run(scrape_fn(job_title))
        except Exception as e:
            log.error("[PostAssessment] Scraping failed for '%s': %s", job_title, e)
            return

        if not scraped:
            log.info("[PostAssessment] No results on RecruitAI yet for '%s'", job_title)
            return

        log.info("[PostAssessment] Got %d result(s) from RecruitAI for '%s'",
                 len(scraped), job_title)

        # Build lookup maps: email & name
        by_email = {r["email"].lower(): r for r in scraped if r.get("email")}
        by_name  = {r["name"].lower():  r for r in scraped if r.get("name")}

        for candidate in candidates:
            # Match: exact email → exact name → partial name
            result = (
                by_email.get((candidate.email or "").lower())
                or by_name.get((candidate.name or "").lower())
                or next(
                    (v for k, v in by_name.items()
                     if candidate.name and candidate.name.lower() in k),
                    None
                )
            )

            if not result:
                log.info("[PostAssessment] No result yet for %s", candidate.name)
                continue

            if result.get("status", "").upper() != "COMPLETED":
                log.info("[PostAssessment] %s — exam not completed yet", candidate.name)
                continue

            score_pct = result.get("score_pct")
            log.info("[PostAssessment] %s | COMPLETED | score=%s%%",
                     candidate.name, score_pct)

            # Save score to DB
            candidate.exam_completed      = True
            candidate.exam_completed_date = datetime.utcnow()
            candidate.exam_percentage     = score_pct
            candidate.exam_score          = score_pct

            # Act on result
            if score_pct is not None and score_pct >= PASS_THRESHOLD:
                self._handle_pass(candidate)
            else:
                self._handle_fail(candidate)

    # ── PASS ──────────────────────────────────────────────────────────────────

    def _handle_pass(self, candidate: Candidate):
        log.info("PASS: %s (%.1f%%) -> interview invite",
                 candidate.name, candidate.exam_percentage or 0)

        candidate.final_status = "Assessment Passed"

        # Don't double-schedule
        if candidate.interview_scheduled and candidate.interview_token:
            log.info("[PostAssessment] Already scheduled for %s — skipping", candidate.name)
            return

        token          = str(uuid.uuid4())
        interview_link = f"{FRONTEND_URL}/secure-interview/{token}"
        interview_date = datetime.utcnow() + timedelta(days=2)

        candidate.interview_token     = token
        candidate.interview_link      = interview_link
        candidate.interview_scheduled = True
        candidate.interview_date      = interview_date

        # Optional columns
        for attr, val in {
            "interview_email_sent":      True,
            "interview_email_sent_date": datetime.utcnow(),
            "interview_expires_at":      datetime.utcnow() + timedelta(days=7),
        }.items():
            if hasattr(candidate, attr):
                setattr(candidate, attr, val)

        try:
            send_interview_link_email(
                candidate_email=candidate.email,
                candidate_name=candidate.name,
                interview_link=interview_link,
                interview_date=interview_date,
                time_slot="Flexible — access anytime within 7 days",
                position=candidate.job_title,
            )
            log.info("Interview email sent -> %s", candidate.email)
        except Exception as e:
            log.error("Interview email FAILED for %s: %s", candidate.email, e)

    # ── FAIL ──────────────────────────────────────────────────────────────────

    def _handle_fail(self, candidate: Candidate):
        log.info("FAIL: %s (%.1f%%) -> rejection",
                 candidate.name, candidate.exam_percentage or 0)

        candidate.final_status = "Assessment Failed"
        if hasattr(candidate, "rejection_reason"):
            candidate.rejection_reason = (
                f"Score {candidate.exam_percentage:.0f}% < threshold {PASS_THRESHOLD:.0f}%"
            )

        try:
            send_rejection_email(candidate)
            log.info("Rejection email sent -> %s", candidate.email)
        except Exception as e:
            log.error("Rejection email FAILED for %s: %s", candidate.email, e)


# ── SINGLETON + PUBLIC API ────────────────────────────────────────────────────

_instance = PostAssessmentAutomation()


def start_post_assessment_automation():
    """Call once on app startup — starts 24/7 background thread."""
    _instance.start()


def stop_post_assessment_automation():
    _instance.stop()


def get_automation_status():
    return _instance.status


def run_once_now(job_title: str = None):
    """
    Trigger one check cycle immediately (no delay).
    Called from pipeline.py after assessment creation.
    """
    log.info("[run_once_now] Triggered | job_title=%s", job_title or "ALL")
    session = SessionLocal()
    try:
        query = session.query(Candidate).filter(
            and_(
                Candidate.exam_link_sent == True,
                or_(
                    Candidate.exam_completed == False,
                    Candidate.exam_completed == None,
                )
            )
        )
        if job_title:
            query = query.filter(Candidate.job_title.ilike(f"%{job_title}%"))

        pending = query.all()
        log.info("[run_once_now] %d candidate(s) to check", len(pending))

        jobs = {}
        for c in pending:
            jobs.setdefault(c.job_title or "Unknown", []).append(c)

        for jt, candidates in jobs.items():
            _instance._process_job(jt, candidates, session)

        session.commit()
        log.info("[run_once_now] Complete")

    except Exception as e:
        session.rollback()
        log.error("[run_once_now] Error: %s", e, exc_info=True)
    finally:
        session.close()


# ── CLI: python app/services/post_assessment_automation.py "Senior Software Engineer"
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s"
    )
    title = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    run_once_now(title)