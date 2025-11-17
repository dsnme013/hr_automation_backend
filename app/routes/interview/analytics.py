
from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import os, json, time, uuid
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_
from app.models.db import Candidate, SessionLocal
from app.extensions import logger
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


analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/api/interview/results', methods=['GET'])
def get_interview_results():
    """Get all interview results with filtering options"""
    session = SessionLocal()
    try:
        # Get query parameters
        position = request.args.get('position')
        status = request.args.get('status')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        
        # Build query
        query = session.query(Candidate).filter(
            Candidate.interview_scheduled == True
        )
        
        # Apply filters
        if position:
            query = query.filter(Candidate.job_title == position)
        
        if status:
            if status == 'completed':
                query = query.filter(Candidate.interview_completed_at.isnot(None))
            elif status == 'pending':
                query = query.filter(Candidate.interview_completed_at.is_(None))
        
        if date_from:
            query = query.filter(Candidate.interview_date >= date_from)
        
        if date_to:
            query = query.filter(Candidate.interview_date <= date_to)
        
        # Get results
        candidates = query.all()
        
        # Format results
        results = []
        for candidate in candidates:
            results.append({
                'id': candidate.id,
                'name': candidate.name,
                'email': candidate.email,
                'job_title': candidate.job_title,
                'interview_date': candidate.interview_date.isoformat() if candidate.interview_date else None,
                'interview_completed_at': candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                'interview_ai_score': candidate.interview_ai_score,
                'interview_ai_technical_score': candidate.interview_ai_technical_score,
                'interview_ai_communication_score': candidate.interview_ai_communication_score,
                'interview_ai_problem_solving_score': candidate.interview_ai_problem_solving_score,
                'interview_ai_cultural_fit_score': candidate.interview_ai_cultural_fit_score,
                'interview_ai_overall_feedback': candidate.interview_ai_overall_feedback,
                'interview_final_status': candidate.interview_final_status,
                'interview_recording_url': candidate.interview_recording_url,
                'interview_transcript': candidate.interview_transcript
            })
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting interview results: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        session.close()

@analytics_bp.route('/api/interview/stats', methods=['GET'])
def get_interview_stats():
    """Get interview statistics"""
    session = SessionLocal()
    try:
        # Get all interviewed candidates
        candidates = session.query(Candidate).filter(
            Candidate.interview_scheduled == True
        ).all()
        
        # Calculate statistics
        total = len(candidates)
        completed = len([c for c in candidates if c.interview_completed_at])
        with_scores = len([c for c in candidates if c.interview_ai_score])
        passed = len([c for c in candidates if c.interview_ai_score and c.interview_ai_score >= 70])
        
        avg_score = 0
        if with_scores > 0:
            total_score = sum(c.interview_ai_score for c in candidates if c.interview_ai_score)
            avg_score = total_score / with_scores
        
        # Skills averages
        skills = {
            'technical': 0,
            'communication': 0,
            'problem_solving': 0,
            'cultural_fit': 0
        }
        
        for c in candidates:
            if c.interview_ai_technical_score:
                skills['technical'] += c.interview_ai_technical_score
            if c.interview_ai_communication_score:
                skills['communication'] += c.interview_ai_communication_score
            if c.interview_ai_problem_solving_score:
                skills['problem_solving'] += c.interview_ai_problem_solving_score
            if c.interview_ai_cultural_fit_score:
                skills['cultural_fit'] += c.interview_ai_cultural_fit_score
        
        # Calculate averages
        for skill in skills:
            if with_scores > 0:
                skills[skill] = skills[skill] / with_scores
        
        return jsonify({
            'success': True,
            'stats': {
                'total_interviews': total,
                'completed_interviews': completed,
                'average_score': round(avg_score, 1),
                'pass_rate': round((passed / with_scores * 100), 1) if with_scores > 0 else 0,
                'pending_analysis': completed - with_scores,
                'skills_average': skills
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting interview stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        session.close()
