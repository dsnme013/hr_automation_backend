
from flask import Blueprint, jsonify, request
from sqlalchemy import func
import os, requests
from app.extensions import cache, logger
from app.models.db import Candidate, SessionLocal
from app.routes.shared import rate_limit

jobs_bp = Blueprint("jobs", __name__)

@cache.memoize(timeout=300)
def get_cached_jobs():
    """Cached job fetching"""
    try:
        API_KEY = os.getenv("BAMBOOHR_API_KEY")
        SUBDOMAIN = os.getenv("BAMBOOHR_SUBDOMAIN")
        
        if not API_KEY or not SUBDOMAIN:
            raise ValueError("BambooHR credentials not configured")
            
        auth = (API_KEY, "x")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        url = f"https://api.bamboohr.com/api/gateway.php/{SUBDOMAIN}/v1/applicant_tracking/jobs/"
        
        resp = requests.get(url, auth=auth, headers=headers, timeout=10)
        resp.raise_for_status()
        
        jobs = resp.json()
        open_jobs = []
        
        session = SessionLocal()
        try:
            for job in jobs:
                if job.get("status", {}).get("label", "").lower() == "open":
                    # Get candidate count for this job
                    candidate_count = session.query(Candidate).filter_by(job_id=str(job["id"])).count()
                    
                    open_jobs.append({
                        "id": job["id"],
                        "title": job.get("title", {}).get("label", ""),
                        "location": job.get("location", {}).get("label", ""),
                        "department": job.get("department", {}).get("label", ""),
                        "postingUrl": job.get("postingUrl", ""),
                        "applications": candidate_count,
                        "status": "Active",
                        "description": job.get("description", "")
                    })
        finally:
            session.close()
        
        return open_jobs
        
    except Exception as e:
        logger.error(f"BambooHR API error: {e}")
        # Fallback to database
        return get_jobs_from_database()

def get_jobs_from_database():
    """Fallback job fetching from database"""
    session = SessionLocal()
    try:
        jobs_data = session.query(
            Candidate.job_id,
            Candidate.job_title,
            func.count(Candidate.id).label('applications')
        ).filter(
            Candidate.job_id.isnot(None),
            Candidate.job_title.isnot(None)
        ).group_by(
            Candidate.job_id, 
            Candidate.job_title
        ).all()
        
        jobs = []
        for job_id, job_title, app_count in jobs_data:
            jobs.append({
                'id': str(job_id),
                'title': job_title,
                'department': 'Engineering',
                'location': 'Remote',
                'applications': app_count,
                'status': 'Active',
                'description': f'Job description for {job_title}',
                'postingUrl': ''
            })
        
        return jobs
    finally:
        session.close()

@jobs_bp.route('/api/jobs', methods=['GET', 'OPTIONS'])
@rate_limit(max_calls=30, time_window=60)
def api_jobs():
    """Enhanced API endpoint to get jobs with caching"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        jobs = get_cached_jobs()
        return jsonify(jobs), 200
    except Exception as e:
        logger.error(f"Error in api_jobs: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch jobs", "message": str(e)}), 500
