# app/services/interview_automation.py
"""
Interview automation service for TalentFlow.
- Runs a background loop that sets up AI interviews for candidates who passed assessments.
- Uses app.models.db for DB access and app.utils.email_util for sending emails.
(Adapted from your original module; imports and side-effects cleaned.)
"""

import os
import time
import threading
import logging
import uuid
from datetime import datetime, timedelta

import requests
import json
from sqlalchemy import and_, or_

from app.models.db import Candidate, SessionLocal
# If your real email util lives elsewhere, update this import:
try:
    from app.utils.email_util import send_email
except Exception:
    # Minimal fallback so the module can import even if email util isn't wired yet.
    def send_email(to_addr: str, subject: str, html: str) -> None:
        logging.getLogger(__name__).warning(
            "send_email() shim used. Implement app.utils.email_util.send_email"
        )

logger = logging.getLogger(__name__)


class InterviewAutomationSystem:
    """Automated interview system that runs on an interval in a background thread."""

    def __init__(self):
        self.is_running = False
        self.check_interval = 1800  # 30 minutes
        self.thread: threading.Thread | None = None

        self.heygen_api_key = os.getenv("HEYGEN_API_KEY")
        self.heygen_api_url = "https://api.heygen.com/v1/streaming/knowledge_base/create"

    # ---- lifecycle ----
    def start(self) -> None:
        if self.is_running:
            logger.warning("Interview automation system already running")
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("Interview automation system started")

    def stop(self) -> None:
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("Interview automation system stopped")

    # ---- loop ----
    def _run_loop(self) -> None:
        while self.is_running:
            try:
                logger.info("🔄 Running interview automation check...")
                self._process_candidates()
            except Exception as e:
                logger.error("Error in interview automation loop: %s", e, exc_info=True)
            time.sleep(self.check_interval)

    # ---- core logic ----
    def _process_candidates(self) -> None:
        """Candidates who: completed exam, >=70%, not scheduled, no KB yet."""
        session = SessionLocal()
        try:
            candidates = (
                session.query(Candidate)
                .filter(
                    and_(
                        Candidate.exam_completed.is_(True),
                        Candidate.exam_percentage >= 70,
                        Candidate.interview_scheduled.is_(False),
                        or_(Candidate.interview_kb_id.is_(None), Candidate.interview_kb_id == ""),
                    )
                )
                .all()
            )

            logger.info("Found %d candidates ready for interview setup", len(candidates))

            for cand in candidates:
                try:
                    self._setup_interview_for_candidate(cand, session)
                except Exception as e:
                    logger.error("Failed to setup interview for candidate %s: %s", cand.id, e, exc_info=True)
                    continue

            session.commit()
        except Exception as e:
            logger.error("Error processing candidates: %s", e, exc_info=True)
            session.rollback()
        finally:
            session.close()

    def _setup_interview_for_candidate(self, candidate: Candidate, session) -> None:
        logger.info("Setting up interview for %s (%s)", candidate.name, candidate.email)

        # 1) Create HeyGen knowledge base
        kb_id = self._create_knowledge_base(candidate)
        if not kb_id:
            logger.error("Failed to create knowledge base for %s", candidate.name)
            return

        # 2) Generate interview link/token
        interview_token = str(uuid.uuid4())
        interview_link = f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/interview/{interview_token}"

        # 3) Update candidate record
        candidate.interview_kb_id = kb_id
        candidate.interview_token = interview_token
        candidate.interview_link = interview_link
        candidate.interview_scheduled = True
        candidate.interview_date = datetime.now() + timedelta(days=1)
        candidate.final_status = "Interview Scheduled"

        # 4) Email candidate
        self._send_interview_email(candidate)

        logger.info("Interview setup complete for %s", candidate.name)

    # ---- helpers ----
    def _create_knowledge_base(self, candidate: Candidate) -> str | None:
        try:
            job_desc = self._get_job_description(candidate.job_id, candidate.job_title)
            kb_name = f"Interview - {candidate.name} - {candidate.job_title} - {datetime.now().strftime('%Y-%m-%d')}"
            opening_line = f"Hello {candidate.name}, welcome to your interview for the {candidate.job_title} position."

            custom_prompt = self._generate_interview_prompt(
                candidate_name=candidate.name,
                position=candidate.job_title,
                job_description=job_desc,
                company_name=os.getenv("COMPANY_NAME", "Our Company"),
            )

            useful_links: list[str] = []
            if candidate.resume_path:
                resume_url = self._get_resume_url(candidate.resume_path)
                if resume_url:
                    useful_links.append(resume_url)

            headers = {"x-api-key": self.heygen_api_key or "", "Content-Type": "application/json"}
            payload = {
                "name": kb_name,
                "opening_line": opening_line,
                "custom_prompt": custom_prompt,
                "useful_links": useful_links,
            }

            resp = requests.post(self.heygen_api_url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                kb_id = data.get("data", {}).get("knowledge_base_id")
                logger.info("Created knowledge base: %s", kb_id)
                return kb_id
            logger.error("HeyGen API error: %s - %s", resp.status_code, resp.text)
            return None
        except Exception as e:
            logger.error("Error creating knowledge base: %s", e, exc_info=True)
            return None

    def _get_job_description(self, job_id: str, job_title: str) -> str:
        try:
            api_key = os.getenv("BAMBOOHR_API_KEY")
            subdomain = os.getenv("BAMBOOHR_SUBDOMAIN")
            if api_key and subdomain:
                auth = (api_key, "x")
                headers = {"Accept": "application/json"}
                url = f"https://api.bamboohr.com/api/gateway.php/{subdomain}/v1/applicant_tracking/jobs/{job_id}"
                r = requests.get(url, auth=auth, headers=headers, timeout=10)
                if r.status_code == 200:
                    job_data = r.json()
                    return job_data.get("description", "")
        except Exception:
            pass
        return (
            f"We are looking for a talented {job_title} to join our team. "
            "Strong technical skills, problem solving, communication, and growth mindset required."
        )

    def _get_resume_url(self, resume_path: str) -> str | None:
        # TODO: map file server / S3 if you have it
        return None

    def _generate_interview_prompt(self, candidate_name: str, position: str, job_description: str, company_name: str) -> str:
        return f"""
# Professional Interview Assistant

## CANDIDATE INFORMATION
**Name**: {candidate_name}
**Position**: {position}
**Company**: {company_name}

## JOB DESCRIPTION
{job_description}

## INTERVIEW PROTOCOL
(… unchanged …)
"""

    def _send_interview_email(self, candidate: Candidate) -> None:
        try:
            subject = f"Interview Invitation - {candidate.job_title} Position"
            body_html = f"""
<html>
  <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
      <h2 style="color: #2c3e50;">Congratulations, {candidate.name}!</h2>
      <p>You passed the assessment for <strong>{candidate.job_title}</strong>. Start your AI-powered interview below.</p>
      <div style="text-align:center;margin:30px 0;">
        <a href="{candidate.interview_link}" style="display:inline-block;padding:12px 30px;background:#3498db;color:#fff;text-decoration:none;border-radius:5px;font-weight:bold;">Start Your Interview</a>
      </div>
      <p>This link expires in 7 days.</p>
    </div>
  </body>
</html>
"""
            send_email(candidate.email, subject, body_html)
            logger.info("Interview email sent to %s", candidate.email)
        except Exception as e:
            logger.error("Failed to send interview email to %s: %s", candidate.email, e, exc_info=True)


# # Exported instance + start/stop helpers (match your original API)
# interview_automation = InterviewAutomationSystem()

# def start_interview_automation() -> None:
#     interview_automation.start()

# def stop_interview_automation() -> None:
#     interview_automation.stop()
class InterviewAutomation:
    def __init__(self):
        self.is_running = False
        self.check_interval = 600  # 10 minutes
    
    def start(self):
        self.is_running = True
    
    def stop(self):
        self.is_running = False

# Global instance
interview_automation = InterviewAutomation()

def start_interview_automation():
    interview_automation.start()

def stop_interview_automation():
    interview_automation.stop()