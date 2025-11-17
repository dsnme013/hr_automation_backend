from flask import Blueprint, jsonify, request
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from app.extensions import cache, logger
from app.models.db import Candidate, SessionLocal
from app.routes.shared import rate_limit

stats_bp = Blueprint("stats", __name__)

@stats_bp.route('/api/recruitment-stats', methods=['GET','OPTIONS'])
@rate_limit(max_calls=20, time_window=60)
@cache.memoize(timeout=600)  # 10 minute cache
def api_recruitment_stats():
    """Cached recruitment statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    session = SessionLocal()
    try:
        stats = []
        current_date = datetime.now()
        
        # Get last 6 months of data efficiently
        for i in range(6):
            try:
                month_date = current_date - timedelta(days=30*i)
                month_name = month_date.strftime('%b')
                
                # Calculate month boundaries
                month_start = month_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if month_start.month == 12:
                    month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(seconds=1)
                else:
                    month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(seconds=1)
                
                # Single query for all stats
                applications = session.query(func.count(Candidate.id)).filter(
                    and_(
                        Candidate.processed_date >= month_start,
                        Candidate.processed_date <= month_end
                    )
                ).scalar() or 0
                
                interviews = session.query(func.count(Candidate.id)).filter(
                    and_(
                        Candidate.interview_scheduled == True,
                        Candidate.interview_date >= month_start,
                        Candidate.interview_date <= month_end
                    )
                ).scalar() or 0
                
                hires = session.query(func.count(Candidate.id)).filter(
                    and_(
                        Candidate.final_status == "Hired",
                        Candidate.processed_date >= month_start,
                        Candidate.processed_date <= month_end
                    )
                ).scalar() or 0
                
                stats.append({
                    "month": month_name,
                    "applications": applications,
                    "interviews": interviews,
                    "hires": hires
                })
                
            except Exception as e:
                logger.error(f"Error calculating stats for month {i}: {e}")
                stats.append({
                    "month": (current_date - timedelta(days=30*i)).strftime('%b'),
                    "applications": 0,
                    "interviews": 0,
                    "hires": 0
                })
        
        # Reverse to get chronological order
        stats.reverse()
        
        logger.info(f"Generated recruitment stats for {len(stats)} months")
        return jsonify(stats), 200
        
    except Exception as e:
        logger.error(f"Error in api_recruitment_stats: {e}", exc_info=True)
        return jsonify({"error": "Failed to get statistics", "message": str(e)}), 500
    finally:
        session.close()
