# app/services/interview_analysis_service_production.py
"""
Production-ready interview analysis service for TalentFlow.

Adaptations for the modular app:
- Uses `from app.models.db import SessionLocal, Candidate`
- Accepts cache from `app.extensions.cache`
- Writes JSON fields to `interview_ai_strengths` / `interview_ai_weaknesses`
  to match what your routes read.
"""

import json
import time
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import queue
import os
import re

from app.models.db import SessionLocal, Candidate
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import cache as shared_cache  # centralized cache

logger = logging.getLogger(__name__)

class AnalysisStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID = "invalid"
    RETRY = "retry"

@dataclass
class AnalysisTask:
    candidate_id: int
    priority: int = 5
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

class ProductionInterviewAnalysisService:
    """Production interview analysis service with strict validation & retries."""

    def __init__(self, cache=None, max_workers: int = 4):
        self.cache = cache
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.analysis_queue = queue.PriorityQueue()
        self.is_running = False
        self.monitor_thread = None
        self.worker_threads = []
        self.failed_analyses: Dict[int, Dict[str, Any]] = {}
        self.completed_analyses: set[int] = set()
        self._lock = threading.Lock()
        
        self.config = {
            'monitor_interval': int(os.getenv('ANALYSIS_MONITOR_INTERVAL', '30')),
            'max_retries': int(os.getenv('ANALYSIS_MAX_RETRIES', '3')),
            'retry_delay': int(os.getenv('ANALYSIS_RETRY_DELAY', '300')),
            'stale_threshold': int(os.getenv('ANALYSIS_STALE_THRESHOLD', '3600')),
            'batch_size': int(os.getenv('ANALYSIS_BATCH_SIZE', '10')),
            'min_questions': int(os.getenv('MIN_INTERVIEW_QUESTIONS', '5')),
            'min_valid_answers': int(os.getenv('MIN_VALID_ANSWERS', '5')),
            'min_answer_length': int(os.getenv('MIN_ANSWER_LENGTH', '30')),
            'min_word_count': int(os.getenv('MIN_WORD_COUNT', '5')),
            'validity_threshold': float(os.getenv('VALIDITY_THRESHOLD', '0.7')),
        }
        
        # Patterns that mark invalid/test/system answers
        self.invalid_patterns = [
            'INIT_INTERVIEW', 'TEST', 'TEST_RESPONSE', 'undefined', 'null',
            '[object Object]', 'lorem ipsum', 'START_INTERVIEW', 'END_INTERVIEW',
            'NEXT_QUESTION', 'SKIP', 'test answer', 'sample response',
            'No answer provided',
        ]
        
        self.technical_keywords = [
            'implement', 'develop', 'design', 'architecture', 'algorithm',
            'database', 'api', 'framework', 'optimize', 'scale', 'debug',
            'testing', 'deployment', 'version control', 'git', 'agile',
            'code', 'programming', 'software', 'function', 'class', 'module',
            'performance', 'security', 'authentication', 'integration',
        ]
        self.soft_skill_keywords = [
            'team', 'collaborate', 'communicate', 'lead', 'manage',
            'problem', 'solution', 'challenge', 'learn', 'adapt',
            'deadline', 'priority', 'stakeholder', 'conflict', 'feedback',
            'mentor', 'present', 'document', 'plan', 'organize',
        ]
    
    # ---- lifecycle ----
    def start(self):
        if self.is_running:
            logger.warning("Analysis service already running")
            return
        self.is_running = True

        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, name="AnalysisMonitor", daemon=True
        )
        self.monitor_thread.start()
        
        for i in range(2):
            worker = threading.Thread(
                target=self._worker_loop, name=f"AnalysisWorker-{i}", daemon=True
            )
            worker.start()
            self.worker_threads.append(worker)
        logger.info("Interview Analysis Service started with %d workers", len(self.worker_threads))
    
    def stop(self):
        logger.info("Stopping Interview Analysis Service...")
        self.is_running = False
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        for worker in self.worker_threads:
            worker.join(timeout=5)
        self.executor.shutdown(wait=True)
        logger.info("Interview Analysis Service stopped")
    
    # ---- loops ----
    def _monitor_loop(self):
        while self.is_running:
            try:
                self._check_pending_interviews()
                self._check_stale_analyses()
                self._retry_failed_analyses()
            except Exception as e:
                logger.error("Monitor loop error: %s", e, exc_info=True)
            time.sleep(self.config['monitor_interval'])
    
    def _worker_loop(self):
        while self.is_running:
            try:
                priority, task = self.analysis_queue.get(timeout=5)
                if task:
                    self._process_analysis_task(task)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("Worker loop error: %s", e, exc_info=True)
    
    # ---- queue feeders ----
    def _check_pending_interviews(self):
        session = SessionLocal()
        try:
            candidates = session.query(Candidate).filter(
                Candidate.interview_completed_at.isnot(None),
                (Candidate.interview_ai_analysis_status.is_(None)) |
                (Candidate.interview_ai_analysis_status == AnalysisStatus.PENDING.value),
                Candidate.interview_auto_score_triggered == False,
            ).limit(self.config['batch_size']).all()
            
            for candidate in candidates:
                if candidate.id in self.completed_analyses:
                    continue
                candidate.interview_auto_score_triggered = True
                session.commit()
                task = AnalysisTask(candidate_id=candidate.id, priority=self._calculate_priority(candidate))
                self.analysis_queue.put((task.priority, task))
                logger.info("Queued analysis for candidate %s (%s)", candidate.id, candidate.name)
        except SQLAlchemyError as e:
            logger.error("DB error in pending check: %s", e)
            session.rollback()
        finally:
            session.close()
    
    def _check_stale_analyses(self):
        session = SessionLocal()
        try:
            stale_time = datetime.now() - timedelta(seconds=self.config['stale_threshold'])
            stale_candidates = session.query(Candidate).filter(
                Candidate.interview_ai_analysis_status == AnalysisStatus.PROCESSING.value,
                Candidate.interview_analysis_started_at < stale_time,
            ).all()
            for c in stale_candidates:
                logger.warning("Stale analysis for candidate %s", c.id)
                c.interview_ai_analysis_status = AnalysisStatus.RETRY.value
                c.interview_auto_score_triggered = False
                session.commit()
        except SQLAlchemyError as e:
            logger.error("DB error in stale check: %s", e)
        finally:
            session.close()
    
    def _retry_failed_analyses(self):
        now = datetime.now()
        with self._lock:
            retry_ids = [
                cid for cid, info in list(self.failed_analyses.items())
                if now - info['failed_at'] > timedelta(seconds=self.config['retry_delay'])
                and info['retry_count'] < self.config['max_retries']
            ]
            for cid in retry_ids:
                del self.failed_analyses[cid]
        for cid in retry_ids:
            task = AnalysisTask(candidate_id=cid, priority=1)
            self.analysis_queue.put((task.priority, task))
            logger.info("Retrying analysis for candidate %s", cid)
    
    # ---- processing ----
    def _calculate_priority(self, candidate) -> int:
        priority = 5
        if candidate.interview_completed_at:
            hours_ago = (datetime.now() - candidate.interview_completed_at).total_seconds() / 3600
            if hours_ago < 1:
                priority = 1
            elif hours_ago < 6:
                priority = 3
        return priority
    
    def _process_analysis_task(self, task: AnalysisTask):
        logger.info("Processing analysis for candidate %s", task.candidate_id)
        session = SessionLocal()
        candidate = None
        try:
            candidate = session.query(Candidate).filter_by(id=task.candidate_id).first()
            if not candidate:
                logger.error("Candidate %s not found", task.candidate_id)
                return
            candidate.interview_ai_analysis_status = AnalysisStatus.PROCESSING.value
            candidate.interview_analysis_started_at = datetime.now()
            session.commit()
            
            analysis_result = self._perform_analysis(candidate)
            if analysis_result:
                self._save_analysis_results(candidate, analysis_result, session)
                with self._lock:
                    self.completed_analyses.add(task.candidate_id)
                self._send_realtime_update(task.candidate_id, analysis_result)
                logger.info("Analysis completed for candidate %s: %s%%",
                            task.candidate_id, analysis_result['overall_score'])
            else:
                raise RuntimeError("Analysis returned no results")
        except Exception as e:
            logger.error("Analysis failed for candidate %s: %s", task.candidate_id, e, exc_info=True)
            if candidate:
                candidate.interview_ai_analysis_status = AnalysisStatus.FAILED.value
                session.commit()
            with self._lock:
                self.failed_analyses[task.candidate_id] = {
                    'failed_at': datetime.now(),
                    'retry_count': task.retry_count,
                    'error': str(e),
                }
        finally:
            session.close()
    
    # ---- validation & analysis ----
    def _validate_interview_responses(self, qa_pairs: List[Dict]) -> Tuple[bool, str]:
        if not qa_pairs:
            return False, "No Q&A data available"
        if len(qa_pairs) < self.config['min_questions']:
            return False, f"Interview has only {len(qa_pairs)} questions (minimum: {self.config['min_questions']})"
        
        valid, invalid = 0, []
        for i, qa in enumerate(qa_pairs, 1):
            answer = (qa.get('answer') or '').strip()
            if not answer or answer == "No answer provided":
                invalid.append(f"Q{i}: No answer provided"); continue
            if len(answer) < self.config['min_answer_length']:
                invalid.append(f"Q{i}: Answer too short ({len(answer)} chars)"); continue
            lower = answer.lower()
            if any(p.lower() in lower for p in self.invalid_patterns):
                invalid.append(f"Q{i}: Contains invalid pattern"); continue
            if not any(c.isalpha() for c in answer):
                invalid.append(f"Q{i}: No alphabetic content"); continue
            if len(answer.split()) < self.config['min_word_count']:
                invalid.append(f"Q{i}: Too few words"); continue
            if len(set(lower.split())) < 3:
                invalid.append(f"Q{i}: Repetitive content"); continue
            valid += 1
        
        rate = valid / len(qa_pairs)
        if valid < self.config['min_valid_answers']:
            return False, f"{valid} valid answers (< {self.config['min_valid_answers']})"
        if rate < self.config['validity_threshold']:
            return False, f"Validity rate {rate:.1%} below threshold {self.config['validity_threshold']:.0%}"
        return True, f"{valid}/{len(qa_pairs)} valid"
    
    def _perform_analysis(self, candidate) -> Optional[Dict[str, Any]]:
        try:
            qa_pairs = self._parse_qa_data_safely(candidate)
            is_valid, reason = self._validate_interview_responses(qa_pairs)
            if not is_valid:
                return self._generate_invalid_interview_result(reason, qa_pairs)
            if self._has_ai_capability():
                try:
                    return self._analyze_with_ai_production(qa_pairs, candidate)
                except Exception as e:
                    logger.warning("AI analysis failed, using rule-based: %s", e)
            return self._analyze_with_rules_production(qa_pairs, candidate)
        except Exception as e:
            logger.error("Analysis error: %s", e, exc_info=True)
            return self._generate_error_result(str(e))
    
    def _parse_qa_data_safely(self, candidate) -> List[Dict]:
        # Prefer single field if present
        if candidate.interview_qa_pairs:
            try:
                data = json.loads(candidate.interview_qa_pairs)
                if isinstance(data, list) and data:
                    return data
            except json.JSONDecodeError:
                logger.warning("Failed to parse interview_qa_pairs for %s", candidate.id)
        # Fall back to separate arrays
        qa_pairs: List[Dict] = []
        try:
            questions = json.loads(candidate.interview_questions_asked or '[]')
            answers = json.loads(candidate.interview_answers_given or '[]')
            for i, q in enumerate(questions):
                qa = {
                    'question': q.get('text', '') if isinstance(q, dict) else str(q),
                    'answer': '',
                    'timestamp': q.get('timestamp') if isinstance(q, dict) else None,
                    'order': i + 1,
                }
                if i < len(answers):
                    a = answers[i]
                    qa['answer'] = a.get('text', '') if isinstance(a, dict) else str(a)
                qa_pairs.append(qa)
        except Exception as e:
            logger.error("Failed parsing Q/A arrays: %s", e)
        return qa_pairs
    
    def _has_ai_capability(self) -> bool:
        return bool(os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY'))
    
    # --- AI path (optional; requires OPENAI_API_KEY) ---
    def _analyze_with_ai_production(self, qa_pairs: List[Dict], candidate) -> Dict[str, Any]:
        import openai
        openai.api_key = os.getenv('OPENAI_API_KEY')
        qa_text = self._format_qa_for_ai(qa_pairs)
        prompt = self._create_ai_prompt(qa_text, candidate)

        # NOTE: If you're on OpenAI's Chat Completions, adjust accordingly.
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
            timeout=30,
        )
        content = resp.choices[0].message.content
        parsed = self._parse_ai_response(content)
        if not parsed:
            raise RuntimeError("AI response parsing failed")
        parsed['method'] = 'ai-gpt3.5'
        parsed['confidence'] = 0.95
        return parsed
    
    # --- Rule-based path ---
    def _analyze_with_rules_production(self, qa_pairs: List[Dict], candidate) -> Dict[str, Any]:
        metrics = self._calculate_interview_metrics(qa_pairs)
        scores = self._calculate_scores_from_metrics(metrics, candidate)
        insights = self._generate_insights_from_metrics(metrics, scores)
        feedback = self._generate_comprehensive_feedback(metrics, scores, insights, candidate)
        return {
            'technical_score': scores['technical'],
            'communication_score': scores['communication'],
            'problem_solving_score': scores['problem_solving'],
            'cultural_fit_score': scores['cultural_fit'],
            'overall_score': scores['overall'],
            'strengths': insights['strengths'],
            'weaknesses': insights['weaknesses'],
            'recommendations': insights['recommendations'],
            'feedback': feedback,
            'confidence': 0.75,
            'method': 'rule-based-v2',
        }
    
    def _calculate_interview_metrics(self, qa_pairs: List[Dict]) -> Dict[str, Any]:
        total = len(qa_pairs)
        answered = sum(1 for qa in qa_pairs if qa.get('answer'))
        lengths = [len(qa.get('answer', '')) for qa in qa_pairs if qa.get('answer')]
        avg_len = sum(lengths) / len(lengths) if lengths else 0
        all_answers = ' '.join(qa.get('answer', '') for qa in qa_pairs).lower()
        tech_kw = sum(1 for kw in self.technical_keywords if kw in all_answers)
        soft_kw = sum(1 for kw in self.soft_skill_keywords if kw in all_answers)

        tech_q = 0
        beh_q = 0
        for qa in qa_pairs:
            if qa.get('answer'):
                ql = qa.get('question', '').lower()
                if any(k in ql for k in ['technical', 'code', 'implement', 'design']):
                    tech_q += 1
                elif any(k in ql for k in ['team', 'challenge', 'situation', 'describe']):
                    beh_q += 1

        return {
            'total_questions': total,
            'answered_questions': answered,
            'completion_rate': (answered / total * 100) if total > 0 else 0,
            'avg_answer_length': avg_len,
            'min_answer_length': min(lengths) if lengths else 0,
            'max_answer_length': max(lengths) if lengths else 0,
            'technical_keyword_count': tech_kw,
            'soft_keyword_count': soft_kw,
            'technical_questions_answered': tech_q,
            'behavioral_questions_answered': beh_q,
            'answer_quality_score': self._calculate_answer_quality_score(qa_pairs),
        }
    
    def _calculate_answer_quality_score(self, qa_pairs: List[Dict]) -> float:
        if not qa_pairs:
            return 0.0
        scores = []
        for qa in qa_pairs:
            ans = qa.get('answer', '')
            if not ans:
                scores.append(0); continue
            score = 50
            length = len(ans)
            if length > 200: score += 20
            elif length > 100: score += 10
            elif length < 30: score -= 20
            sentences = ans.count('.') + ans.count('!') + ans.count('?')
            if sentences > 3: score += 10
            elif sentences > 1: score += 5
            if any(ch.isdigit() for ch in ans): score += 5
            if ans.count(',') > 2: score += 5
            scores.append(min(100, max(0, score)))
        return sum(scores) / len(scores) if scores else 0.0
    
    def _calculate_scores_from_metrics(self, m: Dict, candidate) -> Dict[str, float]:
        t = 30 + min(30, m['completion_rate'] * 0.3) + min(20, m['technical_keyword_count'] * 2) + min(20, m['answer_quality_score'] * 0.2)
        c = 30 + min(30, m['completion_rate'] * 0.3) + min(25, (m['avg_answer_length'] / 8)) + min(15, m['soft_keyword_count'] * 2)
        p = 30 + min(30, m['behavioral_questions_answered'] * 6) + min(25, m['answer_quality_score'] * 0.25) + min(15, m['completion_rate'] * 0.15)
        f = 30 + min(30, m['completion_rate'] * 0.3) + min(25, m['soft_keyword_count'] * 3) + min(15, ((m['answered_questions'] / m['total_questions']) * 15) if m['total_questions'] > 0 else 0)
        scores = {
            'technical': min(100, max(0, t)),
            'communication': min(100, max(0, c)),
            'problem_solving': min(100, max(0, p)),
            'cultural_fit': min(100, max(0, f)),
        }
        scores['overall'] = scores['technical'] * 0.35 + scores['communication'] * 0.25 + scores['problem_solving'] * 0.25 + scores['cultural_fit'] * 0.15
        return scores
    
    def _generate_insights_from_metrics(self, m: Dict, s: Dict) -> Dict[str, List[str]]:
        strengths, weaknesses, recommendations = [], [], []
        if m['completion_rate'] >= 95: strengths.append("Excellent interview completion - answered all questions thoroughly")
        elif m['completion_rate'] >= 80: strengths.append("Good interview engagement with high completion rate")
        elif m['completion_rate'] < 60: weaknesses.append("Low completion rate indicates potential communication issues")
        if m['avg_answer_length'] > 150: strengths.append("Provided detailed and comprehensive responses")
        elif m['avg_answer_length'] < 50:
            weaknesses.append("Responses were too brief and lacked detail")
            recommendations.append("Encourage more detailed responses in future interviews")
        if m['technical_keyword_count'] >= 8: strengths.append("Strong technical vocabulary and domain knowledge")
        elif m['technical_keyword_count'] < 3: weaknesses.append("Limited technical terminology in responses")
        if m['soft_keyword_count'] >= 6: strengths.append("Good emphasis on teamwork and collaboration")
        elif m['soft_keyword_count'] < 2: weaknesses.append("Minimal focus on soft skills and team dynamics")
        if s['overall'] >= 75: recommendations.append("Strong candidate - proceed to next round")
        elif s['overall'] >= 60: recommendations.append("Promising candidate - consider for technical assessment")
        else: recommendations.append("May not be suitable for current role requirements")
        if s['technical'] < 60: recommendations.append("Additional technical screening recommended")
        if s['communication'] < 60: recommendations.append("Communication skills assessment needed")
        return {'strengths': strengths[:3], 'weaknesses': weaknesses[:3], 'recommendations': recommendations[:3]}
    
    def _generate_comprehensive_feedback(self, m: Dict, s: Dict, insights: Dict, candidate) -> str:
        return f"""
INTERVIEW ANALYSIS REPORT
========================
Candidate: {candidate.name}
Position: {candidate.job_title}
Date: {datetime.now().strftime('%Y-%m-%d')}

EXECUTIVE SUMMARY
-----------------
Overall Score: {s['overall']:.1f}/100
Recommendation: {'Highly Recommended' if s['overall'] >= 75 else 'Recommended' if s['overall'] >= 60 else 'Not Recommended'}

DETAILED SCORES
---------------
- Technical Skills: {s['technical']:.1f}/100
- Communication: {s['communication']:.1f}/100
- Problem Solving: {s['problem_solving']:.1f}/100
- Cultural Fit: {s['cultural_fit']:.1f}/100

INTERVIEW METRICS
-----------------
- Questions Answered: {m['answered_questions']}/{m['total_questions']}
- Completion Rate: {m['completion_rate']:.1f}%
- Average Response Length: {m['avg_answer_length']:.0f} characters
- Answer Quality Score: {m['answer_quality_score']:.1f}/100

KEY STRENGTHS
-------------
{chr(10).join(f'• {x}' for x in insights['strengths']) or '• —'}

AREAS FOR IMPROVEMENT
---------------------
{chr(10).join(f'• {x}' for x in insights['weaknesses']) or '• —'}

RECOMMENDATIONS
---------------
{chr(10).join(f'• {x}' for x in insights['recommendations']) or '• —'}
""".strip()
    
    def _generate_invalid_interview_result(self, reason: str, qa_pairs: List[Dict]) -> Dict[str, Any]:
        total = len(qa_pairs)
        answered = sum(1 for qa in qa_pairs if qa.get('answer'))
        issues = []
        for i, qa in enumerate(qa_pairs, 1):
            ans = (qa.get('answer') or '').strip()
            if not ans: issues.append(f"Q{i}: No answer")
            elif any(p in ans.upper() for p in ['INIT_INTERVIEW', 'TEST']): issues.append(f"Q{i}: Test/system response")
            elif len(ans) < 20: issues.append(f"Q{i}: Too brief ({len(ans)} chars)")
        return {
            'technical_score': 0,
            'communication_score': 0,
            'problem_solving_score': 0,
            'cultural_fit_score': 0,
            'overall_score': 0,
            'strengths': [],
            'weaknesses': [
                f'Interview validation failed: {reason}',
                f'Only {answered}/{total} questions answered',
                'Invalid or test responses detected',
            ],
            'recommendations': [
                'Schedule a new interview session',
                'Ensure candidate provides complete responses',
                'Verify interview system is working correctly',
            ],
            'feedback': f"INTERVIEW INVALID — RESCHEDULE REQUIRED\nReason: {reason}\nIssues: {', '.join(issues[:5])}",
            'confidence': 0,
            'method': 'invalid_interview',
        }
    
    def _generate_error_result(self, error_msg: str) -> Dict[str, Any]:
        return {
            'technical_score': 0,
            'communication_score': 0,
            'problem_solving_score': 0,
            'cultural_fit_score': 0,
            'overall_score': 0,
            'strengths': [],
            'weaknesses': ['Analysis could not be completed'],
            'recommendations': ['Manual review required'],
            'feedback': f'Analysis Error: {error_msg}',
            'confidence': 0,
            'method': 'error',
        }
    
    def _save_analysis_results(self, candidate, results: Dict, session):
        """Persist scores/feedback; keeps field names consistent with your routes."""
        try:
            # Scores
            candidate.interview_ai_score = results['overall_score']
            candidate.interview_ai_technical_score = results['technical_score']
            candidate.interview_ai_communication_score = results['communication_score']
            candidate.interview_ai_problem_solving_score = results['problem_solving_score']
            candidate.interview_ai_cultural_fit_score = results['cultural_fit_score']
            # Feedback/meta
            candidate.interview_ai_overall_feedback = results['feedback']
            candidate.interview_confidence_score = results['confidence']
            candidate.interview_scoring_method = results['method']
            # Store insights where your API expects them
            candidate.interview_ai_strengths = json.dumps(results.get('strengths', []))
            candidate.interview_ai_weaknesses = json.dumps(results.get('weaknesses', []))
            candidate.interview_recommendations = json.dumps(results.get('recommendations', []))
            # Status/final
            if results['method'] == 'invalid_interview':
                candidate.interview_ai_analysis_status = AnalysisStatus.INVALID.value
                candidate.interview_final_status = 'Invalid'
                candidate.final_status = 'Interview Invalid - Reschedule Required'
            else:
                candidate.interview_ai_analysis_status = AnalysisStatus.COMPLETED.value
                candidate.interview_analysis_completed_at = datetime.now()
                if results['overall_score'] >= 70:
                    candidate.interview_final_status = 'Passed'
                    candidate.final_status = 'Interview Passed - Recommended'
                elif results['overall_score'] >= 50:
                    candidate.interview_final_status = 'Review'
                    candidate.final_status = 'Interview Review Required'
                else:
                    candidate.interview_final_status = 'Failed'
                    candidate.final_status = 'Interview Failed'
            session.commit()
            logger.info("Saved analysis results for candidate %s (overall=%s)", candidate.id, results['overall_score'])
            if self.cache:
                self.cache.delete(f"candidate_{candidate.id}")
                self.cache.delete("interview_results")
        except Exception as e:
            logger.error("Error saving analysis results: %s", e)
            session.rollback()
            raise
    
    def _send_realtime_update(self, candidate_id: int, results: Dict):
        try:
            update_data = {
                'candidate_id': candidate_id,
                'status': 'analysis_complete',
                'scores': {
                    'overall': results['overall_score'],
                    'technical': results['technical_score'],
                    'communication': results['communication_score'],
                    'problem_solving': results['problem_solving_score'],
                    'cultural_fit': results['cultural_fit_score'],
                },
                'final_status': (
                    'Invalid' if results.get('method') == 'invalid_interview'
                    else ('Passed' if results['overall_score'] >= 70 else 'Failed')
                ),
                'recommendation': (results.get('recommendations') or [''])[0],
                'timestamp': datetime.now().isoformat(),
                'method': results.get('method', 'unknown'),
            }
            if self.cache:
                self.cache.set(f"interview_update_{candidate_id}", json.dumps(update_data), timeout=300)
            logger.info("Realtime update set for candidate %s", candidate_id)
        except Exception as e:
            logger.error("Realtime update error: %s", e)
    
    # --- AI helpers ---
    def _format_qa_for_ai(self, qa_pairs: List[Dict]) -> str:
        blocks = []
        for i, qa in enumerate(qa_pairs, 1):
            q = qa.get('question', 'Unknown question')
            a = qa.get('answer', 'No answer provided')
            blocks.append(f"Question {i}: {q}\nAnswer: {a}\n")
        return "\n".join(blocks)
    
    def _create_ai_prompt(self, qa_text: str, candidate) -> str:
        return f"""
Analyze this technical interview for the {candidate.job_title} position.

IMPORTANT: Score based on ACTUAL content quality. If answers are test responses, invalid, or too brief, score should be 0–30%.

CANDIDATE: {candidate.name}

INTERVIEW TRANSCRIPT:
{qa_text}

Return JSON with keys technical_skills, communication_skills, problem_solving, cultural_fit, overall_score,
plus strengths[], areas_for_improvement[], recommendations[], and feedback.
"""
    
    def _get_system_prompt(self) -> str:
        return ("You are an expert technical interviewer. Be critical with invalid/test responses. "
                "Score such interviews very low. Always return valid JSON.")
    
    def _parse_ai_response(self, content: str) -> Optional[Dict[str, Any]]:
        try:
            m = re.search(r'\{.*\}', content, re.DOTALL)
            if not m:
                return None
            data = json.loads(m.group())
            required = ['technical_skills', 'communication_skills', 'problem_solving', 'cultural_fit', 'overall_score']
            if not all(k in data for k in required):
                return None
            return {
                'technical_score': float(data.get('technical_skills', 0)),
                'communication_score': float(data.get('communication_skills', 0)),
                'problem_solving_score': float(data.get('problem_solving', 0)),
                'cultural_fit_score': float(data.get('cultural_fit', 0)),
                'overall_score': float(data.get('overall_score', 0)),
                'strengths': (data.get('strengths') or [])[:3],
                'weaknesses': (data.get('areas_for_improvement') or [])[:3],
                'recommendations': (data.get('recommendations') or [])[:3],
                'feedback': data.get('feedback', 'No detailed feedback provided'),
            }
        except Exception as e:
            logger.error("Failed to parse AI response: %s", e)
            return None

    # ---- public API ----
    def analyze_single_interview(self, candidate_id: int) -> bool:
        try:
            self.analysis_queue.put((0, AnalysisTask(candidate_id=candidate_id, priority=0)))
            logger.info("Manually queued analysis for candidate %s", candidate_id)
            return True
        except Exception as e:
            logger.error("Error queuing manual analysis: %s", e)
            return False
    
    def get_service_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'is_running': self.is_running,
                'queue_size': self.analysis_queue.qsize(),
                'completed_analyses': len(self.completed_analyses),
                'failed_analyses': len(self.failed_analyses),
                'worker_threads': len([t for t in self.worker_threads if t.is_alive()]),
                'config': self.config,
            }

# Exported singleton
interview_analysis_service = ProductionInterviewAnalysisService(cache=shared_cache)
