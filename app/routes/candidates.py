
from typing import Optional
from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import os, json
from app.extensions import cache, logger
from app.models.db import Candidate, SessionLocal
from app.routes.shared import rate_limit
from fastapi import Query
candidates_bp = Blueprint("candidates", __name__)

@cache.memoize(timeout=180)
def get_cached_candidates(job_id=None, status_filter=None):
    """Cached candidate fetching with optimized queries"""
    session = SessionLocal()
    try:
        query = session.query(Candidate)
        
        if job_id:
            query = query.filter_by(job_id=str(job_id))
        
        if status_filter:
            query = query.filter_by(status=status_filter)
        
        candidates = query.all()
        
        result = []
        for c in candidates:
            try:
                # Calculate time remaining for assessment
                time_remaining = None
                link_expired = False
                
                if c.exam_link_sent_date and not c.exam_completed:
                    deadline = c.exam_link_sent_date + timedelta(hours=ASSESSMENT_CONFIG['EXPIRY_HOURS']) # type: ignore
                    if datetime.now() < deadline:
                        time_remaining = (deadline - datetime.now()).total_seconds() / 3600
                    else:
                        link_expired = True
                
                candidate_data = {
                    "id": c.id,
                    "name": c.name or "Unknown",
                    "email": c.email or "",
                    "job_id": c.job_id,
                    "job_title": c.job_title or "Unknown Position",
                    "status": c.status,
                    "ats_score": float(c.ats_score) if c.ats_score else 0.0,
                    "linkedin": c.linkedin,
                    "github": c.github,
                    "phone": getattr(c, 'phone', None),
                    "resume_path": c.resume_path,
                    "resume_url": c.resume_path,  # Add this for frontend compatibility
                    "processed_date": c.processed_date.isoformat() if c.processed_date else None,
                    "score_reasoning": c.score_reasoning,
                    
                    # Assessment fields
                    "assessment_invite_link": c.assessment_invite_link,
                    "exam_link_sent": bool(c.exam_link_sent),
                    "exam_link_sent_date": c.exam_link_sent_date.isoformat() if c.exam_link_sent_date else None,
                    "exam_completed": bool(c.exam_completed),
                    "exam_completed_date": c.exam_completed_date.isoformat() if c.exam_completed_date else None,
                    "link_expired": link_expired,
                    "time_remaining_hours": time_remaining,
                    "exam_percentage": float(c.exam_percentage) if c.exam_percentage else None,
                    
                    # Interview scheduling fields
                    "interview_scheduled": bool(c.interview_scheduled),
                    "interview_date": c.interview_date.isoformat() if c.interview_date else None,
                    "interview_link": c.interview_link,
                    "interview_token": c.interview_token,
                    
                    # Interview progress fields
                    "interview_started_at": c.interview_started_at.isoformat() if c.interview_started_at else None,
                    "interview_completed_at": c.interview_completed_at.isoformat() if c.interview_completed_at else None,
                    "interview_duration": c.interview_duration or 0,
                    "interview_progress": c.interview_progress_percentage or 0,
                    "interview_questions_answered": c.interview_answered_questions or 0,
                    "interview_total_questions": c.interview_total_questions or 0,
                    
                    # Interview AI analysis fields
                    "interview_ai_score": c.interview_ai_score,
                    "interview_ai_technical_score": c.interview_ai_technical_score,
                    "interview_ai_communication_score": c.interview_ai_communication_score,
                    "interview_ai_problem_solving_score": c.interview_ai_problem_solving_score,
                    "interview_ai_cultural_fit_score": c.interview_ai_cultural_fit_score,
                    "interview_ai_overall_feedback": c.interview_ai_overall_feedback,
                    "interview_ai_analysis_status": c.interview_ai_analysis_status,
                    "interview_final_status": c.interview_final_status,
                    
                    # Interview insights
                    "strengths": json.loads(c.interview_ai_strengths or '[]') if c.interview_ai_strengths else [],
                    "weaknesses": json.loads(c.interview_ai_weaknesses or '[]') if c.interview_ai_weaknesses else [],
                    "recommendations": json.loads(c.interview_recommendations or '[]') if hasattr(c, 'interview_recommendations') and c.interview_recommendations else [],
                    
                    # Interview recording
                    "interview_recording_url": c.interview_recording_url,
                    
                    # Status fields
                    "final_status": c.final_status,
                }
                
                result.append(candidate_data)
                
            except Exception as e:
                logger.error(f"Error processing candidate {c.id}: {e}")
                continue
        
        return result
    finally:
        session.close()


@candidates_bp.route('/api/candidates', methods=['GET','OPTIONS'])
@rate_limit(max_calls=60, time_window=60)
def api_candidates():
    """Enhanced API endpoint to get candidates with caching"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        job_id = request.args.get('job_id')
        status_filter = request.args.get('status')
        
        candidates = get_cached_candidates(job_id, status_filter)
        return jsonify(candidates), 200
        
    except Exception as e:
        logger.error(f"Error in api_candidates: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch candidates", "message": str(e)}), 500
    
