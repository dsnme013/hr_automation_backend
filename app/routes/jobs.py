# from flask import Blueprint, jsonify, request
# from sqlalchemy import func
# from app.extensions import cache, logger
# from app.models.db import Candidate, SessionLocal
# from app.routes.shared import rate_limit
# from app.services.resumescraper import get_roles_from_dashboard  # ← scrapes http://65.0.3.172/admin

# jobs_bp = Blueprint("jobs", __name__)


# @cache.memoize(timeout=300)
# def get_cached_jobs():
#     """
#     Fetch jobs by scraping the HR dashboard at http://65.0.3.172/admin
#     via resumescraper.get_roles_from_dashboard().
#     Falls back to the local database if the dashboard is unreachable.
#     """
#     try:
#         roles = get_roles_from_dashboard()

#         if not roles:
#             logger.warning("No roles returned from dashboard — falling back to database")
#             return get_jobs_from_database()

#         # Enrich each role with live candidate count from the database
#         session = SessionLocal()
#         try:
#             for role in roles:
#                 candidate_count = (
#                     session.query(Candidate)
#                     .filter_by(job_title=role["title"])
#                     .count()
#                 )
#                 # Use DB count if higher than history count
#                 role["applications"] = max(role["applications"], candidate_count)
#         finally:
#             session.close()

#         logger.info(f"Returning {len(roles)} role(s) from HR dashboard")
#         return roles

#     except Exception as e:
#         logger.error(f"Dashboard scrape error: {e}")
#         return get_jobs_from_database()


# def get_jobs_from_database():
#     """Fallback: build job list from candidates already stored in the database."""
#     session = SessionLocal()
#     try:
#         jobs_data = session.query(
#             Candidate.job_id,
#             Candidate.job_title,
#             func.count(Candidate.id).label("applications"),
#         ).filter(
#             Candidate.job_id.isnot(None),
#             Candidate.job_title.isnot(None),
#         ).group_by(
#             Candidate.job_id,
#             Candidate.job_title,
#         ).all()

#         jobs = []
#         for job_id, job_title, app_count in jobs_data:
#             jobs.append({
#                 "id":           str(job_id),
#                 "title":        job_title,
#                 "department":   "",
#                 "location":     "",
#                 "applications": app_count,
#                 "status":       "Active",
#                 "description":  f"Job description for {job_title}",
#                 "postingUrl":   "",
#             })

#         return jobs
#     finally:
#         session.close()


# @jobs_bp.route("/api/jobs", methods=["GET", "OPTIONS"])
# @rate_limit(max_calls=30, time_window=60)
# def api_jobs():
#     """Return all active jobs scraped from the HR dashboard."""
#     if request.method == "OPTIONS":
#         return "", 200

#     try:
#         jobs = get_cached_jobs()
#         return jsonify(jobs), 200
#     except Exception as e:
#         logger.error(f"Error in api_jobs: {e}", exc_info=True)
#         return jsonify({"error": "Failed to fetch jobs", "message": str(e)}), 500
from flask import Blueprint, jsonify, request
from sqlalchemy import func
from app.extensions import cache, logger
from app.models.db import Candidate, SessionLocal
from app.routes.shared import rate_limit
from app.services.jobs_api import get_roles_from_dashboard  # ← scrapes http://65.1.136.77/admin

jobs_bp = Blueprint("jobs", __name__)


@cache.memoize(timeout=300)
def get_cached_jobs():
    """
    Fetch jobs by scraping the HR dashboard at http://65.1.136.77/admin
    via resumescraper.get_roles_from_dashboard().
    Falls back to the local database if the dashboard is unreachable.
    """
    try:
        roles = get_roles_from_dashboard()

        if not roles:
            logger.warning("No roles returned from dashboard — falling back to database")
            return get_jobs_from_database()

        # Enrich each role with live candidate count from the database
        session = SessionLocal()
        try:
            for role in roles:
                candidate_count = (
                    session.query(Candidate)
                    .filter_by(job_title=role["title"])
                    .count()
                )
                # Use DB count if higher than history count
                role["applications"] = max(role["applications"], candidate_count)
        finally:
            session.close()

        logger.info(f"Returning {len(roles)} role(s) from HR dashboard")
        return roles

    except Exception as e:
        logger.error(f"Dashboard scrape error: {e}")
        return get_jobs_from_database()


def get_jobs_from_database():
    """Fallback: build job list from candidates already stored in the database."""
    session = SessionLocal()
    try:
        jobs_data = session.query(
            Candidate.job_id,
            Candidate.job_title,
            func.count(Candidate.id).label("applications"),
        ).filter(
            Candidate.job_id.isnot(None),
            Candidate.job_title.isnot(None),
        ).group_by(
            Candidate.job_id,
            Candidate.job_title,
        ).all()

        jobs = []
        for job_id, job_title, app_count in jobs_data:
            jobs.append({
                "id":           str(job_id),
                "title":        job_title,
                "department":   "",
                "location":     "",
                "applications": app_count,
                "status":       "Active",
                "description":  f"Job description for {job_title}",
                "postingUrl":   "",
            })

        return jobs
    finally:
        session.close()


@jobs_bp.route("/api/jobs", methods=["GET", "OPTIONS"])
@rate_limit(max_calls=30, time_window=60)
def api_jobs():
    """Return all active jobs scraped from the HR dashboard."""
    if request.method == "OPTIONS":
        return "", 200

    try:
        jobs = get_cached_jobs()
        return jsonify(jobs), 200
    except Exception as e:
        logger.error(f"Error in api_jobs: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch jobs", "message": str(e)}), 500