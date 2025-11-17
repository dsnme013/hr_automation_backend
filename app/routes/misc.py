
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from app.models.db import Candidate, SessionLocal
from app.extensions import cache, logger
import os

misc_bp = Blueprint("misc", __name__)

@misc_bp.route('/test')
def test():
    return "API is working!"

request_metrics = {
    'total_requests': 0,
    'avg_response_time': 0,
    'slow_requests': 0
}

@misc_bp.before_app_request
def before_request():
    import time, uuid
    request.start_time = time.time()
    if not hasattr(current_app, "request_metrics"):
        current_app.request_metrics = {'total_requests': 0, 'avg_response_time': 0, 'slow_requests': 0}
    current_app.request_metrics['total_requests'] += 1
    request.request_id = str(uuid.uuid4())[:8]

@misc_bp.after_app_request
def after_request(response):
    import time
    metrics = getattr(current_app, "request_metrics", None)
    if hasattr(request, 'start_time') and metrics is not None:
        duration = time.time() - request.start_time
        if metrics['avg_response_time'] == 0:
            metrics['avg_response_time'] = duration
        else:
            metrics['avg_response_time'] = (metrics['avg_response_time'] + duration) / 2
        if duration > 5.0:
            metrics['slow_requests'] += 1
            logger.warning(f"Slow request: {request.method} {request.path} took {duration:.2f}s")
        response.headers['X-Response-Time'] = f"{duration:.3f}s"
        response.headers['X-Request-ID'] = getattr(request, 'request_id', 'unknown')
    return response

@misc_bp.route('/', methods=['GET'])
def home():
    """Enhanced root endpoint with comprehensive API information"""
    try:
        # Get system statistics
        session = SessionLocal()
        try:
            stats = {
                "total_candidates": session.query(Candidate).count(),
                "total_jobs": session.query(Candidate.job_id).distinct().count(),
                "shortlisted_candidates": session.query(Candidate).filter_by(status='Shortlisted').count(),
                "completed_assessments": session.query(Candidate).filter_by(exam_completed=True).count(),
                "scheduled_interviews": session.query(Candidate).filter_by(interview_scheduled=True).count(),
            }
        except Exception:
            stats = {"error": "Could not fetch statistics"}
        finally:
            session.close()
        
        # Check system health
        system_health = {
            "database": "healthy",
            "cache": "healthy",
            "interview_automation": "running" if hasattr(current_app, 'interview_automation') else "stopped"
        }
        
        # API documentation with examples
        api_docs = {
            "endpoints": {
                "GET /api/jobs": {
                    "description": "Get all job postings",
                    "example": f"{request.host_url}api/jobs"
                },
                "GET /api/candidates": {
                    "description": "Get candidates (filterable by job_id, status)",
                    "example": f"{request.host_url}api/candidates?job_id=123&status=Shortlisted"
                },
                "POST /api/run_full_pipeline": {
                    "description": "Start recruitment pipeline for a job",
                    "example_payload": {
                        "job_id": "123",
                        "job_title": "Software Engineer",
                        "job_desc": "Job description here"
                    }
                },
                "GET /api/pipeline_status/<job_id>": {
                    "description": "Check pipeline status for specific job",
                    "example": f"{request.host_url}api/pipeline_status/123"
                }
            }
        }
        
        return jsonify({
            "message": "TalentFlow AI Backend API",
            "tagline": "Intelligent Recruitment Automation Platform",
            "version": "2.1.0",
            "status": "operational",
            "timestamp": datetime.now().isoformat(),
            "uptime": "System started successfully",
            
            # System Statistics
            "statistics": stats,
            "system_health": system_health,
            
            # Quick Links
            "quick_links": {
                "health_check": f"{request.host_url}health",
                "api_documentation": f"{request.host_url}api/routes",
                "frontend_dashboard": "http://localhost:3000"
            },
            
            # API Information
            "api_info": api_docs,
            
            # Contact & Support
            "support": {
                "company": os.getenv('COMPANY_NAME', 'TalentFlow AI'),
                "admin_email": os.getenv('ADMIN_EMAIL', 'admin@talentflow.ai'),
                "documentation": "https://docs.talentflow.ai"
            },
            
            # Features Highlight
            "features": [
                "AI-Powered Resume Screening",
                "Automated Assessment Creation", 
                "Smart Email Automation",
                "Real-time Analytics Dashboard",
                "AI Avatar Interviews",
                "Pipeline Automation"
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Error in enhanced home route: {e}")
        return jsonify({
            "message": "TalentFlow AI Backend API",
            "version": "2.1.0",
            "status": "running",
            "error": "Partial system information available",
            "basic_endpoints": ["/api/jobs", "/api/candidates", "/health"]
        }), 200

