# assessment_automation_system.py
"""
Assessment Automation System for TalentFlow
Works WITH your existing automation.py to complete the full pipeline:
1. This system: Fetches assessment results → Evaluates scores
2. Your automation.py: Schedules interviews → Sends emails
"""

import os
import time
import logging
import threading
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import requests
from sqlalchemy import and_, or_, func

# Import your existing database models
from app.models.db import Candidate, AssessmentResult, SessionLocal, EmailLog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
)
logger = logging.getLogger(__name__)


class AssessmentAutomationSystem:
    """
    Assessment Results Automation System
    Fetches results from Testlify/Criteria and triggers your existing interview scheduling
    """
    
    def __init__(self):
        self.is_running = False
        self.check_interval = 600  # Check every 10 minutes
        self.thread = None
        self.pass_threshold = float(os.getenv('ASSESSMENT_MIN_SCORE', '75'))
        
        # API endpoint for your existing automation.py
        self.base_url = os.getenv('API_BASE_URL', 'http://localhost:5000')
        
        # Track processing
        self.stats = {
            'last_run': None,
            'testlify_processed': 0,
            'criteria_processed': 0,
            'interviews_triggered': 0,
            'errors': []
        }
        
        logger.info(f"Assessment Automation System initialized (pass threshold: {self.pass_threshold}%)")
    
    def start(self) -> None:
        """Start the assessment automation"""
        if self.is_running:
            logger.warning("Assessment automation already running")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("✅ Assessment Automation System started")
    
    def stop(self) -> None:
        """Stop the assessment automation"""
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("🛑 Assessment automation stopped")
    
    def _run_loop(self) -> None:
        """Main automation loop"""
        while self.is_running:
            try:
                logger.info("=" * 70)
                logger.info("🔄 ASSESSMENT AUTOMATION CYCLE STARTING...")
                logger.info("=" * 70)
                
                self._process_all_assessments()
                
                logger.info("=" * 70)
                logger.info("✅ ASSESSMENT CYCLE COMPLETE")
                logger.info(f"   Next check in {self.check_interval} seconds...")
                logger.info("=" * 70)
                
            except Exception as e:
                logger.error(f"❌ Error in automation loop: {e}", exc_info=True)
                self.stats['errors'].append({
                    'time': datetime.now().isoformat(),
                    'error': str(e)
                })
            
            time.sleep(self.check_interval)
    
    def _process_all_assessments(self) -> None:
        """Process all pending assessments"""
        self.stats['last_run'] = datetime.now().isoformat()
        
        session = SessionLocal()
        try:
            # Reset counters
            self.stats['testlify_processed'] = 0
            self.stats['criteria_processed'] = 0
            self.stats['interviews_triggered'] = 0
            
            # Step 1: Process Testlify
            logger.info("\n📊 STEP 1: Processing Testlify Assessments...")
            testlify_results = self._process_testlify(session)
            
            # Step 2: Process Criteria
            logger.info("\n📊 STEP 2: Processing Criteria Assessments...")
            criteria_results = self._process_criteria(session)
            
            # Step 3: Trigger interviews for qualified candidates
            logger.info("\n🎯 STEP 3: Triggering Interview Scheduling...")
            self._trigger_interview_scheduling(session)
            
            # Commit all changes
            session.commit()
            
            # Log summary
            self._log_summary()
            
        except Exception as e:
            logger.error(f"Error in process_all_assessments: {e}")
            session.rollback()
        finally:
            session.close()
    
    # ===================== TESTLIFY PROCESSING =====================
    
    def _process_testlify(self, session) -> int:
        """Process Testlify assessment results"""
        try:
            # Find pending Testlify assessments
            pending = session.query(Candidate).filter(
                and_(
                    Candidate.exam_link_sent == True,
                    Candidate.exam_completed == False,
                    or_(
                        Candidate.assessment_invite_link.contains('testlify'),
                        Candidate.assessment_id.isnot(None)
                    )
                )
            ).all()
            
            if not pending:
                logger.info("   No pending Testlify assessments")
                return 0
            
            # Get unique assessment names
            assessment_names = list(set([c.job_title for c in pending if c.job_title]))
            logger.info(f"   Found {len(assessment_names)} Testlify assessments to check")
            
            processed = 0
            
            for assessment_name in assessment_names:
                logger.info(f"   🔍 Checking: {assessment_name}")
                
                # Run your existing Testlify scraper
                results = self._run_testlify_scraper(assessment_name)
                
                if results:
                    logger.info(f"      Found {len(results)} results")
                    
                    for result in results:
                        email = result.get('email')
                        if not email:
                            continue
                        
                        candidate = session.query(Candidate).filter_by(email=email).first()
                        if not candidate or candidate.exam_completed:
                            continue
                        
                        # Update candidate with results
                        percentage = result.get('percentage', 0)
                        if percentage:
                            candidate.exam_completed = True
                            candidate.exam_completed_date = datetime.now()
                            candidate.exam_percentage = float(percentage)
                            candidate.exam_score = int(percentage)
                            
                            # Mark status
                            if percentage >= self.pass_threshold:
                                candidate.status = "Assessment Passed"
                                candidate.final_status = "Ready for Interview"
                                logger.info(f"      ✅ {email}: PASSED with {percentage}%")
                            else:
                                candidate.status = "Assessment Failed"
                                candidate.final_status = "Rejected - Low Score"
                                logger.info(f"      ❌ {email}: FAILED with {percentage}%")
                            
                            processed += 1
                            self.stats['testlify_processed'] += 1
                            
                            # Store in AssessmentResult table
                            self._store_assessment_result(
                                session, candidate, result, 'testlify'
                            )
            
            return processed
            
        except Exception as e:
            logger.error(f"Error processing Testlify: {e}")
            return 0
    
    def _run_testlify_scraper(self, assessment_name: str) -> List[Dict]:
        """Run your existing Testlify scraper"""
        try:
            from testlify_results_scraper import scrape_assessment_results_by_name
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                results = loop.run_until_complete(
                    scrape_assessment_results_by_name(assessment_name)
                )
                return results
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"Failed to run Testlify scraper: {e}")
            return []
    
    # ===================== CRITERIA PROCESSING =====================
    
    def _process_criteria(self, session) -> int:
        """Process Criteria assessment results"""
        try:
            # Find pending Criteria assessments
            pending = session.query(Candidate).filter(
                and_(
                    Candidate.exam_link_sent == True,
                    Candidate.exam_completed == False,
                    Candidate.assessment_invite_link.contains('criteria')
                )
            ).all()
            
            if not pending:
                logger.info("   No pending Criteria assessments")
                return 0
            
            # Get unique job titles
            job_titles = list(set([c.job_title for c in pending if c.job_title]))
            logger.info(f"   Found {len(job_titles)} Criteria assessments to check")
            
            processed = 0
            
            for job_title in job_titles:
                logger.info(f"   🔍 Checking: {job_title}")
                
                # Run your existing Criteria scraper
                results = self._run_criteria_scraper(job_title)
                
                if results:
                    logger.info(f"      Found {len(results)} results")
                    
                    for result in results:
                        email = result.get('email')
                        if not email:
                            continue
                        
                        candidate = session.query(Candidate).filter_by(email=email).first()
                        if not candidate or candidate.exam_completed:
                            continue
                        
                        # Extract score
                        score = result.get('talent_signal') or result.get('overall_score') or 0
                        if isinstance(score, str):
                            score = float(score.replace('%', ''))
                        percentage = float(score)
                        
                        if percentage > 0:
                            candidate.exam_completed = True
                            candidate.exam_completed_date = datetime.now()
                            candidate.exam_percentage = percentage
                            candidate.exam_score = int(percentage)
                            
                            # Mark status
                            if percentage >= self.pass_threshold:
                                candidate.status = "Assessment Passed"
                                candidate.final_status = "Ready for Interview"
                                logger.info(f"      ✅ {email}: PASSED with {percentage}%")
                            else:
                                candidate.status = "Assessment Failed"
                                candidate.final_status = "Rejected - Low Score"
                                logger.info(f"      ❌ {email}: FAILED with {percentage}%")
                            
                            processed += 1
                            self.stats['criteria_processed'] += 1
                            
                            # Store in AssessmentResult table
                            self._store_assessment_result(
                                session, candidate, result, 'criteria'
                            )
            
            return processed
            
        except Exception as e:
            logger.error(f"Error processing Criteria: {e}")
            return 0
    
    def _run_criteria_scraper(self, job_title: str) -> List[Dict]:
        """Run your existing Criteria scraper"""
        try:
            process = subprocess.Popen(
                [sys.executable, "Criteria_score.py", "--job", job_title, "--format", "json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(timeout=300)
            
            if process.returncode != 0:
                logger.error(f"Criteria scraper failed: {stderr}")
                return []
            
            # Find output file
            output_dir = Path("criteria_scores")
            json_files = list(output_dir.glob(f"*{job_title.replace(' ', '_')}*.json"))
            
            if not json_files:
                return []
            
            latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
            
            with open(latest_file, 'r') as f:
                data = json.load(f)
                return data.get('candidates', [])
                
        except Exception as e:
            logger.error(f"Failed to run Criteria scraper: {e}")
            return []
    
    # ===================== INTERVIEW SCHEDULING =====================
    
    def _trigger_interview_scheduling(self, session) -> None:
        """Trigger interview scheduling for qualified candidates using your existing automation.py"""
        try:
            # Find candidates ready for interview
            qualified = session.query(Candidate).filter(
                and_(
                    Candidate.exam_completed == True,
                    Candidate.exam_percentage >= self.pass_threshold,
                    Candidate.interview_scheduled == False
                )
            ).all()
            
            if not qualified:
                logger.info("   No qualified candidates pending interview")
                return
            
            logger.info(f"   Found {len(qualified)} qualified candidates")
            
            for candidate in qualified:
                try:
                    logger.info(f"   📅 Scheduling interview for {candidate.name} ({candidate.email})")
                    
                    # Call YOUR EXISTING schedule-interview endpoint
                    response = requests.post(
                        f"{self.base_url}/api/schedule-interview",
                        json={
                            'candidate_id': candidate.id,
                            'email': candidate.email,
                            'date': (datetime.now() + timedelta(days=2)).isoformat(),
                            'time_slot': '10:00 AM - 11:00 AM'
                        },
                        timeout=30
                    )
                    
                    if response.ok:
                        data = response.json()
                        if data.get('success'):
                            logger.info(f"      ✅ Interview scheduled!")
                            logger.info(f"         Link: {data.get('interview_link')}")
                            logger.info(f"         KB ID: {data.get('knowledge_base_id')}")
                            self.stats['interviews_triggered'] += 1
                        else:
                            logger.error(f"      ❌ Failed: {data.get('message')}")
                    else:
                        logger.error(f"      ❌ API error: {response.status_code}")
                        
                except Exception as e:
                    logger.error(f"   Failed to schedule for {candidate.email}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error triggering interviews: {e}")
    
    def _store_assessment_result(self, session, candidate, result, provider):
        """Store assessment result in database"""
        try:
            assessment_result = AssessmentResult(
                assessment_name=candidate.job_title,
                candidate_name=candidate.name,
                candidate_email=candidate.email,
                score=candidate.exam_percentage,
                status='completed',
                provider=provider,
                raw_data=result,
                created_at=datetime.now()
            )
            session.add(assessment_result)
        except Exception as e:
            logger.error(f"Error storing assessment result: {e}")
    
    def _log_summary(self):
        """Log processing summary"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 PROCESSING SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Testlify Processed: {self.stats['testlify_processed']}")
        logger.info(f"Criteria Processed: {self.stats['criteria_processed']}")
        logger.info(f"Interviews Triggered: {self.stats['interviews_triggered']}")
        
        if self.stats['errors']:
            logger.warning(f"Errors encountered: {len(self.stats['errors'])}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current system status"""
        session = SessionLocal()
        try:
            return {
                'is_running': self.is_running,
                'pass_threshold': self.pass_threshold,
                'check_interval': self.check_interval,
                'last_run': self.stats['last_run'],
                'statistics': {
                    'testlify_processed': self.stats['testlify_processed'],
                    'criteria_processed': self.stats['criteria_processed'],
                    'interviews_triggered': self.stats['interviews_triggered']
                },
                'pending': {
                    'testlify': session.query(Candidate).filter(
                        and_(
                            Candidate.exam_link_sent == True,
                            Candidate.exam_completed == False,
                            Candidate.assessment_invite_link.contains('testlify')
                        )
                    ).count(),
                    'criteria': session.query(Candidate).filter(
                        and_(
                            Candidate.exam_link_sent == True,
                            Candidate.exam_completed == False,
                            Candidate.assessment_invite_link.contains('criteria')
                        )
                    ).count(),
                    'ready_for_interview': session.query(Candidate).filter(
                        and_(
                            Candidate.exam_completed == True,
                            Candidate.exam_percentage >= self.pass_threshold,
                            Candidate.interview_scheduled == False
                        )
                    ).count()
                }
            }
        finally:
            session.close()


# ===================== GLOBAL INSTANCE =====================

assessment_automation = AssessmentAutomationSystem()

def start_assessment_automation():
    """Start the assessment automation system"""
    assessment_automation.start()

def stop_assessment_automation():
    """Stop the assessment automation system"""
    assessment_automation.stop()

def get_assessment_status():
    """Get assessment automation status"""
    return assessment_automation.get_status()


# ===================== CLI INTERFACE =====================

if __name__ == "__main__":
    print("=" * 70)
    print("TALENTFLOW ASSESSMENT AUTOMATION SYSTEM")
    print("=" * 70)
    print("\nThis system works WITH your existing automation.py:")
    print("1. Fetches assessment results (Testlify & Criteria)")
    print("2. Evaluates scores (≥75% pass)")
    print("3. Triggers YOUR schedule-interview endpoint")
    print("4. Your automation.py handles the rest!")
    print("=" * 70)
    
    choice = input("\nOptions:\n1. Start automation\n2. Check status\n3. Manual run\n\nChoice: ").strip()
    
    if choice == "1":
        print("\n🚀 Starting assessment automation...")
        start_assessment_automation()
        print("✅ System running! Press Ctrl+C to stop.")
        
        try:
            while True:
                time.sleep(60)
                status = get_assessment_status()
                print(f"\n⏰ Status: Last run: {status['last_run']}")
                print(f"   Pending: Testlify={status['pending']['testlify']}, Criteria={status['pending']['criteria']}")
        except KeyboardInterrupt:
            print("\n🛑 Stopping...")
            stop_assessment_automation()
            
    elif choice == "2":
        status = get_assessment_status()
        print("\n📊 SYSTEM STATUS")
        print(f"Running: {status['is_running']}")
        print(f"Last Run: {status['last_run']}")
        print(f"\nPending:")
        for key, value in status['pending'].items():
            print(f"  {key}: {value}")
            
    elif choice == "3":
        print("\n🔄 Running manual assessment check...")
        assessment_automation._process_all_assessments()
        print("✅ Complete!")