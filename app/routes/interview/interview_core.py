import traceback
from flask import Blueprint, app, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import os, json, time, uuid, requests
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_
from app.models.db import Candidate, SessionLocal
from concurrent.futures import ThreadPoolExecutor
import atexit 
from werkzeug.utils import secure_filename
from flask_cors import cross_origin 
from app.extensions import cache 
from app.extensions import logger
from flask import Blueprint
from app.routes.interview.helpers import _append_jsonl, _ensure_dir, _ok_preflight, create_error_page, extract_experience_years, extract_projects_from_resume, extract_resume_content, extract_skills_from_resume, generate_kb_recommendations, trigger_auto_scoring
from app.routes.interview.helpers import create_expired_interview_page
from app.routes.candidates import get_cached_candidates
from app.routes.interview.helpers import completion_handler
from app.services.interview_analysis_service_production import interview_analysis_service
from app.routes.interview.avatar import create_heygen_knowledge_base

try:
    from app.extensions import executor
except Exception:
    executor = None
try:
    from app.routes.shared import rate_limit
except Exception:
    def rate_limit(*args, **kwargs):
        def _d(f):
            return f
        return _d


interview_core_bp = Blueprint('interview_core', __name__)
api_bp = interview_core_bp

@interview_core_bp.route('/secure-interview/<token>', methods=['GET'])
def secure_interview_page(token):
    """Serve the interview page ONLY if interview is not completed"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return create_error_page(token, "Interview not found"), 404
        
        # BLOCK if completed
        if getattr(candidate, 'interview_completed_at', None):
            completed_time = candidate.interview_completed_at.strftime('%B %d, %Y at %I:%M %p')
            return f"""<!DOCTYPE html>
            <html>
            <head>
                <title>Interview Completed</title>
                <style>
                    body {{ 
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        margin: 0;
                    }}
                    .container {{
                        background: white;
                        padding: 3rem;
                        border-radius: 15px;
                        box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                        text-align: center;
                        max-width: 500px;
                    }}
                    h1 {{ color: #28a745; }}
                    .icon {{ font-size: 4rem; margin-bottom: 1rem; }}
                    .details {{ 
                        background: #f8f9fa;
                        padding: 1rem;
                        border-radius: 8px;
                        margin: 1rem 0;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="icon"></div>
                    <h1>Interview Already Completed</h1>
                    <div class="details">
                        <p><strong>Candidate:</strong> {candidate.name}</p>
                        <p><strong>Position:</strong> {candidate.job_title}</p>
                        <p><strong>Completed on:</strong> {completed_time}</p>
                    </div>
                    <p>Thank you for completing your interview. Your responses have been submitted for review.</p>
                    <p>The interview link cannot be used again for security reasons.</p>
                    <p style="color: #666; font-size: 0.9em; margin-top: 2rem;">
                        If you have any questions, please contact our HR department.
                    </p>
                </div>
            </body>
            </html>""", 200
        
        # BLOCK if expired
        expires_at = getattr(candidate, 'interview_expires_at', None)
        if expires_at and expires_at < datetime.now():
            return create_expired_interview_page(token), 403
        
        # NOW ADD THE NORMAL INTERVIEW PAGE CODE (from your first code)
        # This only runs if NOT completed and NOT expired
        
        is_reconnection = bool(getattr(candidate, 'interview_started_at', None))
        
        company_name = os.getenv('COMPANY_NAME', 'Our Company')
        if getattr(candidate, 'company_name', None):
            company_name = candidate.company_name
        
        job_description = getattr(candidate, 'job_description', f'Interview for {candidate.job_title} position')
        
        interview_data = {
            'token': token,
            'candidateId': candidate.id,
            'candidateName': candidate.name,
            'candidateEmail': candidate.email,
            'position': candidate.job_title,
            'company': company_name,
            # 'knowledgeBaseId': getattr(candidate, 'knowledge_base_id', None),
            'sessionId': getattr(candidate, 'interview_session_id', None),
            'status': 'active',
            'jobDescription': job_description,
            'atsScore': candidate.ats_score,
            'resumePath': candidate.resume_path,
            'isReconnection': is_reconnection,
            'previousSessionData': {
                'questionsAsked': getattr(candidate, 'interview_total_questions', 0),
                'questionsAnswered': getattr(candidate, 'interview_answered_questions', 0),
                'duration': getattr(candidate, 'interview_duration', 0)
            }
        }
        
        return create_interview_landing_page(interview_data, token), 200
        
    except Exception as e:
        logger.exception("Error in interview route")
        return create_error_page(token, str(e)), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/validate-token/<token>', methods=['GET','POST'])
def validate_interview_token(token):
    """Validate interview token - PREVENT access after completion"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"valid": False, "error": "Invalid token"}), 404
        
        # CHECK 1: If interview is already completed, DENY access
        if getattr(candidate, 'interview_completed_at', None):
            return jsonify({
                "valid": False,
                "error": "Interview already completed",
                "completed_at": candidate.interview_completed_at.isoformat(),
                "message": "This interview has been completed and cannot be accessed again"
            }), 403
        
        # CHECK 2: Check expiration (with proper getattr)
        expires_at = getattr(candidate, 'interview_expires_at', None)
        if expires_at and expires_at < datetime.now():
            return jsonify({
                "valid": False,
                "error": "Interview link has expired",
                "expired_at": expires_at.isoformat(),
                "message": "This interview link has expired. Please contact HR for assistance."
            }), 403
        
        # CHECK 3: If already started but abandoned for too long (optional)
        started_at = getattr(candidate, 'interview_started_at', None)
        if started_at:
            time_since_start = datetime.now() - started_at
            if time_since_start.total_seconds() > 7200:  # 2 hours
                # Auto-complete abandoned interviews
                candidate.interview_completed_at = datetime.now()
                candidate.interview_ai_analysis_status = 'abandoned'
                session.commit()
                
                return jsonify({
                    "valid": False,
                    "error": "Interview session timeout",
                    "message": "This interview session has timed out after 2 hours."
                }), 403
        
        # Only allow access if NOT completed and NOT expired
        session_info = {
            "valid": True,
            "candidate_name": candidate.name,
            "position": candidate.job_title,
            "interview_started": bool(started_at),
            "interview_completed": False,  # Always false here since we checked above
            "knowledge_base_id": getattr(candidate, 'knowledge_base_id', None),
            "can_continue": True,
            "questions_asked": getattr(candidate, 'interview_total_questions', 0),
            "questions_answered": getattr(candidate, 'interview_answered_questions', 0)
        }
        
        # Update last accessed time
        if request.method == 'POST':
            if hasattr(candidate, 'last_accessed'):
                candidate.last_accessed = datetime.now()
                session.commit()
        
        return jsonify(session_info), 200
        
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        return jsonify({"valid": False, "error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/get-interview/<token>', methods=['GET','POST'])
def get_interview(token):
    from datetime import timezone  # ensure timezone available here
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        if not candidate:
            return jsonify({'error': 'Interview not found'}), 404

        if request.method == 'POST':
            body = request.get_json(silent=True) or {}
            action = body.get('action')

            if action == 'start':
                candidate.interview_started_at = datetime.now(timezone.utc)
                session.commit()
                return jsonify({"success": True}), 200

            elif action == 'complete':
                candidate.interview_completed_at = datetime.now(timezone.utc)
                transcript = body.get('transcript')
                if transcript:
                    candidate.interview_transcript = transcript
                session.commit()
                return jsonify({"success": True}), 200

        # unify KB id across both possible columns
        kb = getattr(candidate, 'knowledge_base_id', None) or getattr(candidate, 'interview_kb_id', None)
        position = getattr(candidate, "job_title", None) or getattr(candidate, "position", "") or "Interview"

        data = {
            "id": getattr(candidate, "id", None),
            "token": getattr(candidate, "interview_token", None),
            "candidateId": getattr(candidate, "id", None),
            "candidateName": getattr(candidate, "name", "") or "",
            "candidateEmail": getattr(candidate, "email", "") or "",
            "position": position,
            "company": getattr(candidate, "company_name", None)
                       or getattr(candidate, "company", None)
                       or os.getenv("COMPANY_NAME", "Our Company"),
            "knowledgeBaseId": kb,
            "status": "active" if getattr(candidate, "interview_scheduled", False) else "inactive",
            "jobDescription": getattr(candidate, "job_description", None)
                              or f"Interview for {position} position",
            "resumeLink": getattr(candidate, "resume_link", None) or getattr(candidate, "resume_path", None),
            "createdAt": getattr(candidate, "interview_created_at", None).isoformat()
                         if getattr(candidate, "interview_created_at", None) else None,
        }
        return jsonify(data), 200

    except Exception as e:
        logger.error(f"Error in get_interview: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/debug-schedule-interview', methods=['POST'])
def debug_schedule_interview():
    """Debug: try to create a KB and echo responses for troubleshooting"""
    try:
        data = request.json or {}
        api_key = os.getenv('HEYGEN_API_KEY')
        if not api_key:
            return jsonify({
                "error": "HEYGEN_API_KEY not found in environment variables",
                "fix": "Add HEYGEN_API_KEY to your .env file"
            }), 400
        if len(api_key) < 20:
            return jsonify({"error": "HEYGEN_API_KEY seems too short", "length": len(api_key)}), 400

        test_payload = {
            'name': f'Test_Interview_{int(time.time())}',
            'description': 'Test knowledge base',
            'content': 'Test interview questions: 1. Tell me about yourself. 2. Why this role?',
            'opening_line': 'Hello, this is a test interview.'
        }
        try:
            heygen_response = requests.post(
                'https://api.heygen.com/v1/streaming/knowledge_base',
                headers={
                    'X-Api-Key': api_key,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                json=test_payload,
                timeout=30
            )
            if heygen_response.ok:
                kb_data = heygen_response.json()
                return jsonify({
                    "success": True,
                    "knowledge_base_id": (kb_data.get('data', {}) or {}).get('knowledge_base_id') or
                                         (kb_data.get('data', {}) or {}).get('id') or
                                         kb_data.get('knowledge_base_id') or kb_data.get('id'),
                    "full_response": kb_data
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "error": "HeyGen API error",
                    "status_code": heygen_response.status_code,
                    "body": heygen_response.text[:500]
                }), 400
        except requests.exceptions.RequestException as e:
            return jsonify({"success": False, "error": "Request failed", "details": str(e)}), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "error": "Unexpected error",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500

# Add this enhanced function to your backend.py

@interview_core_bp.route('/api/verify-interview-system/<token>', methods=['GET'])
def verify_interview_system(token):
    """Verify complete interview system setup"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        if not candidate:
            return jsonify({"error": "Interview not found"}), 404
        
        # Check all components
        checks = {
            "candidate_found": True,
            "resume_exists": bool(candidate.resume_path and os.path.exists(candidate.resume_path)),
            "knowledge_base_created": bool(candidate.knowledge_base_id),
            "heygen_api_configured": bool(os.getenv('HEYGEN_API_KEY')),
            "session_configured": bool(candidate.interview_session_id),
            "recording_ready": True,
            "qa_tracking_ready": True
        }
        
        # Extract sample questions
        sample_questions = []
        if candidate.resume_path:
            resume_content = extract_resume_content(candidate.resume_path)
            skills = extract_skills_from_resume(resume_content)
            sample_questions = [
                f"Tell me about your experience with {skills[0]}" if skills else "Tell me about yourself",
                "What interests you about this position?",
                "Describe a challenging project you've worked on"
            ]
        
        return jsonify({
            "status": "ready" if all(checks.values()) else "issues_found",
            "checks": checks,
            "candidate_info": {
                "name": candidate.name,
                "position": candidate.job_title,
                "knowledge_base_id": candidate.knowledge_base_id
            },
            "sample_questions": sample_questions,
            "recommendations": [
                "Ensure HEYGEN_API_KEY is set" if not checks["heygen_api_configured"] else None,
                "Upload candidate resume" if not checks["resume_exists"] else None,
                "Create knowledge base" if not checks["knowledge_base_created"] else None
            ]
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview-status/<int:candidate_id>', methods=['GET'])
def get_interview_v1_status(candidate_id):
    """Check if interview is already scheduled for a candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        return jsonify({
            "candidate_id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "exam_completed": candidate.exam_completed,
            "exam_percentage": candidate.exam_percentage,
            "interview_scheduled": candidate.interview_scheduled,
            "interview_token": candidate.interview_token,
            "interview_link": candidate.interview_link,
            "final_status": candidate.final_status
        }), 200
    finally:
        session.close()

interview_executor = ThreadPoolExecutor(max_workers=2)

@interview_core_bp.route('/api/interview/track-link-click/<token>', methods=['POST', 'OPTIONS'])
@cross_origin()
def track_interview_link_click(token):
    """Track when a candidate clicks on their interview link"""
    
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        logger.info(f"Tracking link click for token: {token}")
        
        # Import your models and db session
        from models import Candidate, InterviewSession, db
        
        # Find the candidate
        candidate = Candidate.query.filter_by(interview_token=token).first()
        
        if not candidate:
            logger.error(f"No candidate found with token: {token}")
            return jsonify({'error': 'Invalid interview token'}), 404
        
        logger.info(f"Found candidate: {candidate.id} - {candidate.name}")
        
        # Update the interview status from "Interview Scheduled" to "in_progress"
        if candidate.interview_status == "Interview Scheduled":
            candidate.interview_status = "in_progress"
        
        # Set the link clicked timestamp
        if not hasattr(candidate, 'interview_link_clicked_at') or not candidate.interview_link_clicked_at:
            candidate.interview_link_clicked_at = datetime.utcnow()
        
        # Also update the interview session if it exists
        session = InterviewSession.query.filter_by(
            candidate_id=candidate.id
        ).order_by(InterviewSession.created_at.desc()).first()
        
        if session:
            session.status = 'in_progress'
            session.last_activity = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'candidate_id': candidate.id,
            'message': 'Link click tracked successfully',
            'interview_status': candidate.interview_status
        }), 200
        
    except Exception as e:
        logger.error(f"Error tracking link click: {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@interview_core_bp.route('/api/interview/force-complete/<token>', methods=['POST'])
def force_complete_interview(token):
    """Force complete an interview regardless of Q&A count"""
    session = SessionLocal()
    try:
        logger.info(f"Force completing interview for token: {token}")
        
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        if not candidate:
            logger.error(f"No candidate found with token: {token}")
            return jsonify({"error": "Interview not found"}), 404
        
        logger.info(f"Found candidate: {candidate.id} - {candidate.name}")
        logger.info(f"Current completed_at: {candidate.interview_completed_at}")
        
        # Force completion
        if not candidate.interview_completed_at:
            candidate.interview_completed_at = datetime.now()
            candidate.interview_status = 'completed'
            candidate.interview_progress_percentage = 100
            
            # Calculate duration
            if candidate.interview_started_at:
                duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                candidate.interview_duration = int(duration)
            
            # Mark for AI analysis
            candidate.interview_ai_analysis_status = 'pending'
            candidate.final_status = 'Interview Completed'
            
            # Log the changes before commit
            logger.info(f"Setting completed_at to: {candidate.interview_completed_at}")
            logger.info(f"Setting final_status to: {candidate.final_status}")
            
            # Commit the changes
            session.commit()
            logger.info("Changes committed to database")
            
            # Verify the commit worked
            session.refresh(candidate)
            logger.info(f"After commit - completed_at: {candidate.interview_completed_at}")
            
            # Trigger scoring
            try:
                trigger_auto_scoring(candidate.id)
            except Exception as e:
                logger.error(f"Failed to trigger auto-scoring: {e}")
            
        return jsonify({
            "success": True,
            "message": "Interview completed",
            "candidate_id": candidate.id,
            "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error force completing interview: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/session/progress', methods=['POST', 'OPTIONS'])
def update_session_progress():
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    session_id = data.get('session_id')
    progress = data.get('progress', 0)
    status = data.get('status', 'in_progress')
    
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_session_id=session_id).first()
        
        if not candidate:
            # Try splitting session_id and matching by candidate ID
            parts = session_id.split('_')
            if len(parts) >= 2 and parts[1].isdigit():
                candidate_id = int(parts[1])
                candidate = session.query(Candidate).filter_by(id=candidate_id).first()
                if candidate:
                    # Update session_id if found
                    candidate.interview_session_id = session_id
        
        if not candidate:
            logger.warning(f"No candidate found for session_id: {session_id}")
            return jsonify({"error": "Session not found"}), 404
        
        # Update progress fields
        if hasattr(candidate, 'interview_progress_percentage'):
            candidate.interview_progress_percentage = float(progress)
        
        if hasattr(candidate, 'interview_last_activity'):
            candidate.interview_last_activity = datetime.now()
        
        # Handle completion status
        if status == 'completed' or progress >= 100:
            if hasattr(candidate, 'interview_completed_at'):
                if not candidate.interview_completed_at:
                    candidate.interview_completed_at = datetime.now()
                    if hasattr(candidate, 'interview_status'):
                        candidate.interview_status = 'completed'
                    candidate.final_status = 'Interview Completed'
                    
                    if hasattr(candidate, 'interview_started_at') and candidate.interview_started_at:
                        duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                        if hasattr(candidate, 'interview_duration'):
                            candidate.interview_duration = int(duration)
                    
                    if hasattr(candidate, 'interview_ai_analysis_status'):
                        candidate.interview_ai_analysis_status = 'pending'
                    
                    logger.info(f"Interview marked as completed for candidate {candidate.id}")
                    # session.commit()

                    try:
                        if 'trigger_auto_scoring' in globals():
                            trigger_auto_scoring(candidate.id)
                        else:
                            logger.warning("Auto-scoring function not found.")
                    except Exception as e:
                        logger.error(f"Error triggering auto-scoring: {e}")
        
        elif status == 'in_progress' and hasattr(candidate, 'interview_started_at'):
            if not candidate.interview_started_at:
                candidate.interview_started_at = datetime.now()
                if hasattr(candidate, 'interview_status'):
                    candidate.interview_status = 'in_progress'
        
        # if session.dirty:
        session.commit()

        cache.delete_memoized(get_cached_candidates)

        return jsonify({
            "success": True,
            "progress": progress,
            "status": status,
            "candidate_id": candidate.id,
            "candidate_name": candidate.name
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating progress: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@interview_core_bp.route('/api/interview/session/complete', methods=['POST', 'OPTIONS'])
def complete_interview_session():
    """Mark interview session as complete"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    session_id = data.get('session_id')
    interview_token = data.get('interview_token')
    
    session = SessionLocal()
    try:
        # Find candidate by session_id or token
        candidate = None
        if session_id:
            candidate = session.query(Candidate).filter_by(
                interview_session_id=session_id
            ).first()
        elif interview_token:
            candidate = session.query(Candidate).filter_by(
                interview_token=interview_token
            ).first()
        
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        # Mark as completed
        candidate.interview_completed_at = datetime.now()
        candidate.interview_progress_percentage = 100
        candidate.final_status = 'Interview Completed - Pending Review'
        
        # Update interview status if it exists
        if hasattr(candidate, 'interview_status'):
            candidate.interview_status = 'completed'
        
        # Calculate interview duration if interview started
        if candidate.interview_started_at:
            duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
            if hasattr(candidate, 'interview_duration'):
                candidate.interview_duration = int(duration)
        
        # Update Q&A stats if interview_total_questions exists
        if hasattr(candidate, 'interview_qa_completion_rate'):
            if candidate.interview_total_questions and candidate.interview_total_questions > 0:
                completion_rate = (candidate.interview_answered_questions / candidate.interview_total_questions) * 100
                candidate.interview_qa_completion_rate = completion_rate
        
        # Set AI analysis status to pending if the attribute exists
        if hasattr(candidate, 'interview_ai_analysis_status'):
            candidate.interview_ai_analysis_status = 'pending'
        
        session.commit()
        
        logger.info(f"Interview completed for candidate {candidate.id} - {candidate.name}")
        
        # Trigger analysis in background (auto-scoring)
        try:
            if 'trigger_auto_scoring' in globals():
                from concurrent.futures import ThreadPoolExecutor
                executor = ThreadPoolExecutor(max_workers=2)
                executor.submit(trigger_auto_scoring, candidate.id)
        except Exception as e:
            logger.error(f"Failed to trigger analysis: {e}")
        
        return jsonify({
            "success": True,
            "message": "Interview completed successfully",
            "candidate_id": candidate.id,
            "duration_seconds": candidate.interview_duration if hasattr(candidate, 'interview_duration') else None,
            "next_step": "AI analysis in progress"
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error completing interview session: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()
# Add to backend.py

@interview_core_bp.route('/api/interview/status/<token>', methods=['GET'])
def get_interview_status(token):
    """Get current interview status - LIGHTWEIGHT"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Interview not found"}), 404
        
        # Determine current status
        status = 'not_started'
        if candidate.interview_completed_at:
            status = 'completed'
        elif hasattr(candidate, 'interview_status') and candidate.interview_status:
            status = candidate.interview_status
        elif candidate.interview_started_at:
            status = 'in_progress'
        elif candidate.link_clicked or (hasattr(candidate, 'interview_link_clicked') and candidate.interview_link_clicked):
            status = 'link_clicked'
        
        # Return only essential data
        return jsonify({
            "status": status,
            "progress": candidate.interview_progress_percentage if hasattr(candidate, 'interview_progress_percentage') else 0,
            "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
            "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
            "expires_at": candidate.interview_expires_at.isoformat() if candidate.interview_expires_at else None
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview/dashboard', methods=['GET'])
def interview_tracking_dashboard():
    """Get dashboard data for all interviews"""
    session = SessionLocal()
    try:
        # Get all scheduled interviews
        all_interviews = session.query(Candidate).filter(
            Candidate.interview_scheduled == True
        ).all()
        
        stats = {
            "total_scheduled": len(all_interviews),
            "not_started": 0,
            "link_clicked": 0,
            "in_progress": 0,
            "completed": 0,
            "expired": 0,
            "abandoned": 0
        }
        
        interviews = []
        
        for candidate in all_interviews:
            # Determine status
            if candidate.interview_completed_at:
                status = 'completed'
                stats['completed'] += 1
            elif candidate.interview_status == 'expired':
                status = 'expired'
                stats['expired'] += 1
            elif candidate.interview_status == 'abandoned':
                status = 'abandoned'
                stats['abandoned'] += 1
            elif candidate.interview_started_at:
                status = 'in_progress'
                stats['in_progress'] += 1
            elif candidate.interview_link_clicked:
                status = 'link_clicked'
                stats['link_clicked'] += 1
            else:
                status = 'not_started'
                stats['not_started'] += 1
            
            interviews.append({
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title,
                "status": status,
                "scheduled_date": candidate.interview_date.isoformat() if candidate.interview_date else None,
                "link_clicked": bool(candidate.interview_link_clicked),
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "progress": candidate.interview_progress_percentage or 0,
                "ai_score": candidate.interview_ai_score,
                "final_status": candidate.final_status
            })
        
        return jsonify({
            "success": True,
            "stats": stats,
            "interviews": interviews,
            "last_updated": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview-results', methods=['GET'])
@cache.memoize(timeout=60)
def get_all_interview_results():
    """Get all interview results with proper filtering and pagination"""
    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        status_filter = request.args.get('status')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        session = SessionLocal()
        try:
            # Build query
            query = session.query(Candidate).filter(
                Candidate.interview_scheduled == True
            )
            
            # Apply filters
            if status_filter:
                if status_filter == 'completed':
                    query = query.filter(Candidate.interview_completed_at.isnot(None))
                elif status_filter == 'in_progress':
                    query = query.filter(
                        Candidate.interview_started_at.isnot(None),
                        Candidate.interview_completed_at.is_(None)
                    )
                elif status_filter == 'analyzed':
                    query = query.filter(
                        Candidate.interview_ai_analysis_status == AnalysisStatus.COMPLETED.value
                    )
            
            if date_from:
                query = query.filter(Candidate.interview_date >= date_from)
            if date_to:
                query = query.filter(Candidate.interview_date <= date_to)
            
            # Order by most recent
            query = query.order_by(Candidate.interview_date.desc())
            
            # Paginate
            total = query.count()
            candidates = query.offset((page - 1) * per_page).limit(per_page).all()
            
            # Format results
            results = []
            for candidate in candidates:
                # Safe JSON parsing
                def safe_json_parse(data, default):
                    try:
                        return json.loads(data) if data else default
                    except:
                        return default
                
                result = {
                    'id': candidate.id,
                    'name': candidate.name,
                    'email': candidate.email,
                    'phone': candidate.phone,
                    'job_title': candidate.job_title,
                    'resume_url': candidate.resume_path,
                    
                    # Interview details
                    'interview_date': candidate.interview_date.isoformat() if candidate.interview_date else None,
                    'interview_scheduled': candidate.interview_scheduled,
                    'interview_started_at': candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                    'interview_completed_at': candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                    'interview_duration': candidate.interview_duration or 0,
                    'interview_token': candidate.interview_token,
                    
                    # Progress
                    'interview_progress': candidate.interview_progress_percentage or 0,
                    'interview_questions_answered': candidate.interview_answered_questions or 0,
                    'interview_total_questions': candidate.interview_total_questions or 0,
                    
                    # Scores
                    'interview_ai_score': candidate.interview_ai_score,
                    'interview_ai_technical_score': candidate.interview_ai_technical_score,
                    'interview_ai_communication_score': candidate.interview_ai_communication_score,
                    'interview_ai_problem_solving_score': candidate.interview_ai_problem_solving_score,
                    'interview_ai_cultural_fit_score': candidate.interview_ai_cultural_fit_score,
                    
                    # Analysis
                    'interview_ai_analysis_status': candidate.interview_ai_analysis_status,
                    'interview_ai_overall_feedback': candidate.interview_ai_overall_feedback,
                    'interview_final_status': candidate.interview_final_status,
                    
                    # Insights
                    'strengths': safe_json_parse(candidate.interview_strengths, []),
                    'weaknesses': safe_json_parse(candidate.interview_weaknesses, []),
                    'recommendations': safe_json_parse(candidate.interview_recommendations, []),
                    
                    # Metadata
                    'interview_confidence_score': candidate.interview_confidence_score,
                    'interview_scoring_method': candidate.interview_scoring_method,
                    'interview_recording_url': candidate.interview_recording_url
                }
                
                results.append(result)
            
            # Return paginated response
            return jsonify({
                'results': results,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'pages': (total + per_page - 1) // per_page
                }
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error getting interview results: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500
    
@interview_core_bp.route('/api/interview/trigger-analysis/<int:candidate_id>', methods=['POST'])
@rate_limit(max_calls=5, time_window=60)
def trigger_analysis_manually(candidate_id):
    """Manually trigger analysis for a candidate"""
    try:
        # Validate candidate exists
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            if not candidate:
                return jsonify({"error": "Candidate not found"}), 404
            
            if not candidate.interview_completed_at:
                return jsonify({"error": "Interview not completed"}), 400
            
            # Reset flags to trigger analysis
            candidate.interview_auto_score_triggered = False
            candidate.interview_ai_analysis_status = None
            session.commit()
        finally:
            session.close()
        
        # Queue for analysis
        success = interview_analysis_service.analyze_single_interview(candidate_id)
        
        if success:
            return jsonify({
                "success": True,
                "message": "Analysis triggered successfully",
                "candidate_id": candidate_id
            }), 200
        else:
            return jsonify({
                "success": False,
                "message": "Failed to trigger analysis"
            }), 500
            
    except Exception as e:
        logger.error(f"Error triggering analysis: {e}")
        return jsonify({"error": str(e)}), 500

@interview_core_bp.route('/api/interview/validate-analysis/<int:candidate_id>', methods=['GET'])
def validate_analysis(candidate_id):
    """Validate that analysis is dynamic, not random"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Get Q&A data
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        
        # Check for invalid responses
        has_invalid = False
        invalid_answers = []
        
        for qa in qa_pairs:
            answer = qa.get('answer', '').strip()
            if answer in ['INIT_INTERVIEW', 'TEST', ''] or len(answer) < 5:
                has_invalid = True
                invalid_answers.append(answer)
        
        return jsonify({
            "candidate_id": candidate_id,
            "name": candidate.name,
            "has_valid_qa_data": len(qa_pairs) > 0 and not has_invalid,
            "total_questions": len(qa_pairs),
            "invalid_answers": invalid_answers,
            "current_score": candidate.interview_ai_score,
            "scoring_method": candidate.interview_scoring_method,
            "analysis_status": candidate.interview_ai_analysis_status,
            "should_fail": has_invalid,
            "expected_score_range": "0-30%" if has_invalid else "Based on actual content"
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview/reanalyze/<int:candidate_id>', methods=['POST'])
def reanalyze_interview(candidate_id):
    """Force re-analysis with dynamic scoring"""
    try:
        from interview_analysis_service_production_fixed import dynamic_analyzer
        
        # Perform dynamic analysis
        result = dynamic_analyzer.analyze_interview(candidate_id)
        
        return jsonify({
            "success": True,
            "message": "Re-analysis completed",
            "new_score": result['overall_score'],
            "method": result['method'],
            "recommendation": result.get('recommendation')
        }), 200
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@interview_core_bp.route('/api/interview/service-status', methods=['GET'])
def get_analysis_service_status():
    """Get analysis service health status"""
    try:
        stats = interview_analysis_service.get_service_stats()
        
        # Add database stats
        session = SessionLocal()
        try:
            db_stats = {
                'pending_analyses': session.query(Candidate).filter(
                    Candidate.interview_completed_at.isnot(None),
                    Candidate.interview_ai_analysis_status.is_(None)
                ).count(),
                'processing_analyses': session.query(Candidate).filter(
                    Candidate.interview_ai_analysis_status == AnalysisStatus.PROCESSING.value
                ).count(),
                'completed_today': session.query(Candidate).filter(
                    Candidate.interview_analysis_completed_at >= datetime.now().replace(hour=0, minute=0, second=0)
                ).count()
            }
            stats['database'] = db_stats
        finally:
            session.close()
        
        return jsonify({
            "status": "healthy" if stats['is_running'] else "stopped",
            "details": stats
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting service status: {e}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@atexit.register
def cleanup_analysis_service():
    """Cleanup on shutdown"""
    try:
        logger.info("Stopping Interview Analysis Service...")
        interview_analysis_service.stop()
    except Exception as e:
        logger.error(f"Error stopping analysis service: {e}")

@interview_core_bp.route('/api/interview/live-status/<int:candidate_id>', methods=['GET'])
def get_live_interview_status(candidate_id):
    """Get real-time interview status for frontend"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Parse Q&A data
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        
        # Calculate live stats
        status = {
            'candidate_id': candidate.id,
            'name': candidate.name,
            'interview_status': get_interview_status(candidate),
            'progress': candidate.interview_progress_percentage or 0,
            'link_clicked': candidate.interview_link_clicked,
            'started': bool(candidate.interview_started_at),
            'completed': bool(candidate.interview_completed_at),
            'total_questions': candidate.interview_total_questions or 0,
            'answered_questions': candidate.interview_answered_questions or 0,
            'unanswered': candidate.interview_total_questions - candidate.interview_answered_questions if candidate.interview_total_questions else 0,
            'duration': None,
            'ai_score': candidate.interview_ai_score,
            'analysis_status': candidate.interview_ai_analysis_status,
            'last_activity': candidate.interview_last_activity.isoformat() if candidate.interview_last_activity else None,
            'connection_quality': candidate.interview_connection_quality or 'unknown',
            'current_question': None,
            'is_active': False
        }
        
        # Calculate duration
        if candidate.interview_started_at:
            if candidate.interview_completed_at:
                duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
            else:
                duration = (datetime.now() - candidate.interview_started_at).total_seconds()
            status['duration'] = int(duration)
        
        # Check if currently active
        if candidate.interview_last_activity:
            time_since_activity = (datetime.now() - candidate.interview_last_activity).total_seconds()
            status['is_active'] = time_since_activity < 60  # Active if activity within last minute
        
        # Get current question being answered
        for qa in qa_pairs:
            if qa.get('question') and not qa.get('answer'):
                status['current_question'] = qa.get('question')
                break
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"Error getting live status: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/poll-updates/<int:candidate_id>', methods=['GET'])
def poll_interview_updates(candidate_id):
    """Polling endpoint for real-time updates"""
    update_key = f"interview_update_{candidate_id}"
    update_data = cache.get(update_key)
    
    if update_data:
        return jsonify(json.loads(update_data)), 200
    else:
        return jsonify({"no_updates": True}), 204

@interview_core_bp.route('/api/verify-interview-process/<int:candidate_id>', methods=['GET'])
def verify_interview_process(candidate_id):
    """Verify the interview link generation process for a candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Check assessment completion
        assessment_status = {
            "exam_completed": candidate.exam_completed,
            "exam_percentage": candidate.exam_percentage,
            "exam_score": candidate.exam_score,
            "exam_feedback": candidate.exam_feedback
        }
        
        # Check interview status
        interview_status = {
            "interview_scheduled": candidate.interview_scheduled,
            "interview_token": candidate.interview_token,
            "interview_link": candidate.interview_link,
            "knowledge_base_id": candidate.knowledge_base_id,
            "final_status": candidate.final_status
        }
        
        # Determine if interview should be scheduled
        should_schedule = (
            candidate.exam_completed and 
            candidate.exam_percentage >= 70 and 
            not candidate.interview_scheduled
        )
        
        # Generate test interview link if needed
        test_link = None
        if should_schedule and not candidate.interview_token:
            import uuid
            test_token = str(uuid.uuid4())
            test_link = f"{request.host_url.rstrip('/')}/secure-interview/{test_token}"
        
        return jsonify({
            "candidate_info": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "job_title": candidate.job_title
            },
            "assessment_status": assessment_status,
            "interview_status": interview_status,
            "should_schedule_interview": should_schedule,
            "test_interview_link": test_link,
            "process_ready": candidate.exam_completed and candidate.exam_percentage is not None
        }), 200
    finally:
        session.close()

@interview_core_bp.route('/api/interview/recording/start', methods=['POST', 'OPTIONS'])
def start_recording():
    if request.method == 'OPTIONS':
        return _ok_preflight()

    body = request.get_json(silent=True) or {}
    session_id = body.get('session_id')
    if not session_id:
        return jsonify({"success": False, "error": "session_id required"}), 400

    base = _ensure_dir(os.path.join('logs', 'interviews', session_id))
    _append_jsonl(os.path.join(base, 'session.jsonl'), {
        "event": "recording_started",
        "ts": datetime.now(timezone.utc).isoformat(),
        "meta": {
            "recording_format": body.get('recording_format'),
            "client_meta": body.get('client_meta'),
        }
    })

    # optional: flag on candidate
    try:
        db = SessionLocal()
        try:
            cand = db.query(Candidate).filter_by(interview_session_id=session_id).first()
            if cand:
                cand.recording_started_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("start_recording: candidate update failed")

    return jsonify({"success": True}), 200

@interview_core_bp.route("/api/interview/recording/upload", methods=["POST", "OPTIONS"])
def upload_recording():
    # CORS preflight
    if request.method == "OPTIONS":
        return _ok_preflight()

    # multipart/form-data expected
    f = request.files.get("recording")
    session_id = request.form.get("session_id") or request.args.get("session_id")

    if not f or not session_id:
        return jsonify({"success": False, "error": "missing recording file or session_id"}), 400

    # sanitize session_id for filesystem usage
    safe_session = secure_filename(str(session_id)) or f"session_{int(time.time())}"

    # Decide filename + ext
    ext = _ext_from_filename(getattr(f, "filename", None), default_ext="webm")
    base = _ensure_dir(os.path.join("logs", "interviews", safe_session))
    fname = f"interview_{safe_session}_{int(time.time())}.{ext}"
    path = os.path.join(base, fname)

    try:
        # Save file
        f.save(path)

        # Log event
        _append_jsonl(os.path.join(base, "session.jsonl"), {
            "event": "recording_uploaded",
            "ts": datetime.now(timezone.utc).isoformat(),
            "file": path,
            "size": os.path.getsize(path),
            "session_id": safe_session,
        })

        # Optional: update candidate record
        try:
            db = SessionLocal()
            try:
                cand = db.query(Candidate).filter_by(interview_session_id=session_id).first()
                if cand:
                    cand.recording_path = path
                    cand.interview_recording_format = ext
                    cand.interview_recording_status = "completed"
                    # only set completed_at if not already present
                    if not getattr(cand, "interview_completed_at", None):
                        cand.interview_completed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception as e:
                db.rollback()
                logger.exception(f"Failed to update candidate recording info: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.exception(f"upload_recording: candidate update failed: {e}")

        return jsonify({"success": True, "path": path}), 200

    except Exception as e:
        logger.exception(f"upload_recording: saving failed: {e}")
        return jsonify({"success": False, "error": "failed to save recording"}), 500
    
@interview_core_bp.route('/api/interview/full-analysis/<token>', methods=['GET'])
def get_full_interview_analysis(token):
    """Get complete interview analysis data"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Interview not found"}), 404
        
        # Parse Q&A data
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        questions_asked = json.loads(candidate.interview_questions_asked or '[]')
        answers_given = json.loads(candidate.interview_answers_given or '[]')
        
        return jsonify({
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title
            },
            "interview_status": {
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "duration_seconds": candidate.interview_duration,
                "duration_minutes": round(candidate.interview_duration / 60, 1) if candidate.interview_duration else None,
                "status": candidate.interview_status,
                "progress": candidate.interview_progress_percentage
            },
            "qa_statistics": {
                "total_qa_pairs": len(qa_pairs),
                "questions_asked": len(questions_asked),
                "answers_given": len(answers_given),
                "completion_rate": f"{(len(answers_given) / len(questions_asked) * 100) if questions_asked else 0:.1f}%"
            },
            "ai_analysis": {
                "analysis_status": candidate.interview_ai_analysis_status,
                "overall_score": candidate.interview_ai_score,
                "technical_score": candidate.interview_ai_technical_score,
                "communication_score": candidate.interview_ai_communication_score,
                "problem_solving_score": candidate.interview_ai_problem_solving_score,
                "cultural_fit_score": candidate.interview_ai_cultural_fit_score,
                "final_status": candidate.interview_final_status,
                "overall_feedback": candidate.interview_ai_overall_feedback
            },
            "recommendation": {
                "final_status": candidate.final_status,
                "interview_passed": candidate.interview_ai_score >= 70 if candidate.interview_ai_score else False
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting full analysis: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/fix-status/<token>', methods=['POST'])
@cross_origin()
def fix_interview_status(token):
    """Fix interview status and completion tracking"""
    
    try:
        from models import Candidate, InterviewSession, InterviewQA, db
        
        candidate = Candidate.query.filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({'error': 'Invalid token'}), 404
        
        # Get current session
        session = InterviewSession.query.filter_by(
            candidate_id=candidate.id
        ).order_by(InterviewSession.created_at.desc()).first()
        
        # Count actual Q&A pairs with answers
        qa_count = InterviewQA.query.filter_by(
            candidate_id=candidate.id
        ).filter(InterviewQA.answer.isnot(None)).count()
        
        # Determine if interview should be complete
        # Based on your completion criteria
        should_complete = qa_count >= 10  # At least 10 answered questions
        
        if should_complete:
            # Mark as complete
            candidate.interview_completed_at = datetime.utcnow()
            candidate.interview_status = "Completed"
            
            if candidate.interview_started_at:
                duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                candidate.interview_duration = int(duration)
            
            if session:
                session.status = 'completed'
                session.completed_at = datetime.utcnow()
                session.progress = 100.0
            
            message = "Interview marked as completed"
        else:
            # Update to in_progress
            candidate.interview_status = "in_progress"
            
            if session:
                session.status = 'in_progress'
                # Calculate actual progress
                session.progress = (qa_count / 30) * 100  # Assuming 30 total questions
            
            message = f"Interview status updated to in_progress ({qa_count} questions answered)"
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': message,
            'candidate_id': candidate.id,
            'status': candidate.interview_status,
            'qa_count': qa_count,
            'progress': session.progress if session else 0
        }), 200
        
    except Exception as e:
        logger.error(f"Error fixing status: {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@interview_core_bp.route('/api/interview/debug-db/<token>', methods=['GET'])
def debug_interview_db(token):
    """Debug database state for an interview"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Interview not found"}), 404
        
        # Get all interview-related fields
        interview_fields = {}
        for attr in dir(candidate):
            if attr.startswith('interview_') and not attr.startswith('_'):
                try:
                    value = getattr(candidate, attr)
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    elif callable(value):
                        continue
                    interview_fields[attr] = value
                except:
                    interview_fields[attr] = "Error reading"
        
        return jsonify({
            "candidate_id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "token": token,
            "interview_fields": interview_fields,
            "has_completed_at": candidate.interview_completed_at is not None,
            "final_status": candidate.final_status,
            "database_values": {
                "interview_completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "interview_started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "interview_status": getattr(candidate, 'interview_status', None),
                "interview_progress_percentage": getattr(candidate, 'interview_progress_percentage', None),
                "interview_duration": getattr(candidate, 'interview_duration', None),
                "final_status": candidate.final_status
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/check/<token>', methods=['GET'])
def check_interview_simple(token):
    """Simple check of interview status"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Interview not found"}), 404
        
        # Force a fresh read from database
        session.refresh(candidate)
        
        return jsonify({
            "candidate_id": candidate.id,
            "name": candidate.name,
            "interview_completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
            "interview_started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
            "final_status": candidate.final_status,
            "fields_exist": {
                "has_completed_at_field": hasattr(candidate, 'interview_completed_at'),
                "has_status_field": hasattr(candidate, 'interview_status'),
                "has_duration_field": hasattr(candidate, 'interview_duration'),
            }
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview/export-conversation/<session_id>', methods=['GET'])
def export_conversation_unified(session_id):
    """Export conversation in various formats"""
    format_type = request.args.get('format', 'text')
    
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_session_id=session_id).first()
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        conversation = json.loads(getattr(candidate, 'interview_conversation', '[]'))
        
        # If no conversation data, build from qa_pairs
        if not conversation:
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            for qa in qa_pairs:
                if qa.get('question'):
                    conversation.append({
                        'type': 'question',
                        'speaker': 'Avatar',
                        'content': qa['question'],
                        'timestamp': qa.get('timestamp')
                    })
                    if qa.get('answer'):
                        conversation.append({
                            'type': 'answer',
                            'speaker': 'Candidate',
                            'content': qa['answer'],
                            'timestamp': qa.get('answered_at')
                        })
        
        if format_type == 'text':
            # Plain text format
            output = f"Interview Transcript\n"
            output += f"Candidate: {candidate.name}\n"
            output += f"Position: {candidate.job_title}\n"
            output += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            output += "="*50 + "\n\n"
            
            for entry in conversation:
                output += f"{entry.get('speaker', 'Unknown')}: {entry['content']}\n\n"
            
            response = Response(output, mimetype='text/plain')
            response.headers['Content-Disposition'] = f'attachment; filename=interview_{candidate.name}_{session_id}.txt'
            return response
            
        elif format_type == 'json':
            # JSON format with all metadata
            output = {
                "interview": {
                    "session_id": session_id,
                    "candidate": {
                        "id": candidate.id,
                        "name": candidate.name,
                        "email": candidate.email,
                        "position": candidate.job_title
                    },
                    "date": datetime.now().isoformat(),
                    "conversation": conversation,
                    "statistics": {
                        "total_exchanges": len(conversation),
                        "questions": len([e for e in conversation if e['type'] == 'question']),
                        "answers": len([e for e in conversation if e['type'] == 'answer']),
                        "completion": candidate.interview_progress_percentage
                    }
                }
            }
            
            response = Response(json.dumps(output, indent=2), mimetype='application/json')
            response.headers['Content-Disposition'] = f'attachment; filename=interview_{candidate.name}_{session_id}.json'
            return response
            
        elif format_type == 'html':
            # HTML format for viewing
            html = f"""
            <html>
            <head>
                <title>Interview Transcript - {candidate.name}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    .header {{ background: #f0f0f0; padding: 20px; margin-bottom: 30px; }}
                    .conversation {{ max-width: 800px; }}
                    .avatar {{ color: #2563eb; font-weight: bold; margin-top: 20px; }}
                    .candidate {{ color: #059669; font-weight: bold; margin-top: 20px; }}
                    .content {{ margin-left: 20px; margin-top: 5px; }}
                    .timestamp {{ color: #999; font-size: 0.8em; }}
                    .metadata {{ color: #666; font-size: 0.8em; font-style: italic; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>Interview Transcript</h1>
                    <p><strong>Candidate:</strong> {candidate.name}</p>
                    <p><strong>Position:</strong> {candidate.job_title}</p>
                    <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p><strong>Progress:</strong> {candidate.interview_progress_percentage:.1f}%</p>
                </div>
                <div class="conversation">
            """
            
            for entry in conversation:
                speaker_class = 'avatar' if entry.get('speaker') == 'Avatar' else 'candidate'
                html += f'<div class="{speaker_class}">{entry.get("speaker", "Unknown")}:</div>'
                html += f'<div class="content">{entry["content"]}</div>'
                if entry.get('timestamp'):
                    html += f'<div class="timestamp">{entry["timestamp"]}</div>'
                if entry.get('metadata') and any(entry['metadata'].values()):
                    metadata_str = ', '.join([f"{k}: {v}" for k, v in entry['metadata'].items() if v])
                    html += f'<div class="metadata">{metadata_str}</div>'
            
            html += """
                </div>
            </body>
            </html>
            """
            
            response = Response(html, mimetype='text/html')
            response.headers['Content-Disposition'] = f'attachment; filename=interview_{candidate.name}_{session_id}.html'
            return response
            
    except Exception as e:
        logger.error(f"Error exporting conversation: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/fix-all-pending', methods=['POST'])
def fix_all_pending_interviews():
    """Fix all completed interviews that haven't been analyzed"""
    session = SessionLocal()
    fixed = 0
    
    try:
        # Find all completed interviews without scores
        pending = session.query(Candidate).filter(
            Candidate.interview_completed_at.isnot(None),
            Candidate.interview_ai_score.is_(None)
        ).all()
        
        for candidate in pending:
            # Trigger analysis
            candidate.interview_ai_analysis_status = 'pending'
            session.commit()
            
            # Trigger auto-scoring
            trigger_auto_scoring(candidate.id)
            fixed += 1
            
            logger.info(f"Triggered analysis for candidate {candidate.id} - {candidate.name}")
        
        # Clear cache
        cache.delete_memoized(get_cached_candidates)
        
        return jsonify({
            "success": True,
            "fixed": fixed,
            "message": f"Triggered analysis for {fixed} interviews"
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error fixing interviews: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/poll-updates', methods=['GET'])
def poll_for_updates():
    """Poll for interview analysis updates"""
    session = SessionLocal()
    try:
        # Find recently completed analyses
        cutoff = datetime.now() - timedelta(minutes=5)
        
        updated = session.query(Candidate).filter(
            Candidate.interview_analysis_completed_at >= cutoff,
            Candidate.interview_ai_score.isnot(None)
        ).all()
        
        updates = []
        for candidate in updated:
            updates.append({
                'candidate_id': candidate.id,
                'scores': {
                    'overall': candidate.interview_ai_score,
                    'technical': candidate.interview_ai_technical_score,
                    'communication': candidate.interview_ai_communication_score,
                    'problem_solving': candidate.interview_ai_problem_solving_score,
                    'cultural_fit': candidate.interview_ai_cultural_fit_score
                },
                'final_status': candidate.interview_final_status,
                'timestamp': candidate.interview_analysis_completed_at.isoformat()
            })
        
        return jsonify({
            'success': True,
            'updates': updates
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/resume-text/<int:candidate_id>', methods=['GET'])
def api_resume_text(candidate_id):
    session = SessionLocal()
    try:
        cand = session.query(Candidate).filter_by(id=candidate_id).first()
        if not cand:
            return jsonify({"error": "Candidate not found"}), 404

        text = ""
        if cand.resume_path and os.path.exists(cand.resume_path):
            # uses your existing extractor
            text = extract_resume_content(cand.resume_path)

        return jsonify({"resume_text": text, "length": len(text)}), 200
    finally:
        session.close()

@interview_core_bp.route('/api/interview/export-conversation/<int:candidate_id>', methods=['GET'])
def export_conversation(candidate_id):
    """Export conversation in various formats"""
    format_type = request.args.get('format', 'text')  # text, json, pdf
    
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        if format_type == 'text':
            # Return plain text conversation
            conversation = candidate.interview_conversation or "No conversation recorded"
            
            response = Response(
                conversation,
                mimetype='text/plain',
                headers={
                    'Content-Disposition': f'attachment; filename=interview_{candidate.name}_{candidate.id}.txt'
                }
            )
            return response
            
        elif format_type == 'json':
            # Return structured JSON
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            
            export_data = {
                "candidate": {
                    "id": candidate.id,
                    "name": candidate.name,
                    "email": candidate.email,
                    "position": candidate.job_title
                },
                "interview_date": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "qa_pairs": qa_pairs,
                "formatted_conversation": candidate.interview_conversation
            }
            
            return jsonify(export_data), 200
            
        else:
            return jsonify({"error": "Invalid format"}), 400
            
    finally:
        session.close()

@interview_core_bp.route('/api/interview/candidate/<int:candidate_id>/full-data', methods=['GET'])
def get_candidate_interview_data(candidate_id):
    """Get complete interview data for a candidate including Q&A"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Parse all interview data
        questions = json.loads(candidate.interview_questions_asked or '[]')
        answers = json.loads(candidate.interview_answers_given or '[]')
        
        return jsonify({
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title
            },
            "interview": {
                "scheduled": candidate.interview_scheduled,
                "token": candidate.interview_token,
                "session_id": candidate.interview_session_id,
                "knowledge_base_id": candidate.knowledge_base_id,
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None
            },
            "qa_data": {
                "questions": questions,
                "answers": answers,
                "total_questions": len(questions),
                "total_answers": len(answers),
                "completion_rate": f"{(len(answers) / len(questions) * 100) if questions else 0:.1f}%"
            },
            "transcript": {
                "content": candidate.interview_transcript,
                "length": len(candidate.interview_transcript or ''),
                "lines": len((candidate.interview_transcript or '').strip().split('\n'))
            },
            "recording": {
                "status": candidate.interview_recording_status,
                "file": candidate.interview_recording_file,
                "duration": candidate.interview_recording_duration
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting candidate interview data: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/session/data/<session_id>', methods=['GET'])
def get_interview_session_data(session_id):
    """Get complete interview session data including recording and Q&A"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(
            interview_session_id=session_id
        ).first()
        
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        # Parse Q&A data
        questions = json.loads(candidate.interview_questions_asked or '[]')
        answers = json.loads(candidate.interview_answers_given or '[]')
        
        # Create Q&A pairs
        qa_pairs = []
        for i, question in enumerate(questions):
            answer = next((a for a in answers if a.get('question_order') == i + 1), None)
            qa_pairs.append({
                'question': question,
                'answer': answer
            })
        
        return jsonify({
            "session_id": session_id,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title
            },
            "recording": {
                "status": candidate.interview_recording_status,
                "file": candidate.interview_recording_file,
                "url": candidate.interview_recording_url,
                "duration": candidate.interview_recording_duration,
                "size": candidate.interview_recording_size,
                "format": candidate.interview_recording_format
            },
            "qa_data": {
                "total_questions": candidate.interview_total_questions,
                "total_answers": candidate.interview_answered_questions,
                "qa_pairs": qa_pairs,
                "raw_questions": questions,
                "raw_answers": answers
            },
            "ai_analysis": {
                "status": candidate.interview_ai_analysis_status,
                "overall_score": candidate.interview_ai_score,
                "technical_score": candidate.interview_ai_technical_score,
                "communication_score": candidate.interview_ai_communication_score,
                "feedback": candidate.interview_ai_overall_feedback
            },
            "timestamps": {
                "started": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "completed": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None
            }
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview/session/start', methods=['POST', 'OPTIONS'])
def start_interview_session():
    if request.method == 'OPTIONS':
        return _ok_preflight()

    body = request.get_json(silent=True) or {}
    interview_token   = body.get('interview_token')
    candidate_id      = body.get('candidate_id')
    recording_config  = body.get('recording_config') or {}

    # make a session id if none provided
    session_id = body.get('session_id') or f"sess_{uuid.uuid4().hex[:8]}_{int(time.time())}"

    # persist basic linkage if we can find the candidate
    try:
        session = SessionLocal()
        try:
            candidate = None
            if candidate_id:
                candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            elif interview_token:
                candidate = session.query(Candidate).filter_by(interview_token=interview_token).first()

            if candidate:
                candidate.interview_session_id = session_id
                candidate.interview_started_at = datetime.now(timezone.utc)
                candidate.last_accessed = datetime.now(timezone.utc)
                # initialize counters if fields exist
                if not getattr(candidate, 'interview_total_questions', None):
                    candidate.interview_total_questions = 0
                if not getattr(candidate, 'interview_answered_questions', None):
                    candidate.interview_answered_questions = 0
                session.commit()
        finally:
            session.close()
    except Exception as e:
        logger.exception("start_interview_session: DB linkage failed")

    # create a place to log things to disk (optional but handy)
    base = _ensure_dir(os.path.join('logs', 'interviews', session_id))
    _append_jsonl(os.path.join(base, 'session.jsonl'), {
        "event": "session_started",
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "interview_token": interview_token,
        "candidate_id": candidate_id,
        "recording_config": recording_config,
    })

    return jsonify({
        "success": True,
        "session_id": session_id,
        "message": "Interview session initialized"
    }), 200

@interview_core_bp.route('/api/get-candidate-by-token/<token>', methods=['GET', 'OPTIONS'])
def get_candidate_by_token(token):
    """Get candidate data by interview token for KB creation"""
    if request.method == 'OPTIONS':
        return '', 200
    
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        candidate_data = {
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "job_title": candidate.job_title,
            "company": getattr(candidate, 'company_name', os.getenv('COMPANY_NAME', 'Our Company')),
            "resume_path": candidate.resume_path,
            "job_description": getattr(candidate, 'job_description', None),
            "ats_score": candidate.ats_score,
            "phone": getattr(candidate, 'phone', None)
        }
        
        return jsonify(candidate_data), 200
        
    except Exception as e:
        logger.error(f"Error getting candidate by token: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/extract-resume/<int:candidate_id>', methods=['GET', 'OPTIONS'])
def extract_resume_content_api(candidate_id):
    """Extract resume content for a candidate"""
    if request.method == 'OPTIONS':
        return '', 200
    
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        if not candidate.resume_path or not os.path.exists(candidate.resume_path):
            return jsonify({
                "content": "",
                "message": "No resume file available",
                "file_path": candidate.resume_path
            }), 200
        
        # Extract resume content
        resume_content = extract_resume_content(candidate.resume_path)
        
        # Extract additional metadata
        skills = extract_skills_from_resume(resume_content)
        experience = extract_experience_years(resume_content)
        projects = extract_projects_from_resume(resume_content)
        
        return jsonify({
            "content": resume_content,
            "skills": skills,
            "experience": experience,
            "projects": projects,
            "file_path": candidate.resume_path,
            "content_length": len(resume_content),
            "extraction_successful": len(resume_content) > 0
        }), 200
        
    except Exception as e:
        logger.error(f"Error extracting resume: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/validate-kb-creation/<int:candidate_id>', methods=['GET', 'OPTIONS'])
def validate_kb_creation(candidate_id):
    """Validate that all components are ready for KB creation"""
    if request.method == 'OPTIONS':
        return '', 200
    
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Check all requirements
        checks = {
            "candidate_exists": True,
            "interview_token_exists": bool(candidate.interview_token),
            "resume_file_exists": bool(candidate.resume_path and os.path.exists(candidate.resume_path)),
            "heygen_api_configured": bool(os.getenv('HEYGEN_API_KEY')),
            "job_title_available": bool(candidate.job_title),
            "company_name_available": bool(getattr(candidate, 'company_name', None) or os.getenv('COMPANY_NAME'))
        }
        
        # Try to extract resume content
        resume_content = ""
        if checks["resume_file_exists"]:
            resume_content = extract_resume_content_enhanced(candidate.resume_path)
            checks["resume_extractable"] = len(resume_content) > 0
        else:
            checks["resume_extractable"] = False
        
        # Check if KB already exists
        checks["kb_already_exists"] = bool(candidate.knowledge_base_id)
        
        # Overall readiness
        critical_checks = ["candidate_exists", "interview_token_exists", "heygen_api_configured", "job_title_available"]
        all_critical_passed = all(checks[check] for check in critical_checks)
        
        return jsonify({
            "candidate_id": candidate_id,
            "candidate_name": candidate.name,
            "ready_for_kb_creation": all_critical_passed,
            "checks": checks,
            "resume_content_length": len(resume_content),
            "existing_kb_id": candidate.knowledge_base_id,
            "recommendations": generate_kb_recommendations(checks)
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/test-kb-creation/<int:candidate_id>', methods=['POST', 'OPTIONS'])
def test_kb_creation(candidate_id):
    """Test knowledge base creation for debugging"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Step 1: Validate candidate
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            if not candidate:
                return jsonify({"error": "Candidate not found"}), 404
            
            test_results = {
                "candidate_info": {
                    "id": candidate.id,
                    "name": candidate.name,
                    "email": candidate.email,
                    "job_title": candidate.job_title
                }
            }
            
            # Step 2: Test resume extraction
            resume_content = ""
            if candidate.resume_path:
                resume_content = extract_resume_content_enhanced(candidate.resume_path)
                test_results["resume_extraction"] = {
                    "success": len(resume_content) > 0,
                    "content_length": len(resume_content),
                    "file_path": candidate.resume_path,
                    "preview": resume_content[:200] + "..." if resume_content else "No content"
                }
            
            # Step 3: Test HeyGen API connection
            heygen_key = os.getenv('HEYGEN_API_KEY')
            if heygen_key:
                try:
                    # Test with a simple knowledge base
                    test_kb_content = f"Test knowledge base for {candidate.name}"
                    
                    test_response = requests.post(
                        'https://api.heygen.com/v1/streaming/knowledge_base',
                        headers={
                            'X-Api-Key': heygen_key,
                            'Content-Type': 'application/json'
                        },
                        json={
                            'name': f'Test_KB_{candidate.id}_{int(time.time())}',
                            'description': 'Test knowledge base',
                            'content': test_kb_content
                        },
                        timeout=30
                    )
                    
                    test_results["heygen_api_test"] = {
                        "success": test_response.ok,
                        "status_code": test_response.status_code,
                        "response_preview": test_response.text[:500]
                    }
                    
                    if test_response.ok:
                        kb_data = test_response.json()
                        test_kb_id = kb_data.get('data', {}).get('knowledge_base_id')
                        if test_kb_id:
                            test_results["heygen_api_test"]["kb_id_created"] = test_kb_id
                
                except Exception as e:
                    test_results["heygen_api_test"] = {
                        "success": False,
                        "error": str(e)
                    }
            else:
                test_results["heygen_api_test"] = {
                    "success": False,
                    "error": "HEYGEN_API_KEY not configured"
                }
            
            return jsonify({
                "success": True,
                "test_results": test_results,
                "ready_for_production": (
                    test_results.get("heygen_api_test", {}).get("success", False) and
                    test_results.get("resume_extraction", {}).get("success", False)
                )
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"KB creation test failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@interview_core_bp.route('/api/interview/question/add', methods=['POST', 'OPTIONS'])
@rate_limit(max_calls=50, time_window=60)
def add_interview_question():
    """Add a question asked by the avatar during interview"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        session_id = data.get('session_id')
        question_data = data.get('question_data', {})
        
        if not session_id or not question_data.get('text'):
            return jsonify({"success": False, "message": "session_id and question_data.text are required"}), 400
        
        # Import session manager
        from interview_session_manager import interview_session_manager
        
        # Add question to session
        question_id = interview_session_manager.add_interview_question(session_id, question_data)
        
        if question_id:
            return jsonify({
                "success": True,
                "question_id": question_id,
                "message": "Question added successfully"
            }), 200
        else:
            return jsonify({"success": False, "message": "Failed to add question"}), 500
            
    except Exception as e:
        logger.error(f"Error adding interview question: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@interview_core_bp.route('/api/interview/answer/add', methods=['POST', 'OPTIONS'])
@rate_limit(max_calls=50, time_window=60)
def add_interview_answer():
    """Add a candidate's answer during interview"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        session_id = data.get('session_id')
        question_id = data.get('question_id')
        answer_data = data.get('answer_data', {})
        
        if not session_id or not question_id or not answer_data.get('text'):
            return jsonify({"success": False, "message": "session_id, question_id, and answer_data.text are required"}), 400
        
        # Import session manager
        from interview_session_manager import interview_session_manager
        
        # Add answer to session
        answer_id = interview_session_manager.add_interview_answer(session_id, question_id, answer_data)
        
        if answer_id:
            return jsonify({
                "success": True,
                "answer_id": answer_id,
                "message": "Answer added successfully"
            }), 200
        else:
            return jsonify({"success": False, "message": "Failed to add answer"}), 500
            
    except Exception as e:
        logger.error(f"Error adding interview answer: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    
@interview_core_bp.route('/api/interview/session/end', methods=['POST', 'OPTIONS'])
def end_interview_session():
    """End the interview session"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({"error": "session_id is required"}), 400
        
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(
                interview_session_id=session_id
            ).first()
            
            if not candidate:
                return jsonify({"error": "Session not found"}), 404
            
            # Update session status
            candidate.interview_completed_at = datetime.now()
            candidate.interview_status = 'completed'
            
            # Calculate duration
            if candidate.interview_started_at:
                duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                candidate.interview_duration = int(duration)
            
            session.commit()
            
            # Clear caches
            cache.delete_memoized(get_cached_candidates)
            
            logger.info(f"Interview session ended: {session_id}")
            
            return jsonify({
                "success": True,
                "message": "Interview session ended successfully",
                "session_id": session_id,
                "duration": getattr(candidate, 'interview_duration', 0)
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error ending interview session: {e}")
        return jsonify({"error": str(e)}), 500
    
@interview_core_bp.route('/api/interview/analysis/<int:candidate_id>', methods=['GET'])
@cache.memoize(timeout=30)
def get_interview_analysis_production(candidate_id):
    """Get analysis results with caching"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Parse stored data
        strengths = []
        weaknesses = []
        recommendations = []
        
        try:
            if candidate.interview_strengths:
                strengths = json.loads(candidate.interview_strengths)
            if candidate.interview_weaknesses:
                weaknesses = json.loads(candidate.interview_weaknesses)
            if candidate.interview_recommendations:
                recommendations = json.loads(candidate.interview_recommendations)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON data for candidate {candidate_id}")
        
        analysis_data = {
            "candidate_id": candidate_id,
            "status": candidate.interview_ai_analysis_status,
            "scores": {
                "overall": candidate.interview_ai_score,
                "technical": candidate.interview_ai_technical_score,
                "communication": candidate.interview_ai_communication_score,
                "problem_solving": candidate.interview_ai_problem_solving_score,
                "cultural_fit": candidate.interview_ai_cultural_fit_score
            },
            "insights": {
                "strengths": strengths,
                "weaknesses": weaknesses,
                "recommendations": recommendations
            },
            "feedback": candidate.interview_ai_overall_feedback,
            "confidence": candidate.interview_confidence_score,
            "method": candidate.interview_scoring_method,
            "final_status": candidate.interview_final_status,
            "analyzed_at": candidate.interview_analysis_completed_at.isoformat() if candidate.interview_analysis_completed_at else None
        }
        
        return jsonify(analysis_data), 200
        
    except Exception as e:
        logger.error(f"Error getting analysis: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/verify-kb-creation/<int:candidate_id>', methods=['GET'])
def verify_kb_creation(candidate_id):
    """Verify knowledge base creation for a candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Check if we can extract resume
        resume_content = ""
        if candidate.resume_path and os.path.exists(candidate.resume_path):
            resume_content = extract_resume_content(candidate.resume_path)
        
        # Safely get knowledge_base_id using getattr
        knowledge_base_id = getattr(candidate, 'knowledge_base_id', None)
        interview_scheduled = getattr(candidate, 'interview_scheduled', False)
        job_description_available = bool(getattr(candidate, 'job_description', None))
        
        return jsonify({
            "candidate_id": candidate.id,
            "name": candidate.name,
            "resume_path": candidate.resume_path,
            "resume_exists": bool(candidate.resume_path and os.path.exists(candidate.resume_path)),
            "resume_content_length": len(resume_content),
            "resume_preview": resume_content[:500] + "..." if resume_content else "No content",
            "knowledge_base_id": knowledge_base_id,
            "interview_scheduled": interview_scheduled,
            "job_description_available": job_description_available,
            "database_ready": True
        }), 200
    except Exception as e:
        logger.error(f"Error in verify_kb_creation: {e}", exc_info=True)
        return jsonify({
            "error": str(e),
            "message": "Database schema may need updating. Run migration script."
        }), 500
    finally:
        session.close()

@interview_core_bp.route('/api/force-create-kb/<int:candidate_id>', methods=['POST'])
def force_create_kb(candidate_id):
    """Force create knowledge base for a candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Extract resume
        resume_content = ""
        if candidate.resume_path and os.path.exists(candidate.resume_path):
            resume_content = extract_resume_content(candidate.resume_path)
        
        # Try to create HeyGen KB
        kb_id = create_heygen_knowledge_base(
            candidate_name=candidate.name,
            position=candidate.job_title or "Software Engineer",
            resume_content=resume_content,
            company=os.getenv('COMPANY_NAME', 'Our Company')
        )
        
        # Check if HeyGen succeeded
        method = "heygen"
        if not kb_id or kb_id.startswith('kb_fallback'):
            method = "fallback"
            if not kb_id:
                kb_id = f"kb_fallback_{candidate.id}_{int(time.time())}"
        
        # Update candidate
        candidate.interview_kb_id = kb_id
        session.commit()
        
        # Clear cache
        cache.delete_memoized(get_cached_candidates)
        
        return jsonify({
            "success": True,
            "knowledge_base_id": kb_id,
            "resume_extracted": len(resume_content) > 0,
            "method": method
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/check-interview-issues', methods=['GET'])
def check_interview_issues():
    """Check for all interview-related issues"""
    session = SessionLocal()
    try:
        issues = {
            "missing_kb": [],
            "missing_token": [],
            "missing_resume": [],
            "expired_interviews": []
        }
        
        # Get all scheduled interviews
        candidates = session.query(Candidate).filter(
            Candidate.interview_scheduled == True
        ).all()
        
        for candidate in candidates:
            candidate_info = {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "job_title": candidate.job_title
            }
            
            # Check for missing KB using interview_kb_id
            if not candidate.interview_kb_id:
                issues["missing_kb"].append(candidate_info)
            
            # Check for missing token
            if not candidate.interview_token:
                issues["missing_token"].append(candidate_info)
            
            # Check for missing resume
            if not candidate.resume_path or not os.path.exists(candidate.resume_path):
                issues["missing_resume"].append(candidate_info)
            
            # Check for expired interviews
            if candidate.interview_expires_at and candidate.interview_expires_at < datetime.now():
                issues["expired_interviews"].append(candidate_info)
        
        summary = {
            "total_scheduled_interviews": len(candidates),
            "issues_found": {
                "missing_knowledge_bases": len(issues["missing_kb"]),
                "missing_tokens": len(issues["missing_token"]),
                "missing_resumes": len(issues["missing_resume"]),
                "expired_interviews": len(issues["expired_interviews"])
            },
            "details": issues
        }
        
        return jsonify(summary), 200
        
    except Exception as e:
        logger.error(f"Error checking interview issues: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/realtime-analysis', methods=['GET'])
def get_realtime_analysis_status():
    """Get real-time analysis status for all pending interviews"""
    session = SessionLocal()
    try:
        pending = session.query(Candidate).filter(
            Candidate.interview_completed_at.isnot(None),
            Candidate.interview_ai_analysis_status.in_(['pending', 'processing'])
        ).all()
        
        results = []
        for candidate in pending:
            # Calculate progress
            progress = 0
            if candidate.interview_ai_analysis_status == 'processing':
                progress = 50
            
            results.append({
                'candidate_id': candidate.id,
                'name': candidate.name,
                'status': candidate.interview_ai_analysis_status,
                'progress': progress,
                'completed_at': candidate.interview_completed_at.isoformat()
            })
        
        return jsonify({
            'success': True,
            'pending_analyses': results
        }), 200
        
    finally:
        session.close()
        
# Add these endpoints to your backend.py file

@interview_core_bp.route('/api/interview/complete/<token>', methods=['POST', 'OPTIONS'])
@cross_origin()
def complete_interview_by_token(token):
    """Complete an interview with automatic database update"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Get request data
        data = request.json or {}
        trigger_source = data.get('completion_trigger', 'manual')
        
        # Use the completion handler
        result = completion_handler.complete_interview(token, trigger_source)
        
        if result["success"]:
            # Clear cache to update frontend
            cache.delete_memoized(get_cached_candidates)
            
            return jsonify({
                "success": True,
                "message": "Interview completed and saved to database",
                **result
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error")
            }), 500
            
    except Exception as e:
        logger.error(f"Error in complete endpoint: {e}")
        return jsonify({"error": str(e)}), 500
    
@interview_core_bp.route('/api/interview/realtime-complete', methods=['POST'])
def realtime_complete():
    """Handle real-time completion from frontend"""
    try:
        data = request.json
        token = data.get('token')
        session_id = data.get('session_id')
        
        if not token:
            return jsonify({"error": "Token required"}), 400
        
        # Complete the interview
        result = completion_handler.complete_interview(token, "realtime_trigger")
        
        if result["success"]:
            # Also update session if provided
            if session_id:
                session = SessionLocal()
                try:
                    candidate = session.query(Candidate).filter_by(
                        interview_token=token
                    ).first()
                    if candidate:
                        candidate.interview_session_id = session_id
                        session.commit()
                finally:
                    session.close()
            
            return jsonify(result), 200
        else:
            return jsonify(result), 500
            
    except Exception as e:
        logger.error(f"Realtime completion error: {e}")
        return jsonify({"error": str(e)}), 500

@interview_core_bp.route('/api/interview/verify-db-update/<token>', methods=['GET'])
def verify_db_update(token):
    """Verify that interview completion is saved in database"""
    session = SessionLocal()
    try:
        # Force fresh read from database
        session.expire_all()
        
        candidate = session.query(Candidate).filter_by(
            interview_token=token
        ).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Also check with direct SQL
        result = session.execute(
            text("""
                SELECT interview_completed_at, interview_status, final_status,
                       interview_progress_percentage, interview_ai_analysis_status
                FROM candidates WHERE interview_token = :token
            """),
            {"token": token}
        ).fetchone()
        
        return jsonify({
            "token": token,
            "candidate_name": candidate.name,
            "orm_data": {
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "status": candidate.interview_status,
                "final_status": candidate.final_status,
                "progress": candidate.interview_progress_percentage,
                "ai_status": candidate.interview_ai_analysis_status
            },
            "direct_sql_data": {
                "completed_at": str(result[0]) if result and result[0] else None,
                "status": result[1] if result else None,
                "final_status": result[2] if result else None,
                "progress": result[3] if result else None,
                "ai_status": result[4] if result else None
            },
            "is_completed": candidate.interview_completed_at is not None
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview/verify-completion/<token>', methods=['GET'])
def verify_completion(token):
    """Verify if interview completion is persisted in database"""
    session = SessionLocal()
    try:
        # Try multiple ways to find the candidate
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            # Try finding by ID if token looks like an ID
            if token.isdigit():
                candidate = session.query(Candidate).filter_by(id=int(token)).first()
        
        if not candidate:
            return jsonify({"error": "Not found", "token": token}), 404
        
        # Force fresh read from database
        session.expire_all()
        session.commit()  # Commit any pending changes
        session.refresh(candidate)
        
        # Get raw SQL value
        from sqlalchemy import text
        raw_result = session.execute(
            text("SELECT interview_completed_at, interview_status, final_status FROM candidates WHERE id = :id"),
            {"id": candidate.id}
        ).fetchone()
        
        return jsonify({
            "candidate_id": candidate.id,
            "name": candidate.name,
            "orm_values": {
                "interview_completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "interview_status": candidate.interview_status,
                "final_status": candidate.final_status,
                "interview_progress_percentage": candidate.interview_progress_percentage
            },
            "raw_sql_values": {
                "interview_completed_at": str(raw_result[0]) if raw_result else None,
                "interview_status": str(raw_result[1]) if raw_result else None,
                "final_status": str(raw_result[2]) if raw_result else None
            },
            "is_completed": candidate.interview_completed_at is not None
        }), 200
        
    except Exception as e:
        logger.error(f"Verification error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/fix-null-completions', methods=['POST'])
def fix_null_completions():
    """Fix interviews that show as NULL in database but should be completed"""
    session = SessionLocal()
    try:
        from datetime import datetime, timezone
        from sqlalchemy import text
        
        # Find candidates with NULL completion but other signs of completion
        result = session.execute(
            text("""
                UPDATE candidates 
                SET interview_completed_at = CURRENT_TIMESTAMP,
                    interview_status = 'completed',
                    final_status = 'Interview Completed',
                    interview_progress_percentage = 100
                WHERE interview_completed_at IS NULL
                AND (
                    interview_progress_percentage >= 100
                    OR interview_status = 'completed'
                    OR final_status LIKE '%Completed%'
                    OR interview_total_questions > 0
                )
            """)
        )
        
        rows_updated = result.rowcount
        session.commit()
        
        # Clear all caches
        cache.clear()
        
        return jsonify({
            "success": True,
            "rows_fixed": rows_updated,
            "message": f"Fixed {rows_updated} interviews with NULL completion dates"
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Fix failed: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/check-incomplete', methods=['POST'])
def check_incomplete_interviews():
    """Check and fix incomplete interviews"""
    session = SessionLocal()
    fixed = 0
    
    try:
        # Find interviews that should be complete
        candidates = session.query(Candidate).filter(
            Candidate.interview_started_at.isnot(None),
            Candidate.interview_completed_at.is_(None)
        ).all()
        
        for candidate in candidates:
            # Get Q&A data
            questions = json.loads(candidate.interview_questions_asked or '[]')
            answers = json.loads(candidate.interview_answers_given or '[]')
            
            # Check if should be complete
            should_complete = False
            
            # Has enough Q&A
            if len(questions) >= 5 and len(answers) >= len(questions) * 0.8:
                should_complete = True
            
            # Or has been inactive for too long
            if candidate.interview_started_at:
                time_since = (datetime.now() - candidate.interview_started_at).total_seconds()
                if time_since > 7200:  # 2 hours
                    should_complete = True
            
            if should_complete:
                candidate.interview_completed_at = datetime.now()
                candidate.interview_status = 'completed'
                candidate.interview_progress_percentage = 100
                candidate.interview_ai_analysis_status = 'pending'
                fixed += 1
                logger.info(f"Fixed incomplete interview for {candidate.name}")
        
        session.commit()
        
        return jsonify({
            "success": True,
            "checked": len(candidates),
            "fixed": fixed
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error checking incomplete: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/check-completion/<token>', methods=['GET'])
def check_interview_completion(token):
    """Check if interview is properly marked as complete"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Interview not found"}), 404
        
        # Get Q&A data
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        questions = json.loads(candidate.interview_questions_asked or '[]')
        answers = json.loads(candidate.interview_answers_given or '[]')
        
        return jsonify({
            "token": token,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email
            },
            "completion_status": {
                "is_completed": candidate.interview_completed_at is not None,
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "duration": candidate.interview_duration,
                "progress": candidate.interview_progress_percentage,
                "status": candidate.interview_status,
                "final_status": candidate.final_status
            },
            "qa_stats": {
                "total_questions": len(questions),
                "total_answers": len(answers),
                "qa_pairs": len(qa_pairs),
                "stored_total": candidate.interview_total_questions,
                "stored_answered": candidate.interview_answered_questions
            },
            "ai_analysis": {
                "status": candidate.interview_ai_analysis_status,
                "score": candidate.interview_ai_score,
                "triggered": candidate.interview_auto_score_triggered
            }
        }), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview/fix-by-token/<token>', methods=['POST'])
def fix_interview_by_token(token):
    """Emergency fix for a specific interview"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Force complete if it has Q&A data but not marked complete
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        
        if qa_pairs and not candidate.interview_completed_at:
            candidate.interview_completed_at = datetime.now()
            candidate.interview_status = 'completed'
            candidate.interview_progress_percentage = 100
            candidate.final_status = 'Interview Completed'
            
            if candidate.interview_started_at:
                duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                candidate.interview_duration = int(duration)
            
            candidate.interview_ai_analysis_status = 'pending'
            session.commit()
            
            # Trigger scoring
            trigger_auto_scoring(candidate.id)
            
            return jsonify({
                "success": True,
                "message": "Interview fixed and marked as complete",
                "candidate": candidate.name
            }), 200
        else:
            return jsonify({
                "message": "No fix needed",
                "has_qa_data": len(qa_pairs) > 0,
                "already_completed": candidate.interview_completed_at is not None
            }), 200
            
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/tracking-status/<token>', methods=['GET'])
def get_interview_tracking_status(token):
    """Get comprehensive tracking status for an interview"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()

        if not candidate:
            return jsonify({"error": "Interview not found"}), 404

        # Calculate status
        status = 'not_started'
        if candidate.interview_completed_at:
            status = 'completed'
        elif candidate.interview_status == 'expired':
            status = 'expired'
        elif candidate.interview_status == 'abandoned':
            status = 'abandoned'
        elif candidate.interview_started_at:
            status = 'in_progress'
        elif candidate.interview_link_clicked:
            status = 'link_clicked'

        # Time calculations
        time_remaining = None
        if candidate.interview_expires_at and not candidate.interview_completed_at:
            time_remaining = (candidate.interview_expires_at - datetime.now()).total_seconds()
            if time_remaining < 0:
                time_remaining = 0

        tracking_data = {
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title
            },
            "status": status,
            "tracking": {
                "link_clicked": bool(candidate.interview_link_clicked),
                "link_clicked_at": candidate.interview_link_clicked_at.isoformat() if candidate.interview_link_clicked_at else None,
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "last_activity": candidate.interview_last_activity.isoformat() if candidate.interview_last_activity else None,
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "expires_at": candidate.interview_expires_at.isoformat() if candidate.interview_expires_at else None,
                "time_remaining_seconds": time_remaining
            },
            "progress": {
                "percentage": candidate.interview_progress_percentage or 0,
                "total_questions": candidate.interview_total_questions or 0,
                "answered_questions": candidate.interview_answered_questions or 0,
                "qa_completion_rate": candidate.interview_qa_completion_rate or 0
            },
            "analysis": {
                "status": candidate.interview_ai_analysis_status,
                "score": candidate.interview_ai_score,
                "recommendation": candidate.interview_final_status
            },
            "technical": {
                "session_id": candidate.interview_session_id,
                "browser_info": candidate.interview_browser_info,
                "duration_seconds": candidate.interview_duration
            }
        }

        return jsonify(tracking_data), 200

    except Exception as e:
        logger.error(f"Error getting tracking status: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/validate-completion/<token>', methods=['POST'])
def validate_interview_completion(token):
    """Validate and ensure interview is properly marked as complete"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if not candidate:
            return jsonify({"error": "Interview not found"}), 404
        
        # Force completion check
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        questions = json.loads(candidate.interview_questions_asked or '[]')
        answers = json.loads(candidate.interview_answers_given or '[]')
        
        issues = []
        
        # Check for completion criteria
        if len(questions) < 5:
            issues.append("Less than 5 questions asked")
        
        if len(answers) < len(questions) * 0.8:  # 80% answer rate
            issues.append(f"Low answer rate: {len(answers)}/{len(questions)}")
        
        # Initialize inactive_time with a default value
        inactive_time = 0
        
        # Check for recent activity
        if hasattr(candidate, 'interview_last_activity') and candidate.interview_last_activity:
            inactive_time = (datetime.now() - candidate.interview_last_activity).total_seconds()
            if inactive_time > 3600:  # 1 hour
                issues.append("No activity for over 1 hour")
        
        # Force completion if criteria met
        should_complete = False
        if not candidate.interview_completed_at:
            if len(questions) >= 10 and len(answers) >= len(questions) - 1:
                should_complete = True
                logger.info(f"Completion criteria met: 10+ questions with most answered")
            elif inactive_time > 3600 and len(questions) >= 5:
                should_complete = True
                logger.info(f"Completion criteria met: Inactive for 1hr with 5+ questions")
            elif len(questions) >= 5 and len(answers) >= len(questions) * 0.8:
                should_complete = True
                logger.info(f"Completion criteria met: 5+ questions with 80% answered")
        
        if should_complete:
            candidate.interview_completed_at = datetime.now()
            candidate.interview_status = 'completed'
            candidate.interview_progress_percentage = 100
            
            if candidate.interview_started_at:
                duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                candidate.interview_duration = int(duration)
            
            candidate.interview_ai_analysis_status = 'pending'
            session.commit()
            
            logger.info(f"Interview force completed for {candidate.name} (ID: {candidate.id})")
            
            # Trigger scoring
            try:
                trigger_auto_scoring(candidate.id)
            except Exception as e:
                logger.error(f"Failed to trigger auto scoring: {e}")
            
            return jsonify({
                "success": True,
                "message": "Interview marked as complete",
                "forced_completion": True,
                "issues": issues
            }), 200
        
        return jsonify({
            "success": True,
            "message": "Interview status validated",
            "is_complete": candidate.interview_completed_at is not None,
            "issues": issues,
            "stats": {
                "questions": len(questions),
                "answers": len(answers),
                "inactive_minutes": int(inactive_time / 60) if inactive_time else 0
            }
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error validating completion: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/cleanup-incomplete', methods=['POST'])
def cleanup_incomplete_interviews():
    """Fix interviews that show as completed in UI but not in database"""
    session = SessionLocal()
    fixed_count = 0
    
    try:
        # Find candidates with started interviews but no completion
        incomplete = session.query(Candidate).filter(
            Candidate.interview_started_at.isnot(None),
            Candidate.interview_completed_at.is_(None),
            Candidate.interview_token.isnot(None)
        ).all()
        
        for candidate in incomplete:
            # Check if interview is actually complete based on other indicators
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            
            # If they have Q&A data or have been inactive for over 2 hours
            if qa_pairs or (candidate.interview_started_at and 
                          (datetime.now() - candidate.interview_started_at).total_seconds() > 7200):
                
                candidate.interview_completed_at = datetime.now()
                candidate.interview_status = 'completed'
                candidate.interview_progress_percentage = 100
                
                if candidate.interview_started_at:
                    duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                    candidate.interview_duration = int(duration)
                
                candidate.interview_ai_analysis_status = 'pending'
                fixed_count += 1
                
                # Trigger scoring
                trigger_auto_scoring(candidate.id)
                
                logger.info(f"Fixed incomplete interview for {candidate.name} (ID: {candidate.id})")
        
        session.commit()
        
        return jsonify({
            "success": True,
            "fixed_count": fixed_count,
            "message": f"Fixed {fixed_count} incomplete interviews"
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Cleanup error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/debug-status', methods=['GET'])
def debug_interview_status():
    """Debug endpoint to check interview statuses"""
    session = SessionLocal()
    try:
        # Get all interviews with various states
        all_interviews = session.query(Candidate).filter(
            Candidate.interview_scheduled == True
        ).all()
        
        results = {
            "total_scheduled": len(all_interviews),
            "breakdown": {
                "completed_with_score": 0,
                "completed_no_score": 0,
                "started_not_completed": 0,
                "scheduled_not_started": 0,
                "has_qa_data": 0
            },
            "details": []
        }
        
        for candidate in all_interviews:
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            
            status = "unknown"
            if candidate.interview_completed_at and candidate.interview_ai_score:
                status = "completed_with_score"
                results["breakdown"]["completed_with_score"] += 1
            elif candidate.interview_completed_at and not candidate.interview_ai_score:
                status = "completed_no_score"
                results["breakdown"]["completed_no_score"] += 1
            elif candidate.interview_started_at and not candidate.interview_completed_at:
                status = "started_not_completed"
                results["breakdown"]["started_not_completed"] += 1
            elif not candidate.interview_started_at:
                status = "scheduled_not_started"
                results["breakdown"]["scheduled_not_started"] += 1
            
            if qa_pairs:
                results["breakdown"]["has_qa_data"] += 1
            
            results["details"].append({
                "id": candidate.id,
                "name": candidate.name,
                "status": status,
                "scheduled": candidate.interview_scheduled,
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "ai_score": candidate.interview_ai_score,
                "ai_analysis_status": candidate.interview_ai_analysis_status,
                "auto_score_triggered": candidate.interview_auto_score_triggered,
                "qa_pairs_count": len(qa_pairs),
                "final_status": candidate.final_status
            })
        
        return jsonify(results), 200
        
    finally:
        session.close()

@interview_core_bp.route('/api/interview/fix-incomplete-interviews', methods=['POST'])
def fix_incomplete_interviews():
    """Fix interviews that have Q&A data but aren't marked as complete"""
    session = SessionLocal()
    fixed = 0
    
    try:
        # Find all scheduled interviews
        candidates = session.query(Candidate).filter(
            Candidate.interview_scheduled == True
        ).all()
        
        for candidate in candidates:
            # Check if they have Q&A data
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            questions_asked = json.loads(candidate.interview_questions_asked or '[]')
            answers_given = json.loads(candidate.interview_answers_given or '[]')
            
            # If they have Q&A data but no completion timestamp, mark as complete
            if (qa_pairs or questions_asked) and not candidate.interview_completed_at:
                candidate.interview_completed_at = datetime.now()
                candidate.interview_status = 'completed'
                candidate.interview_progress_percentage = 100
                
                # Calculate duration if we have start time
                if candidate.interview_started_at:
                    duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                    candidate.interview_duration = int(duration)
                
                # Set for AI analysis
                candidate.interview_ai_analysis_status = 'pending'
                candidate.interview_auto_score_triggered = False
                candidate.final_status = 'Interview Completed - Pending Analysis'
                
                session.commit()
                
                # Now trigger the scoring
                trigger_auto_scoring(candidate.id)
                
                fixed += 1
                logger.info(f"Fixed and triggered analysis for {candidate.name} (ID: {candidate.id})")
        
        # Clear cache
        cache.delete_memoized(get_cached_candidates)
        
        return jsonify({
            "success": True,
            "fixed": fixed,
            "checked": len(candidates),
            "message": f"Fixed {fixed} incomplete interviews"
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error fixing incomplete interviews: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/force-score/<int:candidate_id>', methods=['POST'])
def force_score_candidate(candidate_id):
    """Force score a specific candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Mark as completed if not already
        if not candidate.interview_completed_at:
            candidate.interview_completed_at = datetime.now()
            candidate.interview_status = 'completed'
            candidate.interview_progress_percentage = 100
        
        # Reset analysis flags
        candidate.interview_ai_analysis_status = 'pending'
        candidate.interview_auto_score_triggered = False
        
        session.commit()
        
        # Trigger scoring
        trigger_auto_scoring(candidate_id)
        
        return jsonify({
            "success": True,
            "message": f"Triggered scoring for {candidate.name}",
            "candidate_id": candidate_id
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error forcing score: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/check-analysis/<int:candidate_id>', methods=['GET'])
def check_analysis_status(candidate_id):
    """Check detailed analysis status for a candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        return jsonify({
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email
            },
            "interview": {
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "duration": candidate.interview_duration,
                "progress": candidate.interview_progress_percentage
            },
            "analysis": {
                "status": candidate.interview_ai_analysis_status,
                "triggered": candidate.interview_auto_score_triggered,
                "scores": {
                    "overall": candidate.interview_ai_score,
                    "technical": candidate.interview_ai_technical_score,
                    "communication": candidate.interview_ai_communication_score,
                    "problem_solving": candidate.interview_ai_problem_solving_score,
                    "cultural_fit": candidate.interview_ai_cultural_fit_score
                },
                "feedback": candidate.interview_ai_overall_feedback,
                "final_status": candidate.interview_final_status,
                "strengths": json.loads(candidate.interview_ai_strengths or '[]'),
                "weaknesses": json.loads(candidate.interview_ai_weaknesses or '[]')
            },
            "qa_data": {
                "qa_pairs": len(json.loads(candidate.interview_qa_pairs or '[]')),
                "questions_asked": len(json.loads(candidate.interview_questions_asked or '[]')),
                "answers_given": len(json.loads(candidate.interview_answers_given or '[]'))
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error checking analysis: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/interview/recording/<int:candidate_id>', methods=['GET'])
def get_interview_recording_info(candidate_id):
    """Get interview recording information"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        recording_info = {
            "recording_file": candidate.interview_recording_file,
            "recording_duration": candidate.interview_recording_duration,
            "recording_size": candidate.interview_recording_size,
            "recording_format": candidate.interview_recording_format,
            "recording_quality": candidate.interview_recording_quality,
            "recording_status": candidate.interview_recording_status,
            "session_id": candidate.interview_session_id,
            "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
            "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None
        }
        
        return jsonify({
            "success": True,
            "candidate_id": candidate_id,
            "recording_info": recording_info
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting recording info: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        session.close()

@interview_core_bp.route('/api/routes', methods=['GET'])
def list_routes():
    """Debug endpoint to list all available routes"""
    routes = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            routes.append({
                'endpoint': rule.endpoint,
                'methods': list(rule.methods),
                'rule': str(rule)
            })
    return jsonify({
        "total_routes": len(routes),
        "routes": sorted(routes, key=lambda x: x['rule'])
    }), 200

@interview_core_bp.route('/api/interview/speech/track', methods=['POST', 'OPTIONS'])
@cross_origin()
def track_speech_segment():
    """Track speech recognition segments with confidence scores"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        session_id = data.get('session_id')
        segment = data.get('segment', {})
        
        if not session_id:
            return jsonify({"error": "session_id required"}), 400
        
        session = SessionLocal()
        try:
            # Find candidate
            candidate = session.query(Candidate).filter_by(
                interview_session_id=session_id
            ).first()
            
            if not candidate:
                # Try alternate lookup
                parts = session_id.split('_')
                if len(parts) >= 2 and parts[1].isdigit():
                    candidate = session.query(Candidate).filter_by(id=int(parts[1])).first()
            
            if not candidate:
                return jsonify({"error": "Session not found"}), 404
            
            # Parse existing speech data
            speech_segments = json.loads(getattr(candidate, 'interview_speech_segments', '[]'))
            
            # Add new segment
            segment_data = {
                'id': f"seg_{len(speech_segments)}_{int(time.time())}",
                'text': segment.get('text', ''),
                'confidence': segment.get('confidence', 0),
                'is_final': segment.get('is_final', False),
                'timestamp': segment.get('timestamp', datetime.now().isoformat()),
                'duration_ms': segment.get('duration', 0)
            }
            
            speech_segments.append(segment_data)
            
            # Store segments
            if hasattr(candidate, 'interview_speech_segments'):
                candidate.interview_speech_segments = json.dumps(speech_segments)
            
            # Update transcript
            if segment.get('is_final'):
                transcript = candidate.interview_transcript or ""
                transcript += f"\n[Candidate]: {segment.get('text', '')}\n"
                candidate.interview_transcript = transcript
            
            # Update last activity
            candidate.interview_last_activity = datetime.now()
            
            session.commit()
            
            return jsonify({
                "success": True,
                "segment_id": segment_data['id'],
                "total_segments": len(speech_segments)
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Speech tracking error: {e}")
        return jsonify({"error": str(e)}), 500

@interview_core_bp.route('/api/interview/speech/complete-utterance', methods=['POST', 'OPTIONS'])
@cross_origin()
def track_complete_utterance():
    """Track a complete utterance (full answer)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        session_id = data.get('session_id')
        utterance = data.get('utterance', {})
        
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(
                interview_session_id=session_id
            ).first()
            
            if not candidate:
                return jsonify({"error": "Session not found"}), 404
            
            # Find the current unanswered question
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            
            for qa in reversed(qa_pairs):
                if qa.get('question') and not qa.get('answer'):
                    # Found unanswered question - add answer
                    qa['answer'] = utterance.get('text', '')
                    qa['answer_confidence'] = utterance.get('confidence', 0)
                    qa['answer_timestamp'] = utterance.get('timestamp')
                    qa['answer_duration_ms'] = utterance.get('duration')
                    break
            
            # Update database
            candidate.interview_qa_pairs = json.dumps(qa_pairs)
            
            # Update answer count
            answered = sum(1 for qa in qa_pairs if qa.get('answer'))
            candidate.interview_answered_questions = answered
            
            # Update progress
            if candidate.interview_total_questions > 0:
                progress = (answered / candidate.interview_total_questions) * 100
                candidate.interview_progress_percentage = progress
            
            session.commit()
            
            # Check for auto-completion
            if answered >= 10 or (candidate.interview_total_questions > 0 and 
                                  answered >= candidate.interview_total_questions):
                # Trigger completion
                executor.submit(check_and_complete_interview, candidate.id)
            
            return jsonify({
                "success": True,
                "answered_questions": answered,
                "progress": candidate.interview_progress_percentage
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Utterance tracking error: {e}")
        return jsonify({"error": str(e)}), 500

@interview_core_bp.route('/api/interview/migrate-qa-data', methods=['POST'])
def migrate_qa_data():
    """Migrate Q&A data from qa_pairs to questions/answers format"""
    session = SessionLocal()
    migrated = []
    
    try:
        candidates = session.query(Candidate).filter(
            Candidate.interview_scheduled == True
        ).all()
        
        for candidate in candidates:
            changes = []
            
            # Parse existing data
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            questions = json.loads(candidate.interview_questions_asked or '[]')
            answers = json.loads(candidate.interview_answers_given or '[]')
            
            # If qa_pairs exist but questions/answers are empty, migrate
            if qa_pairs and not questions:
                new_questions = []
                new_answers = []
                
                for qa in qa_pairs:
                    if qa.get('question'):
                        new_questions.append({
                            'id': qa.get('id'),
                            'text': qa.get('question'),
                            'timestamp': qa.get('timestamp'),
                            'order': qa.get('order', len(new_questions) + 1)
                        })
                        
                    if qa.get('answer'):
                        new_answers.append({
                            'id': qa.get('id'),
                            'text': qa.get('answer'),
                            'timestamp': qa.get('answered_at', qa.get('timestamp')),
                            'question_order': qa.get('order', len(new_answers) + 1)
                        })
                
                # Update the database
                candidate.interview_questions_asked = json.dumps(new_questions)
                candidate.interview_answers_given = json.dumps(new_answers)
                candidate.interview_total_questions = len(new_questions)
                candidate.interview_answered_questions = len(new_answers)
                
                changes.append(f"Migrated {len(new_questions)} questions and {len(new_answers)} answers")
            
            # Fix counts based on actual data
            actual_questions = max(
                len(qa_pairs),
                len(questions),
                candidate.interview_total_questions or 0
            )
            actual_answers = len([qa for qa in qa_pairs if qa.get('answer')]) or len(answers)
            
            if candidate.interview_total_questions != actual_questions:
                candidate.interview_total_questions = actual_questions
                changes.append(f"Fixed total questions: {actual_questions}")
            
            if candidate.interview_answered_questions != actual_answers:
                candidate.interview_answered_questions = actual_answers
                changes.append(f"Fixed answered questions: {actual_answers}")
            
            # Ensure completed interviews have completion timestamp
            if actual_questions > 0 and not candidate.interview_completed_at:
                if candidate.interview_started_at:
                    # Check if it's been more than 30 minutes
                    time_since = (datetime.now() - candidate.interview_started_at).total_seconds()
                    if time_since > 1800:  # 30 minutes
                        candidate.interview_completed_at = datetime.now()
                        candidate.interview_progress_percentage = 100
                        changes.append("Marked as completed (timeout)")
            
            if changes:
                migrated.append({
                    'id': candidate.id,
                    'name': candidate.name,
                    'changes': changes
                })
        
        session.commit()
        
        # Clear cache
        cache.clear()
        
        return jsonify({
            'success': True,
            'migrated_count': len(migrated),
            'details': migrated
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error migrating Q&A data: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

request_metrics = {
    'total_requests': 0,
    'avg_response_time': 0,
    'slow_requests': 0
}


@interview_core_bp.route('/health', methods=['GET'])
def health_check():
    """Enhanced health check endpoint with system status"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.1.0",
        "checks": {},
        "performance": {
            "avg_response_time": f"{request_metrics['avg_response_time']:.3f}s",
            "total_requests": request_metrics['total_requests'],
            "slow_requests": request_metrics['slow_requests']
        }
    }
    
    # Check database
    try:
        session = SessionLocal()
        session.execute("SELECT 1")
        session.close()
        health_status["checks"]["database"] = "healthy"
    except Exception as e:
        health_status["checks"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check cache
    try:
        cache.set('health_check', 'ok', timeout=1)
        if cache.get('health_check') == 'ok':
            health_status["checks"]["cache"] = "healthy"
        else:
            health_status["checks"]["cache"] = "unhealthy"
            health_status["status"] = "degraded"
    except Exception as e:
        health_status["checks"]["cache"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check thread pool
    try:
        if hasattr(executor, '_threads'):
            active_threads = len([t for t in executor._threads if t.is_alive()])
            health_status["checks"]["thread_pool"] = f"healthy ({active_threads} active threads)"
        else:
            health_status["checks"]["thread_pool"] = "healthy"
    except Exception as e:
        health_status["checks"]["thread_pool"] = f"degraded: {str(e)}"
    
    return jsonify(health_status), 200 if health_status["status"] == "healthy" else 503
# Request logging
@api_bp.before_app_request
def log_request_info():
    """Log incoming requests"""
    logger.info(f"ðŸŒ {request.method} {request.path} from {request.remote_addr}")

class InterviewErrorRecovery:
    """Handle interview system errors and recovery"""
    
    @staticmethod
    def recover_incomplete_interviews():
        """Recover and complete incomplete interviews"""
        session = SessionLocal()
        try:
            # Find stuck interviews (started > 2 hours ago, not completed)
            cutoff_time = datetime.now() - timedelta(hours=2)
            stuck_interviews = session.query(Candidate).filter(
                Candidate.interview_started_at < cutoff_time,
                Candidate.interview_completed_at.is_(None)
            ).all()
            
            for candidate in stuck_interviews:
                # Check last activity
                if candidate.interview_last_activity:
                    time_since = (datetime.now() - candidate.interview_last_activity).total_seconds()
                    if time_since > 3600:  # No activity for 1 hour
                        # Force complete
                        candidate.interview_completed_at = datetime.now()
                        candidate.interview_ai_analysis_status = 'pending'
                        
                        # Trigger scoring with what we have
                        trigger_auto_scoring(candidate.id)
                        
                        logger.warning(f"Force completed stuck interview for candidate {candidate.id}")
            
            session.commit()
            
        except Exception as e:
            logger.error(f"Error recovering interviews: {e}")
        finally:
            session.close()
    
    @staticmethod
    def validate_interview_data(candidate_id):
        """Validate and fix interview data integrity"""
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            if not candidate:
                return False
            
            issues_fixed = []
            
            # Fix Q&A pairs
            try:
                qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            except:
                qa_pairs = []
                candidate.interview_qa_pairs = '[]'
                issues_fixed.append('Reset invalid Q&A data')
            
            # Fix counts
            if candidate.interview_total_questions != len(qa_pairs):
                candidate.interview_total_questions = len(qa_pairs)
                issues_fixed.append('Fixed question count')
            
            answered = sum(1 for qa in qa_pairs if qa.get('answer'))
            if candidate.interview_answered_questions != answered:
                candidate.interview_answered_questions = answered
                issues_fixed.append('Fixed answer count')
            
            # Fix progress
            if candidate.interview_total_questions > 0:
                progress = (answered / candidate.interview_total_questions) * 100
                if abs(candidate.interview_progress_percentage - progress) > 1:
                    candidate.interview_progress_percentage = progress
                    issues_fixed.append('Fixed progress percentage')
            
            # Fix status inconsistencies
            if candidate.interview_completed_at and not candidate.interview_started_at:
                candidate.interview_started_at = candidate.interview_completed_at - timedelta(minutes=30)
                issues_fixed.append('Fixed missing start time')
            
            if issues_fixed:
                session.commit()
                logger.info(f"Fixed issues for candidate {candidate_id}: {', '.join(issues_fixed)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating interview data: {e}")
            return False
        finally:
            session.close()

@interview_core_bp.route('/api/interview/health-check', methods=['GET'])
def interview_health_check():
    """Check interview system health and recover if needed"""
    try:
        # Run recovery
        InterviewErrorRecovery.recover_incomplete_interviews()
        
        # Get system stats
        session = SessionLocal()
        try:
            stats = {
                'active_interviews': session.query(Candidate).filter(
                    Candidate.interview_started_at.isnot(None),
                    Candidate.interview_completed_at.is_(None)
                ).count(),
                'pending_scoring': session.query(Candidate).filter(
                    Candidate.interview_completed_at.isnot(None),
                    Candidate.interview_ai_score.is_(None)
                ).count(),
                'failed_scoring': session.query(Candidate).filter(
                    Candidate.interview_ai_analysis_status == 'failed'
                ).count(),
                'system_status': 'healthy'
            }
            
            return jsonify(stats), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"error": str(e), "system_status": "unhealthy"}), 500

@interview_core_bp.route('/api/cache/clear', methods=['POST'])
def clear_all_cache():
    """Clear all cached data"""
    try:
        cache.clear()
        return jsonify({"success": True, "message": "Cache cleared"}), 200
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return jsonify({"error": str(e)}), 500

def create_interview_landing_page(interview_data, token):
    """Create the landing page HTML with reconnection support without illegal f-strings."""
    import json
    interview_json = json.dumps(interview_data)

    # Pre-build dynamic fragments (NO backslashes in f-string expressions):
    is_reconnection = bool(interview_data.get('isReconnection'))
    prev = interview_data.get('previousSessionData') or {}
    reconnect_block = ""
    if is_reconnection:
        reconnect_block = (
            "<div class=\"reconnect-info\">"
            "<h3> Welcome Back!</h3>"
            "<p>You're reconnecting to your interview session.</p>"
            f"<p><strong>Questions asked:</strong> {prev.get('questionsAsked', 0)}</p>"
            f"<p><strong>Questions answered:</strong> {prev.get('questionsAnswered', 0)}</p>"
            "</div>"
        )
    session_type_label = "Reconnection" if is_reconnection else "New Session"
    continue_or_start = "Continue" if is_reconnection else "Start"
    continue_lower = "continue" if is_reconnection else "start"
    progress_line = (
        f"<p><strong> Progress:</strong> {prev.get('questionsAnswered', 0)} questions completed</p>"
        if is_reconnection else ""
    )

    # Build the HTML
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    candidate_name = interview_data['candidateName']
    position = interview_data['position']
    company = interview_data['company']
    knowledge_base_id = interview_data.get('knowledgeBaseId', '')
    candidate_id = interview_data['candidateId']

    return f"""<!DOCTYPE html>
<html>
<head>
  <title>AI Interview - {position}</title>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0; padding: 0;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      min-height: 100vh; display: flex; align-items: center; justify-content: center;
    }}
    .container {{
      background: white; padding: 2rem; border-radius: 15px;
      box-shadow: 0 20px 40px rgba(0,0,0,0.1);
      text-align: center; max-width: 600px; width: 90%;
    }}
    .header {{ color: #333; margin-bottom: 1.5rem; }}
    .info-box {{
      background: #f8f9fa; padding: 1.5rem; border-radius: 10px;
      margin: 1rem 0; border-left: 5px solid #667eea;
    }}
    .reconnect-info {{
      background: #e3f2fd; padding: 1rem; border-radius: 8px;
      margin: 1rem 0; border-left: 5px solid #2196f3;
    }}
    .success-badge {{ color: #28a745; font-weight: bold; font-size: 1.1em; }}
    .start-btn {{
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white; padding: 15px 30px; border: none; border-radius: 50px;
      cursor: pointer; font-size: 18px; font-weight: bold; text-decoration: none;
      display: inline-block; margin: 20px 10px; transition: transform 0.3s, box-shadow 0.3s;
    }}
    .start-btn:hover {{ transform: translateY(-2px); box-shadow: 0 10px 25px rgba(102,126,234,0.3); }}
    .instructions {{ text-align: left; margin: 1.5rem 0; padding: 1.5rem; background: #e3f2fd; border-radius: 10px; }}
    .debug-info {{ background: #fff3cd; padding: 1rem; border-radius: 8px; font-size: 14px; margin-top: 15px; text-align: left; }}
  </style>
</head>
<body>
  <div class="container">
    <h1 class="header">ðŸ¤– AI Interview Portal</h1>

    {reconnect_block}

    <div class="info-box">
      <p><strong> Candidate:</strong> {candidate_name}</p>
      <p><strong> Position:</strong> {position}</p>
      <p><strong> Company:</strong> {company}</p>
      <p class="success-badge"> Interview Link Active & Ready</p>
      <p><strong> Session Type:</strong> {session_type_label}</p>
    </div>

    <div class="instructions">
      <h3> Before {continue_or_start} Your Interview:</h3>
      <ul>
        <li><strong>Internet:</strong> Ensure stable connection</li>
        <li><strong>Camera & Mic:</strong> Test and allow permissions</li>
        <li><strong>Environment:</strong> Find a quiet, well-lit space</li>
        <li><strong>Materials:</strong> Have your resume ready</li>
      </ul>
    </div>

    <div style="margin: 25px 0;">
      <p><strong>â± Duration:</strong> 30-45 minutes</p>
      <p><strong> Format:</strong> AI-powered video interview</p>
      {progress_line}
    </div>

    <button onclick="startInterview()" class="start-btn"> {continue_or_start} AI Interview</button>

    <div class="debug-info">
      <strong> System Status:</strong><br/>
      Token: {token}<br/>
      Knowledge Base: {knowledge_base_id}<br/>
      Candidate ID: {candidate_id}<br/>
      Status: Ready <br/>
      Session Type: {session_type_label}<br/>
      Time: {now_str}
    </div>

    <div style="margin-top: 30px; font-size: 12px; color: #666;">
      <p> Need help? Contact our support team</p>
      <p> Interview link valid for multiple sessions</p>
    </div>
  </div>

  <script>
    const interviewData = {interview_json};
    function startInterview() {{
      console.log(' Starting interview with data:', interviewData);
      sessionStorage.setItem('interviewData', JSON.stringify(interviewData));
      fetch('/api/avatar/interview/{token}', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ action: '{continue_lower}' }})
      }}).catch(() => {{ /* best effort */ }});
      window.location.href = 'http://localhost:3001/interview/{token}';
    }}

    fetch('/api/interview/validate-token/{token}', {{ method: 'POST' }})
      .then(r => r.json())
      .then(d => {{
        if (!d.valid) {{
          alert('This interview link has expired. Please contact HR for assistance.');
          document.querySelector('.start-btn').disabled = true;
        }}
      }})
      .catch(() => {{ /* noop */ }});
  </script>
</body>
</html>"""

