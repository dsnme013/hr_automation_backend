
from asyncio.log import logger
from datetime import datetime
import time, threading, logging
from functools import wraps
from flask import request, jsonify
from flask import Blueprint, jsonify, request

shared_bp = Blueprint("shared", __name__)

# Rate limiter (logic identical to original behavior)
def rate_limit(max_calls=10, time_window=60):
    """Enhanced rate limiting decorator with memory optimization"""
    calls = {}
    cleanup_counter = 0
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal cleanup_counter
            
            # Skip rate limiting for OPTIONS requests (CORS preflight)
            if request.method == 'OPTIONS':
                return func(*args, **kwargs)
            
            now = time.time()
            key = request.remote_addr
            
            # Periodic cleanup to prevent memory leaks
            cleanup_counter += 1
            if cleanup_counter % 100 == 0:
                cutoff = now - time_window * 2
                for ip in list(calls.keys()):
                    calls[ip] = [call_time for call_time in calls.get(ip, []) if call_time > cutoff]
                    if not calls[ip]:
                        del calls[ip]
            
            if key not in calls:
                calls[key] = []
            
            # Remove old calls
            calls[key] = [call_time for call_time in calls[key] if now - call_time < time_window]
            
            if len(calls[key]) >= max_calls:
                logger.warning(f"Rate limit exceeded for {key}")
                return jsonify({"error": "Rate limit exceeded"}), 429
            
            calls[key].append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Pipeline status store
pipeline_status = {}
pipeline_lock = threading.Lock()

def update_pipeline_status(job_id, status, message, progress=None):
    """Thread-safe pipeline status updates"""
    with pipeline_lock:
        pipeline_status[str(job_id)] = {
            'status': status,
            'message': message,
            'progress': progress,
            'timestamp': datetime.now().isoformat(),
            'job_id': str(job_id)
        }
    logger.info(f"Pipeline {job_id}: {status} - {message}")

def get_pipeline_status(job_id=None):
    """Get pipeline status (thread-safe)"""
    with pipeline_lock:
        if job_id:
            return pipeline_status.get(str(job_id))
        # return dict(pipeline_status)
        return pipeline_status.copy()