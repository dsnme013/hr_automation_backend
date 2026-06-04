
# # # # from typing import Optional
# # # # from flask import Blueprint, jsonify, request
# # # # from datetime import datetime, timedelta
# # # # import os, json
# # # # from app.extensions import cache, logger
# # # # from app.models.db import Candidate, SessionLocal
# # # # from app.routes.shared import rate_limit
# # # # from fastapi import Query
# # # # candidates_bp = Blueprint("candidates", __name__)

# # # # @cache.memoize(timeout=180)
# # # # def get_cached_candidates(job_id=None, status_filter=None):
# # # #     """Cached candidate fetching with optimized queries"""
# # # #     session = SessionLocal()
# # # #     try:
# # # #         query = session.query(Candidate)
        
# # # #         if job_id:
# # # #             query = query.filter_by(job_id=str(job_id))
        
# # # #         if status_filter:
# # # #             query = query.filter_by(status=status_filter)
        
# # # #         candidates = query.all()
        
# # # #         result = []
# # # #         for c in candidates:
# # # #             try:
# # # #                 # Calculate time remaining for assessment
# # # #                 time_remaining = None
# # # #                 link_expired = False
                
# # # #                 if c.exam_link_sent_date and not c.exam_completed:
# # # #                     deadline = c.exam_link_sent_date + timedelta(hours=ASSESSMENT_CONFIG['EXPIRY_HOURS']) # type: ignore
# # # #                     if datetime.now() < deadline:
# # # #                         time_remaining = (deadline - datetime.now()).total_seconds() / 3600
# # # #                     else:
# # # #                         link_expired = True
                
# # # #                 candidate_data = {
# # # #                     "id": c.id,
# # # #                     "name": c.name or "Unknown",
# # # #                     "email": c.email or "",
# # # #                     "job_id": c.job_id,
# # # #                     "job_title": c.job_title or "Unknown Position",
# # # #                     "status": c.status,
# # # #                     "ats_score": float(c.ats_score) if c.ats_score else 0.0,
# # # #                     "linkedin": c.linkedin,
# # # #                     "github": c.github,
# # # #                     "phone": getattr(c, 'phone', None),
# # # #                     "resume_path": c.resume_path,
# # # #                     "resume_url": c.resume_path,  # Add this for frontend compatibility
# # # #                     "processed_date": c.processed_date.isoformat() if c.processed_date else None,
# # # #                     "score_reasoning": c.score_reasoning,
                    
# # # #                     # Assessment fields
# # # #                     "assessment_invite_link": c.assessment_invite_link,
# # # #                     "exam_link_sent": bool(c.exam_link_sent),
# # # #                     "exam_link_sent_date": c.exam_link_sent_date.isoformat() if c.exam_link_sent_date else None,
# # # #                     "exam_completed": bool(c.exam_completed),
# # # #                     "exam_completed_date": c.exam_completed_date.isoformat() if c.exam_completed_date else None,
# # # #                     "link_expired": link_expired,
# # # #                     "time_remaining_hours": time_remaining,
# # # #                     "exam_percentage": float(c.exam_percentage) if c.exam_percentage else None,
                    
# # # #                     # Interview scheduling fields
# # # #                     "interview_scheduled": bool(c.interview_scheduled),
# # # #                     "interview_date": c.interview_date.isoformat() if c.interview_date else None,
# # # #                     "interview_link": c.interview_link,
# # # #                     "interview_token": c.interview_token,
                    
# # # #                     # Interview progress fields
# # # #                     "interview_started_at": c.interview_started_at.isoformat() if c.interview_started_at else None,
# # # #                     "interview_completed_at": c.interview_completed_at.isoformat() if c.interview_completed_at else None,
# # # #                     "interview_duration": c.interview_duration or 0,
# # # #                     "interview_progress": c.interview_progress_percentage or 0,
# # # #                     "interview_questions_answered": c.interview_answered_questions or 0,
# # # #                     "interview_total_questions": c.interview_total_questions or 0,
                    
# # # #                     # Interview AI analysis fields
# # # #                     "interview_ai_score": c.interview_ai_score,
# # # #                     "interview_ai_technical_score": c.interview_ai_technical_score,
# # # #                     "interview_ai_communication_score": c.interview_ai_communication_score,
# # # #                     "interview_ai_problem_solving_score": c.interview_ai_problem_solving_score,
# # # #                     "interview_ai_cultural_fit_score": c.interview_ai_cultural_fit_score,
# # # #                     "interview_ai_overall_feedback": c.interview_ai_overall_feedback,
# # # #                     "interview_ai_analysis_status": c.interview_ai_analysis_status,
# # # #                     "interview_final_status": c.interview_final_status,
                    
# # # #                     # Interview insights
# # # #                     "strengths": json.loads(c.interview_ai_strengths or '[]') if c.interview_ai_strengths else [],
# # # #                     "weaknesses": json.loads(c.interview_ai_weaknesses or '[]') if c.interview_ai_weaknesses else [],
# # # #                     "recommendations": json.loads(c.interview_recommendations or '[]') if hasattr(c, 'interview_recommendations') and c.interview_recommendations else [],
                    
# # # #                     # Interview recording
# # # #                     "interview_recording_url": c.interview_recording_url,
                    
# # # #                     # Status fields
# # # #                     "final_status": c.final_status,
# # # #                 }
                
# # # #                 result.append(candidate_data)
                
# # # #             except Exception as e:
# # # #                 logger.error(f"Error processing candidate {c.id}: {e}")
# # # #                 continue
        
# # # #         return result
# # # #     finally:
# # # #         session.close()


# # # # @candidates_bp.route('/api/candidates', methods=['GET','OPTIONS'])
# # # # @rate_limit(max_calls=60, time_window=60)
# # # # def api_candidates():
# # # #     """Enhanced API endpoint to get candidates with caching"""
# # # #     if request.method == 'OPTIONS':
# # # #         return '', 200
    
# # # #     try:
# # # #         job_id = request.args.get('job_id')
# # # #         status_filter = request.args.get('status')
        
# # # #         candidates = get_cached_candidates(job_id, status_filter)
# # # #         return jsonify(candidates), 200
        
# # # #     except Exception as e:
# # # #         logger.error(f"Error in api_candidates: {e}", exc_info=True)
# # # #         return jsonify({"error": "Failed to fetch candidates", "message": str(e)}), 500
    
# # # from typing import Optional
# # # from flask import Blueprint, jsonify, request
# # # from datetime import datetime, timedelta
# # # import os, json
# # # from app.extensions import cache, logger
# # # from app.models.db import Candidate, SessionLocal
# # # from app.routes.shared import rate_limit

# # # candidates_bp = Blueprint("candidates", __name__)

# # # # ✅ FIX: Define ASSESSMENT_CONFIG that was missing (caused silent crash)
# # # ASSESSMENT_CONFIG = {
# # #     'EXPIRY_HOURS': 48  # Assessment link expires after 48 hours
# # # }


# # # @cache.memoize(timeout=180)
# # # def get_cached_candidates(job_id=None, status_filter=None):
# # #     """Cached candidate fetching with optimized queries"""
# # #     session = SessionLocal()
# # #     try:
# # #         query = session.query(Candidate)

# # #         if job_id:
# # #             query = query.filter_by(job_id=str(job_id))

# # #         if status_filter:
# # #             query = query.filter_by(status=status_filter)

# # #         candidates = query.all()

# # #         # ✅ FIX: Log how many candidates the DB actually returns
# # #         logger.info(f"DB query returned {len(candidates)} candidates for job_id={job_id}, status={status_filter}")

# # #         result = []
# # #         for c in candidates:
# # #             try:
# # #                 # Calculate time remaining for assessment
# # #                 time_remaining = None
# # #                 link_expired = False

# # #                 # ✅ FIX: Use getattr safely for all fields that might not exist
# # #                 exam_link_sent_date = getattr(c, 'exam_link_sent_date', None)
# # #                 exam_completed = getattr(c, 'exam_completed', False)

# # #                 if exam_link_sent_date and not exam_completed:
# # #                     deadline = exam_link_sent_date + timedelta(hours=ASSESSMENT_CONFIG['EXPIRY_HOURS'])
# # #                     if datetime.now() < deadline:
# # #                         time_remaining = (deadline - datetime.now()).total_seconds() / 3600
# # #                     else:
# # #                         link_expired = True

# # #                 candidate_data = {
# # #                     "id": c.id,
# # #                     "name": c.name or "Unknown",
# # #                     "email": c.email or "",
# # #                     "job_id": c.job_id,
# # #                     "job_title": getattr(c, 'job_title', None) or "Unknown Position",
# # #                     "status": c.status,
# # #                     "ats_score": float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
# # #                     "linkedin": getattr(c, 'linkedin', None),
# # #                     "github": getattr(c, 'github', None),
# # #                     "phone": getattr(c, 'phone', None),
# # #                     "resume_path": getattr(c, 'resume_path', None),
# # #                     "resume_url": getattr(c, 'resume_path', None),
# # #                     "processed_date": c.processed_date.isoformat() if getattr(c, 'processed_date', None) else None,
# # #                     "score_reasoning": getattr(c, 'score_reasoning', None),

# # #                     # Assessment fields
# # #                     "assessment_invite_link": getattr(c, 'assessment_invite_link', None),
# # #                     "exam_link_sent": bool(getattr(c, 'exam_link_sent', False)),
# # #                     "exam_link_sent_date": exam_link_sent_date.isoformat() if exam_link_sent_date else None,
# # #                     "exam_completed": bool(exam_completed),
# # #                     "exam_completed_date": c.exam_completed_date.isoformat() if getattr(c, 'exam_completed_date', None) else None,
# # #                     "exam_started": bool(getattr(c, 'exam_started', False)),
# # #                     "link_expired": link_expired,
# # #                     "time_remaining_hours": time_remaining,
# # #                     "exam_percentage": float(c.exam_percentage) if getattr(c, 'exam_percentage', None) else None,

# # #                     # Interview scheduling fields
# # #                     "interview_scheduled": bool(getattr(c, 'interview_scheduled', False)),
# # #                     "interview_date": c.interview_date.isoformat() if getattr(c, 'interview_date', None) else None,
# # #                     "interview_link": getattr(c, 'interview_link', None),
# # #                     "interview_token": getattr(c, 'interview_token', None),

# # #                     # Interview progress fields
# # #                     "interview_started_at": c.interview_started_at.isoformat() if getattr(c, 'interview_started_at', None) else None,
# # #                     "interview_completed_at": c.interview_completed_at.isoformat() if getattr(c, 'interview_completed_at', None) else None,
# # #                     "interview_duration": getattr(c, 'interview_duration', 0) or 0,
# # #                     "interview_progress": getattr(c, 'interview_progress_percentage', 0) or 0,
# # #                     "interview_questions_answered": getattr(c, 'interview_answered_questions', 0) or 0,
# # #                     "interview_total_questions": getattr(c, 'interview_total_questions', 0) or 0,

# # #                     # Interview AI analysis fields
# # #                     "interview_ai_score": getattr(c, 'interview_ai_score', None),
# # #                     "interview_ai_technical_score": getattr(c, 'interview_ai_technical_score', None),
# # #                     "interview_ai_communication_score": getattr(c, 'interview_ai_communication_score', None),
# # #                     "interview_ai_problem_solving_score": getattr(c, 'interview_ai_problem_solving_score', None),
# # #                     "interview_ai_cultural_fit_score": getattr(c, 'interview_ai_cultural_fit_score', None),
# # #                     "interview_ai_overall_feedback": getattr(c, 'interview_ai_overall_feedback', None),
# # #                     "interview_ai_analysis_status": getattr(c, 'interview_ai_analysis_status', None),  # ✅ FIX: was crashing
# # #                     "interview_final_status": getattr(c, 'interview_final_status', None),              # ✅ FIX: was crashing

# # #                     # Interview insights
# # #                     "strengths": json.loads(c.interview_ai_strengths or '[]') if getattr(c, 'interview_ai_strengths', None) else [],
# # #                     "weaknesses": json.loads(c.interview_ai_weaknesses or '[]') if getattr(c, 'interview_ai_weaknesses', None) else [],
# # #                     "recommendations": json.loads(c.interview_recommendations or '[]') if getattr(c, 'interview_recommendations', None) else [],  # ✅ FIX: safe getattr

# # #                     # Interview recording
# # #                     "interview_recording_url": getattr(c, 'interview_recording_url', None),

# # #                     # Status fields
# # #                     "final_status": getattr(c, 'final_status', None),
# # #                 }

# # #                 result.append(candidate_data)

# # #             except Exception as e:
# # #                 # ✅ FIX: Log full traceback so errors are visible
# # #                 logger.error(f"Error processing candidate {getattr(c, 'id', 'unknown')}: {e}", exc_info=True)
# # #                 continue

# # #         logger.info(f"Successfully built {len(result)} candidate records")
# # #         return result

# # #     finally:
# # #         session.close()


# # # @candidates_bp.route('/api/candidates', methods=['GET', 'OPTIONS'])
# # # @rate_limit(max_calls=60, time_window=60)
# # # def api_candidates():
# # #     """Enhanced API endpoint to get candidates with caching"""
# # #     if request.method == 'OPTIONS':
# # #         return '', 200

# # #     try:
# # #         job_id = request.args.get('job_id')
# # #         status_filter = request.args.get('status')

# # #         candidates = get_cached_candidates(job_id, status_filter)
# # #         return jsonify(candidates), 200

# # #     except Exception as e:
# # #         logger.error(f"Error in api_candidates: {e}", exc_info=True)
# # #         return jsonify({"error": "Failed to fetch candidates", "message": str(e)}), 500


# # # # ✅ TEMPORARY DEBUG ROUTE - Remove after confirming candidates load correctly
# # # @candidates_bp.route('/api/candidates/debug', methods=['GET'])
# # # def debug_candidates():
# # #     """Debug endpoint to diagnose empty candidate list"""
# # #     session = SessionLocal()
# # #     try:
# # #         all_candidates = session.query(Candidate).all()
# # #         result = []

# # #         for c in all_candidates:
# # #             try:
# # #                 result.append({
# # #                     "id": c.id,
# # #                     "name": c.name,
# # #                     "email": c.email,
# # #                     "job_id": c.job_id,
# # #                     "status": c.status,
# # #                     "ats_score": float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
# # #                     "ok": True
# # #                 })
# # #             except Exception as e:
# # #                 result.append({
# # #                     "id": getattr(c, 'id', 'unknown'),
# # #                     "error": str(e),
# # #                     "ok": False
# # #                 })

# # #         return jsonify({
# # #             "total_in_db": len(all_candidates),
# # #             "successfully_parsed": len([r for r in result if r.get('ok')]),
# # #             "failed": len([r for r in result if not r.get('ok')]),
# # #             "candidates": result
# # #         }), 200

# # #     except Exception as e:
# # #         return jsonify({"error": str(e)}), 500
# # #     finally:
# # #         session.close()
# # from typing import Optional
# # from flask import Blueprint, jsonify, request
# # from datetime import datetime, timedelta
# # import os, json, re
# # from app.extensions import cache, logger
# # from app.models.db import Candidate, SessionLocal
# # from app.routes.shared import rate_limit

# # candidates_bp = Blueprint("candidates", __name__)

# # ASSESSMENT_CONFIG = {'EXPIRY_HOURS': 48}


# # def _safe_json_list(raw) -> list:
# #     """Safely parse a JSON list field that may be string or already a list."""
# #     if not raw:
# #         return []
# #     if isinstance(raw, list):
# #         return raw
# #     try:
# #         result = json.loads(raw)
# #         return result if isinstance(result, list) else []
# #     except Exception:
# #         return []


# # @cache.memoize(timeout=180)
# # def get_cached_candidates(job_id=None, status_filter=None):
# #     session = SessionLocal()
# #     try:
# #         query = session.query(Candidate)
# #         if job_id:
# #             query = query.filter_by(job_id=str(job_id))
# #         if status_filter:
# #             query = query.filter_by(status=status_filter)

# #         candidates = query.all()
# #         logger.info(f"DB query returned {len(candidates)} candidates for job_id={job_id}, status={status_filter}")

# #         result = []
# #         for c in candidates:
# #             try:
# #                 time_remaining = None
# #                 link_expired   = False

# #                 exam_link_sent_date = getattr(c, 'exam_link_sent_date', None)
# #                 exam_completed      = getattr(c, 'exam_completed', False)

# #                 if exam_link_sent_date and not exam_completed:
# #                     deadline = exam_link_sent_date + timedelta(hours=ASSESSMENT_CONFIG['EXPIRY_HOURS'])
# #                     if datetime.now() < deadline:
# #                         time_remaining = (deadline - datetime.now()).total_seconds() / 3600
# #                     else:
# #                         link_expired = True

# #                 # ── Structured rejection/match fields ─────────────────────────
# #                 rejection_reasons  = _safe_json_list(getattr(c, 'rejection_reasons',  None))
# #                 missing_skills     = _safe_json_list(getattr(c, 'missing_skills',     None))
# #                 matched_skills     = _safe_json_list(getattr(c, 'matched_skills',     None))

# #                 candidate_data = {
# #                     "id":             c.id,
# #                     "name":           c.name or "Unknown",
# #                     "email":          c.email or "",
# #                     "job_id":         c.job_id,
# #                     "job_title":      getattr(c, 'job_title', None) or "Unknown Position",
# #                     "status":         c.status,
# #                     "ats_score":      float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
# #                     "linkedin":       getattr(c, 'linkedin', None),
# #                     "github":         getattr(c, 'github', None),
# #                     "phone":          getattr(c, 'phone', None),
# #                     "department":     getattr(c, 'department', None),
# #                     "resume_path":    getattr(c, 'resume_path', None),
# #                     "resume_url":     getattr(c, 'resume_path', None),
# #                     "processed_date": c.processed_date.isoformat() if getattr(c, 'processed_date', None) else None,
# #                     "score_reasoning":getattr(c, 'score_reasoning', None),

# #                     # ── Structured Why Rejected / Why Shortlisted ─────────────
# #                     # These are populated by GPT during the pipeline and are
# #                     # SPECIFIC to the actual job + resume — never generic.
# #                     "rejection_summary":    getattr(c, 'rejection_summary',   None) or "",
# #                     "rejection_reasons":    rejection_reasons,   # list of bullet strings
# #                     "missing_skills":       missing_skills,      # skills the candidate lacked
# #                     "matched_skills":       matched_skills,      # skills that matched
# #                     "experience_match":     getattr(c, 'experience_match',    None) or "",
# #                     "overall_assessment":   getattr(c, 'overall_assessment',  None) or "",

# #                     # Assessment fields
# #                     "assessment_invite_link": getattr(c, 'assessment_invite_link', None),
# #                     "exam_link_sent":      bool(getattr(c, 'exam_link_sent', False)),
# #                     "exam_link_sent_date": exam_link_sent_date.isoformat() if exam_link_sent_date else None,
# #                     "exam_completed":      bool(exam_completed),
# #                     "exam_completed_date": c.exam_completed_date.isoformat() if getattr(c, 'exam_completed_date', None) else None,
# #                     "exam_started":        bool(getattr(c, 'exam_started', False)),
# #                     "link_expired":        link_expired,
# #                     "time_remaining_hours":time_remaining,
# #                     "exam_percentage":     float(c.exam_percentage) if getattr(c, 'exam_percentage', None) else None,

# #                     # Interview scheduling
# #                     "interview_scheduled": bool(getattr(c, 'interview_scheduled', False)),
# #                     "interview_date":      c.interview_date.isoformat() if getattr(c, 'interview_date', None) else None,
# #                     "interview_link":      getattr(c, 'interview_link', None),
# #                     "interview_token":     getattr(c, 'interview_token', None),

# #                     # Interview progress
# #                     "interview_started_at":         c.interview_started_at.isoformat() if getattr(c, 'interview_started_at', None) else None,
# #                     "interview_completed_at":       c.interview_completed_at.isoformat() if getattr(c, 'interview_completed_at', None) else None,
# #                     "interview_duration":           getattr(c, 'interview_duration', 0) or 0,
# #                     "interview_progress":           getattr(c, 'interview_progress_percentage', 0) or 0,
# #                     "interview_questions_answered": getattr(c, 'interview_answered_questions', 0) or 0,
# #                     "interview_total_questions":    getattr(c, 'interview_total_questions', 0) or 0,

# #                     # Interview AI analysis
# #                     "interview_ai_score":                getattr(c, 'interview_ai_score', None),
# #                     "interview_ai_technical_score":      getattr(c, 'interview_ai_technical_score', None),
# #                     "interview_ai_communication_score":  getattr(c, 'interview_ai_communication_score', None),
# #                     "interview_ai_problem_solving_score":getattr(c, 'interview_ai_problem_solving_score', None),
# #                     "interview_ai_cultural_fit_score":   getattr(c, 'interview_ai_cultural_fit_score', None),
# #                     "interview_ai_overall_feedback":     getattr(c, 'interview_ai_overall_feedback', None),
# #                     "interview_ai_analysis_status":      getattr(c, 'interview_ai_analysis_status', None),
# #                     "interview_final_status":            getattr(c, 'interview_final_status', None),

# #                     # Interview insights
# #                     "strengths":       _safe_json_list(getattr(c, 'interview_ai_strengths',   None)),
# #                     "weaknesses":      _safe_json_list(getattr(c, 'interview_ai_weaknesses',  None)),
# #                     "recommendations": _safe_json_list(getattr(c, 'interview_recommendations',None)),

# #                     # Interview recording
# #                     "interview_recording_url": getattr(c, 'interview_recording_url', None),
# #                     "final_status":            getattr(c, 'final_status', None),
# #                 }

# #                 result.append(candidate_data)

# #             except Exception as e:
# #                 logger.error(f"Error processing candidate {getattr(c, 'id', 'unknown')}: {e}", exc_info=True)
# #                 continue

# #         logger.info(f"Successfully built {len(result)} candidate records")
# #         return result

# #     finally:
# #         session.close()


# # @candidates_bp.route('/api/candidates', methods=['GET', 'OPTIONS'])
# # @rate_limit(max_calls=60, time_window=60)
# # def api_candidates():
# #     if request.method == 'OPTIONS':
# #         return '', 200
# #     try:
# #         candidates = get_cached_candidates(
# #             request.args.get('job_id'),
# #             request.args.get('status'),
# #         )
# #         return jsonify(candidates), 200
# #     except Exception as e:
# #         logger.error(f"Error in api_candidates: {e}", exc_info=True)
# #         return jsonify({"error": "Failed to fetch candidates", "message": str(e)}), 500


# # @candidates_bp.route('/api/candidates/debug', methods=['GET'])
# # def debug_candidates():
# #     session = SessionLocal()
# #     try:
# #         all_candidates = session.query(Candidate).all()
# #         result = []
# #         for c in all_candidates:
# #             try:
# #                 result.append({
# #                     "id":               c.id,
# #                     "name":             c.name,
# #                     "email":            c.email,
# #                     "phone":            getattr(c, 'phone', None),
# #                     "department":       getattr(c, 'department', None),
# #                     "job_id":           c.job_id,
# #                     "status":           c.status,
# #                     "ats_score":        float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
# #                     "rejection_summary":getattr(c, 'rejection_summary', None),
# #                     "rejection_reasons":_safe_json_list(getattr(c, 'rejection_reasons', None)),
# #                     "missing_skills":   _safe_json_list(getattr(c, 'missing_skills',    None)),
# #                     "matched_skills":   _safe_json_list(getattr(c, 'matched_skills',    None)),
# #                     "ok":               True,
# #                 })
# #             except Exception as e:
# #                 result.append({"id": getattr(c, 'id', 'unknown'), "error": str(e), "ok": False})

# #         return jsonify({
# #             "total_in_db":         len(all_candidates),
# #             "successfully_parsed": len([r for r in result if r.get('ok')]),
# #             "failed":              len([r for r in result if not r.get('ok')]),
# #             "with_rejection_data": len([r for r in result if r.get('rejection_reasons')]),
# #             "candidates":          result,
# #         }), 200

# #     except Exception as e:
# #         return jsonify({"error": str(e)}), 500
# #     finally:
# #         session.close()
# from typing import Optional
# from flask import Blueprint, jsonify, request
# from datetime import datetime, timedelta
# import os, json, re
# from app.extensions import cache, logger
# from app.models.db import Candidate, SessionLocal
# from app.routes.shared import rate_limit

# candidates_bp = Blueprint("candidates", __name__)

# ASSESSMENT_CONFIG = {'EXPIRY_HOURS': 48}


# def _safe_json_list(raw) -> list:
#     """Safely parse a JSON list field that may be string or already a list."""
#     if not raw:
#         return []
#     if isinstance(raw, list):
#         return raw
#     try:
#         result = json.loads(raw)
#         return result if isinstance(result, list) else []
#     except Exception:
#         return []

# def parse_rejection_reasons(score_reasoning: str, status: str) -> dict:
#     """Parse raw score_reasoning text into structured rejection display data."""
#     if not score_reasoning:
#         return {"reasons": [], "missing_skills": [], "matched_skills": [], "decision": ""}

#     reasons  = []
#     missing  = []
#     matched  = []
#     decision = ""

#     for line in score_reasoning.splitlines():
#         line = line.strip()
#         if not line:
#             continue
#         if line.startswith("Decision:"):
#             decision = line.replace("Decision:", "").strip()
#         elif "Missing must-have:" in line:
#             raw     = line.replace("Missing must-have:", "").strip()
#             missing = [s.strip() for s in raw.split(",") if s.strip() and s.strip().lower() != "none"]
#         elif "Matched must-have:" in line:
#             raw     = line.replace("Matched must-have:", "").strip()
#             matched = [s.strip() for s in raw.split(",") if s.strip() and s.strip().lower() != "none"]

#     if status in ("Rejected", "Pending Review"):
#         if missing:
#             reasons.append(f"Missing required skills: {', '.join(missing)}")
#         if not matched:
#             reasons.append("No must-have skills matched the job requirements")
#         elif len(missing) > len(matched):
#             reasons.append(f"Only {len(matched)} of {len(matched) + len(missing)} required skills matched")
#         if not reasons:
#             reasons.append("Profile does not meet the minimum threshold for this role")

#     return {
#         "decision":       decision,
#         "reasons":        reasons,
#         "missing_skills": missing,
#         "matched_skills": matched,
#     }

# # @cache.memoize(timeout=180)
# # def get_cached_candidates(job_id=None, status_filter=None):
# #     session = SessionLocal()
# #     try:
# #         query = session.query(Candidate)
# #         if job_id:
# #             query = query.filter_by(job_id=str(job_id))
# #         if status_filter:
# #             query = query.filter_by(status=status_filter)

# #         candidates = query.all()
# #         logger.info(f"DB query returned {len(candidates)} candidates for job_id={job_id}, status={status_filter}")

# #         result = []
# #         for c in candidates:
# #             try:
# #                 time_remaining = None
# #                 link_expired   = False

# #                 exam_link_sent_date = getattr(c, 'exam_link_sent_date', None)
# #                 exam_completed      = getattr(c, 'exam_completed', False)

# #                 if exam_link_sent_date and not exam_completed:
# #                     deadline = exam_link_sent_date + timedelta(hours=ASSESSMENT_CONFIG['EXPIRY_HOURS'])
# #                     if datetime.now() < deadline:
# #                         time_remaining = (deadline - datetime.now()).total_seconds() / 3600
# #                     else:
# #                         link_expired = True

# #                 # ── Structured rejection/match fields ─────────────────────────
# #                 rejection_reasons  = _safe_json_list(getattr(c, 'rejection_reasons',  None))
# #                 missing_skills     = _safe_json_list(getattr(c, 'missing_skills',     None))
# #                 matched_skills     = _safe_json_list(getattr(c, 'matched_skills',     None))

# #                 candidate_data = {
# #                     "id":             c.id,
# #                     "name":           c.name or "Unknown",
# #                     "email":          c.email or "",
# #                     "job_id":         c.job_id,
# #                     "job_title":      getattr(c, 'job_title', None) or "Unknown Position",
# #                     "status":         c.status,
# #                     "ats_score":      float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
# #                     "linkedin":       getattr(c, 'linkedin', None),
# #                     "github":         getattr(c, 'github', None),
# #                     "phone":          getattr(c, 'phone', None),
# #                     "department":     getattr(c, 'department', None),
# #                     "resume_path":    getattr(c, 'resume_path', None),
# #                     "resume_url":     getattr(c, 'resume_path', None),
# #                     "processed_date": c.processed_date.isoformat() if getattr(c, 'processed_date', None) else None,
# #                     "score_reasoning":getattr(c, 'score_reasoning', None),

# #                     # ── Structured Why Rejected / Why Shortlisted ─────────────
# #                     # These are populated by GPT during the pipeline and are
# #                     # SPECIFIC to the actual job + resume — never generic.
# #                     "rejection_summary":    getattr(c, 'rejection_summary',   None) or "",
# #                     "rejection_reasons":    rejection_reasons,   # list of bullet strings
# #                     "missing_skills":       missing_skills,      # skills the candidate lacked
# #                     "matched_skills":       matched_skills,      # skills that matched
# #                     "experience_match":     getattr(c, 'experience_match',    None) or "",
# #                     "overall_assessment":   getattr(c, 'overall_assessment',  None) or "",

# #                     # Assessment fields
# #                     "assessment_invite_link": getattr(c, 'assessment_invite_link', None),
# #                     "exam_link_sent":      bool(getattr(c, 'exam_link_sent', False)),
# #                     "exam_link_sent_date": exam_link_sent_date.isoformat() if exam_link_sent_date else None,
# #                     "exam_completed":      bool(exam_completed),
# #                     "exam_completed_date": c.exam_completed_date.isoformat() if getattr(c, 'exam_completed_date', None) else None,
# #                     "exam_started":        bool(getattr(c, 'exam_started', False)),
# #                     "link_expired":        link_expired,
# #                     "time_remaining_hours":time_remaining,
# #                     "exam_percentage":     float(c.exam_percentage) if getattr(c, 'exam_percentage', None) else None,

# #                     # Interview scheduling
# #                     "interview_scheduled": bool(getattr(c, 'interview_scheduled', False)),
# #                     "interview_date":      c.interview_date.isoformat() if getattr(c, 'interview_date', None) else None,
# #                     "interview_link":      getattr(c, 'interview_link', None),
# #                     "interview_token":     getattr(c, 'interview_token', None),

# #                     # Interview progress
# #                     "interview_started_at":         c.interview_started_at.isoformat() if getattr(c, 'interview_started_at', None) else None,
# #                     "interview_completed_at":       c.interview_completed_at.isoformat() if getattr(c, 'interview_completed_at', None) else None,
# #                     "interview_duration":           getattr(c, 'interview_duration', 0) or 0,
# #                     "interview_progress":           getattr(c, 'interview_progress_percentage', 0) or 0,
# #                     "interview_questions_answered": getattr(c, 'interview_answered_questions', 0) or 0,
# #                     "interview_total_questions":    getattr(c, 'interview_total_questions', 0) or 0,

# #                     # Interview AI analysis
# #                     "interview_ai_score":                getattr(c, 'interview_ai_score', None),
# #                     "interview_ai_technical_score":      getattr(c, 'interview_ai_technical_score', None),
# #                     "interview_ai_communication_score":  getattr(c, 'interview_ai_communication_score', None),
# #                     "interview_ai_problem_solving_score":getattr(c, 'interview_ai_problem_solving_score', None),
# #                     "interview_ai_cultural_fit_score":   getattr(c, 'interview_ai_cultural_fit_score', None),
# #                     "interview_ai_overall_feedback":     getattr(c, 'interview_ai_overall_feedback', None),
# #                     "interview_ai_analysis_status":      getattr(c, 'interview_ai_analysis_status', None),
# #                     "interview_final_status":            getattr(c, 'interview_final_status', None),

# #                     # Interview insights
# #                     "strengths":       _safe_json_list(getattr(c, 'interview_ai_strengths',   None)),
# #                     "weaknesses":      _safe_json_list(getattr(c, 'interview_ai_weaknesses',  None)),
# #                     "recommendations": _safe_json_list(getattr(c, 'interview_recommendations',None)),

# #                     # Interview recording
# #                     "interview_recording_url": getattr(c, 'interview_recording_url', None),
# #                     "final_status":            getattr(c, 'final_status', None),
# #                 }

# #                 result.append(candidate_data)

# #             except Exception as e:
# #                 logger.error(f"Error processing candidate {getattr(c, 'id', 'unknown')}: {e}", exc_info=True)
# #                 continue

# #         logger.info(f"Successfully built {len(result)} candidate records")
# #         return result

# #     finally:
# #         session.close()
# @cache.memoize(timeout=180)
# def get_cached_candidates(job_id=None, status_filter=None):
#     session = SessionLocal()
#     try:
#         query = session.query(Candidate)
#         if job_id:
#             query = query.filter_by(job_id=str(job_id))
#         if status_filter:
#             query = query.filter_by(status=status_filter)

#         candidates = query.all()
#         logger.info(f"DB query returned {len(candidates)} candidates for job_id={job_id}, status={status_filter}")

#         result = []
#         for c in candidates:
#             try:
#                 time_remaining = None
#                 link_expired   = False

#                 exam_link_sent_date = getattr(c, 'exam_link_sent_date', None)
#                 exam_completed      = getattr(c, 'exam_completed', False)

#                 if exam_link_sent_date and not exam_completed:
#                     deadline = exam_link_sent_date + timedelta(hours=ASSESSMENT_CONFIG['EXPIRY_HOURS'])
#                     if datetime.now() < deadline:
#                         time_remaining = (deadline - datetime.now()).total_seconds() / 3600
#                     else:
#                         link_expired = True

#                 # ── Parse rejection reasons from score_reasoning ──────────────
#                 _parsed = parse_rejection_reasons(
#                     score_reasoning=getattr(c, 'score_reasoning', None) or "",
#                     status=c.status or "",
#                 )
#                 rejection_reasons = _parsed["reasons"]
#                 missing_skills    = _parsed["missing_skills"]
#                 matched_skills    = _parsed["matched_skills"]

#                 candidate_data = {
#                     "id":             c.id,
#                     "name":           c.name or "Unknown",
#                     "email":          c.email or "",
#                     "job_id":         c.job_id,
#                     "job_title":      getattr(c, 'job_title', None) or "Unknown Position",
#                     "status":         c.status,
#                     "ats_score":      float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
#                     "linkedin":       getattr(c, 'linkedin', None),
#                     "github":         getattr(c, 'github', None),
#                     "phone":          getattr(c, 'phone', None),
#                     "department":     getattr(c, 'department', None),
#                     "resume_path":    getattr(c, 'resume_path', None),
#                     "resume_url":     getattr(c, 'resume_path', None),
#                     "processed_date": c.processed_date.isoformat() if getattr(c, 'processed_date', None) else None,
#                     "score_reasoning":getattr(c, 'score_reasoning', None),

#                     # ── Structured Why Rejected / Why Shortlisted ─────────────
#                     "rejection_breakdown":  _parsed,
#                     "rejection_reasons":    rejection_reasons,
#                     "missing_skills":       missing_skills,
#                     "matched_skills":       matched_skills,
#                     "experience_match":     getattr(c, 'experience_match',    None) or "",
#                     "overall_assessment":   getattr(c, 'overall_assessment',  None) or "",

#                     # Assessment fields
#                     "assessment_invite_link": getattr(c, 'assessment_invite_link', None),
#                     "exam_link_sent":      bool(getattr(c, 'exam_link_sent', False)),
#                     "exam_link_sent_date": exam_link_sent_date.isoformat() if exam_link_sent_date else None,
#                     "exam_completed":      bool(exam_completed),
#                     "exam_completed_date": c.exam_completed_date.isoformat() if getattr(c, 'exam_completed_date', None) else None,
#                     "exam_started":        bool(getattr(c, 'exam_started', False)),
#                     "link_expired":        link_expired,
#                     "time_remaining_hours":time_remaining,
#                     "exam_percentage":     float(c.exam_percentage) if getattr(c, 'exam_percentage', None) else None,

#                     # Interview scheduling
#                     "interview_scheduled": bool(getattr(c, 'interview_scheduled', False)),
#                     "interview_date":      c.interview_date.isoformat() if getattr(c, 'interview_date', None) else None,
#                     "interview_link":      getattr(c, 'interview_link', None),
#                     "interview_token":     getattr(c, 'interview_token', None),

#                     # Interview progress
#                     "interview_started_at":         c.interview_started_at.isoformat() if getattr(c, 'interview_started_at', None) else None,
#                     "interview_completed_at":       c.interview_completed_at.isoformat() if getattr(c, 'interview_completed_at', None) else None,
#                     "interview_duration":           getattr(c, 'interview_duration', 0) or 0,
#                     "interview_progress":           getattr(c, 'interview_progress_percentage', 0) or 0,
#                     "interview_questions_answered": getattr(c, 'interview_answered_questions', 0) or 0,
#                     "interview_total_questions":    getattr(c, 'interview_total_questions', 0) or 0,

#                     # Interview AI analysis
#                     "interview_ai_score":                getattr(c, 'interview_ai_score', None),
#                     "interview_ai_technical_score":      getattr(c, 'interview_ai_technical_score', None),
#                     "interview_ai_communication_score":  getattr(c, 'interview_ai_communication_score', None),
#                     "interview_ai_problem_solving_score":getattr(c, 'interview_ai_problem_solving_score', None),
#                     "interview_ai_cultural_fit_score":   getattr(c, 'interview_ai_cultural_fit_score', None),
#                     "interview_ai_overall_feedback":     getattr(c, 'interview_ai_overall_feedback', None),
#                     "interview_ai_analysis_status":      getattr(c, 'interview_ai_analysis_status', None),
#                     "interview_final_status":            getattr(c, 'interview_final_status', None),

#                     # Interview insights
#                     "strengths":       _safe_json_list(getattr(c, 'interview_ai_strengths',   None)),
#                     "weaknesses":      _safe_json_list(getattr(c, 'interview_ai_weaknesses',  None)),
#                     "recommendations": _safe_json_list(getattr(c, 'interview_recommendations',None)),

#                     # Interview recording
#                     "interview_recording_url": getattr(c, 'interview_recording_url', None),
#                     "final_status":            getattr(c, 'final_status', None),
#                 }

#                 result.append(candidate_data)

#             except Exception as e:
#                 logger.error(f"Error processing candidate {getattr(c, 'id', 'unknown')}: {e}", exc_info=True)
#                 continue

#         logger.info(f"Successfully built {len(result)} candidate records")
#         return result

#     finally:
#         session.close()


# @candidates_bp.route('/api/candidates', methods=['GET', 'OPTIONS'])
# @rate_limit(max_calls=60, time_window=60)
# def api_candidates():
#     if request.method == 'OPTIONS':
#         return '', 200
#     try:
#         candidates = get_cached_candidates(
#             request.args.get('job_id'),
#             request.args.get('status'),
#         )
#         return jsonify(candidates), 200
#     except Exception as e:
#         logger.error(f"Error in api_candidates: {e}", exc_info=True)
#         return jsonify({"error": "Failed to fetch candidates", "message": str(e)}), 500


# @candidates_bp.route('/api/candidates/debug', methods=['GET'])
# def debug_candidates():
#     session = SessionLocal()
#     try:
#         all_candidates = session.query(Candidate).all()
#         result = []
#         for c in all_candidates:
#             try:
#                 result.append({
#                     "id":               c.id,
#                     "name":             c.name,
#                     "email":            c.email,
#                     "phone":            getattr(c, 'phone', None),
#                     "department":       getattr(c, 'department', None),
#                     "job_id":           c.job_id,
#                     "status":           c.status,
#                     "ats_score":        float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
#                     "rejection_summary":getattr(c, 'rejection_summary', None),
#                     "rejection_reasons":_safe_json_list(getattr(c, 'rejection_reasons', None)),
#                     "missing_skills":   _safe_json_list(getattr(c, 'missing_skills',    None)),
#                     "matched_skills":   _safe_json_list(getattr(c, 'matched_skills',    None)),
#                     "ok":               True,
#                 })
#             except Exception as e:
#                 result.append({"id": getattr(c, 'id', 'unknown'), "error": str(e), "ok": False})

#         return jsonify({
#             "total_in_db":         len(all_candidates),
#             "successfully_parsed": len([r for r in result if r.get('ok')]),
#             "failed":              len([r for r in result if not r.get('ok')]),
#             "with_rejection_data": len([r for r in result if r.get('rejection_reasons')]),
#             "candidates":          result,
#         }), 200

#     except Exception as e:
#         return jsonify({"error": str(e)}), 500
#     finally:
#         session.close()
from typing import Optional
from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import os, json, re, math
from app.extensions import cache, logger
from app.models.db import Candidate, SessionLocal
from app.routes.shared import rate_limit

candidates_bp = Blueprint("candidates", __name__)

ASSESSMENT_CONFIG = {'EXPIRY_HOURS': 48}


def _safe_json_list(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def parse_rejection_reasons(score_reasoning: str, status: str) -> dict:
    if not score_reasoning:
        return {"reasons": [], "missing_skills": [], "matched_skills": [], "decision": ""}

    reasons  = []
    missing  = []
    matched  = []
    decision = ""

    for line in score_reasoning.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Decision:"):
            decision = line.replace("Decision:", "").strip()
        elif "Missing must-have:" in line:
            raw     = line.replace("Missing must-have:", "").strip()
            missing = [s.strip() for s in raw.split(",") if s.strip() and s.strip().lower() != "none"]
        elif "Matched must-have:" in line:
            raw     = line.replace("Matched must-have:", "").strip()
            matched = [s.strip() for s in raw.split(",") if s.strip() and s.strip().lower() != "none"]

    if status in ("Rejected", "Pending Review"):
        if missing:
            reasons.append(f"Missing required skills: {', '.join(missing)}")
        if not matched:
            reasons.append("No must-have skills matched the job requirements")
        elif len(missing) > len(matched):
            reasons.append(f"Only {len(matched)} of {len(matched) + len(missing)} required skills matched")
        if not reasons:
            reasons.append("Profile does not meet the minimum threshold for this role")

    return {
        "decision":       decision,
        "reasons":        reasons,
        "missing_skills": missing,
        "matched_skills": matched,
    }


# ── Red flag detector ─────────────────────────────────────────────────────────
def get_red_flags(c) -> list[str]:
    """
    Returns list of active red flag strings for a candidate.
    Empty list = no red flags.
    """
    flags = []

    # 1. Cheating detected in assessment
    if getattr(c, 'exam_cheating_flag', False):
        flags.append("Cheating Detected")

    # 2. Score contradiction — AI says Strong Fit but ATS score is low
    match_type = getattr(c, 'match_type', None)
    ats = float(getattr(c, 'ats_score', 0) or 0)
    if match_type == "Strong Fit" and ats < 60:
        flags.append("Score Mismatch")

    # 3. Link expired, never started
    link_expired   = getattr(c, 'link_expired', False)
    exam_started   = getattr(c, 'exam_started', False)
    exam_completed = getattr(c, 'exam_completed', False)
    if link_expired and not exam_completed:
        flags.append("Assessment Expired")

    # 4. Assessment started but abandoned
    if exam_started and not exam_completed:
        flags.append("Assessment Abandoned")

    # 5. Very low score but still Active (auto-decision may not have fired)
    status = getattr(c, 'status', '') or ''
    if ats > 0 and ats < 40 and status not in ('Rejected', 'Pending Review'):
        flags.append("Very Low Score")

    return flags


# ── KNN feature vector ────────────────────────────────────────────────────────
def _knn_vector(c) -> list[float]:
    """
    Normalised feature vector for KNN distance calculation.
    All values scaled to 0-1 so no single feature dominates.
    Features: ats_score, match_score, matched_skills_count, missing_skills_count (inverted), exam_percentage
    """
    ats       = float(getattr(c, 'ats_score',      0) or 0) / 100.0
    match_sc  = float(getattr(c, 'match_score',    0) or 0) / 100.0
    matched   = len(_safe_json_list(getattr(c, 'matched_skills', None))) / 10.0  # normalise to ~10 max skills
    missing   = 1.0 - min(len(_safe_json_list(getattr(c, 'missing_skills', None))) / 10.0, 1.0)  # invert — fewer missing = better
    exam_pct  = float(getattr(c, 'exam_percentage', 0) or 0) / 100.0

    return [ats, match_sc, matched, missing, exam_pct]


def _euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@cache.memoize(timeout=180)
def get_cached_candidates(job_id=None, status_filter=None):
    session = SessionLocal()
    try:
        query = session.query(Candidate)
        if job_id:
            query = query.filter_by(job_id=str(job_id))
        if status_filter:
            query = query.filter_by(status=status_filter)

        candidates = query.all()
        logger.info(f"DB query returned {len(candidates)} candidates for job_id={job_id}, status={status_filter}")

        result = []
        for c in candidates:
            try:
                time_remaining = None
                link_expired   = False

                exam_link_sent_date = getattr(c, 'exam_link_sent_date', None)
                exam_completed      = getattr(c, 'exam_completed', False)

                if exam_link_sent_date and not exam_completed:
                    deadline = exam_link_sent_date + timedelta(hours=ASSESSMENT_CONFIG['EXPIRY_HOURS'])
                    if datetime.now() < deadline:
                        time_remaining = (deadline - datetime.now()).total_seconds() / 3600
                    else:
                        link_expired = True

                _parsed = parse_rejection_reasons(
                    score_reasoning=getattr(c, 'score_reasoning', None) or "",
                    status=c.status or "",
                )
                rejection_reasons = _parsed["reasons"]
                missing_skills    = _parsed["missing_skills"]
                matched_skills    = _parsed["matched_skills"]

                # ── Red flags computed per candidate ──────────────────────────
                red_flags = get_red_flags(c)

                candidate_data = {
                    "id":             c.id,
                    "name":           c.name or "Unknown",
                    "email":          c.email or "",
                    "job_id":         c.job_id,
                    "job_title":      getattr(c, 'job_title', None) or "Unknown Position",
                    "status":         c.status,
                    "ats_score":      float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
                    "linkedin":       getattr(c, 'linkedin', None),
                    "github":         getattr(c, 'github', None),
                    "phone":          getattr(c, 'phone', None),
                    "department":     getattr(c, 'department', None),
                    "resume_path":    getattr(c, 'resume_path', None),
                    "resume_url":     getattr(c, 'resume_path', None),
                    "processed_date": c.processed_date.isoformat() if getattr(c, 'processed_date', None) else None,
                    "score_reasoning":getattr(c, 'score_reasoning', None),

                    # ── Rejection / match ─────────────────────────────────────
                    "rejection_breakdown":  _parsed,
                    "rejection_reasons":    rejection_reasons,
                    "missing_skills":       missing_skills,
                    "matched_skills":       matched_skills,
                    "experience_match":     getattr(c, 'experience_match',   None) or "",
                    "overall_assessment":   getattr(c, 'overall_assessment', None) or "",

                    # ── NEW: JD matching fields ───────────────────────────────
                    "match_type":           getattr(c, 'match_type',          None),
                    "match_score":          getattr(c, 'match_score',         None),
                    "recommendation":       getattr(c, 'recommendation',      None),
                    "auto_decision_taken":  getattr(c, 'auto_decision_taken', None),

                    # ── NEW: Red flags ────────────────────────────────────────
                    "red_flags":            red_flags,
                    "has_red_flags":        len(red_flags) > 0,
                    "exam_cheating_flag":   bool(getattr(c, 'exam_cheating_flag', False)),

                    # Assessment fields
                    "assessment_invite_link": getattr(c, 'assessment_invite_link', None),
                    "exam_link_sent":      bool(getattr(c, 'exam_link_sent', False)),
                    "exam_link_sent_date": exam_link_sent_date.isoformat() if exam_link_sent_date else None,
                    "exam_completed":      bool(exam_completed),
                    "exam_completed_date": c.exam_completed_date.isoformat() if getattr(c, 'exam_completed_date', None) else None,
                    "exam_started":        bool(getattr(c, 'exam_started', False)),
                    "link_expired":        link_expired,
                    "time_remaining_hours":time_remaining,
                    "exam_percentage":     float(c.exam_percentage) if getattr(c, 'exam_percentage', None) else None,

                    # Interview scheduling
                    "interview_scheduled": bool(getattr(c, 'interview_scheduled', False)),
                    "interview_date":      c.interview_date.isoformat() if getattr(c, 'interview_date', None) else None,
                    "interview_link":      getattr(c, 'interview_link', None),
                    "interview_token":     getattr(c, 'interview_token', None),

                    # Interview progress
                    "interview_started_at":         c.interview_started_at.isoformat() if getattr(c, 'interview_started_at', None) else None,
                    "interview_completed_at":       c.interview_completed_at.isoformat() if getattr(c, 'interview_completed_at', None) else None,
                    "interview_duration":           getattr(c, 'interview_duration', 0) or 0,
                    "interview_progress":           getattr(c, 'interview_progress_percentage', 0) or 0,
                    "interview_questions_answered": getattr(c, 'interview_answered_questions', 0) or 0,
                    "interview_total_questions":    getattr(c, 'interview_total_questions', 0) or 0,

                    # Interview AI analysis
                    "interview_ai_score":                getattr(c, 'interview_ai_score', None),
                    "interview_ai_technical_score":      getattr(c, 'interview_ai_technical_score', None),
                    "interview_ai_communication_score":  getattr(c, 'interview_ai_communication_score', None),
                    "interview_ai_problem_solving_score":getattr(c, 'interview_ai_problem_solving_score', None),
                    "interview_ai_cultural_fit_score":   getattr(c, 'interview_ai_cultural_fit_score', None),
                    "interview_ai_overall_feedback":     getattr(c, 'interview_ai_overall_feedback', None),
                    "interview_ai_analysis_status":      getattr(c, 'interview_ai_analysis_status', None),
                    "interview_final_status":            getattr(c, 'interview_final_status', None),

                    # Interview insights
                    "strengths":       _safe_json_list(getattr(c, 'interview_ai_strengths',   None)),
                    "weaknesses":      _safe_json_list(getattr(c, 'interview_ai_weaknesses',  None)),
                    "recommendations": _safe_json_list(getattr(c, 'interview_recommendations',None)),

                    "interview_recording_url": getattr(c, 'interview_recording_url', None),
                    "final_status":            getattr(c, 'final_status', None),
                }

                result.append(candidate_data)

            except Exception as e:
                logger.error(f"Error processing candidate {getattr(c, 'id', 'unknown')}: {e}", exc_info=True)
                continue

        logger.info(f"Successfully built {len(result)} candidate records")
        return result

    finally:
        session.close()


@candidates_bp.route('/api/candidates', methods=['GET', 'OPTIONS'])
@rate_limit(max_calls=60, time_window=60)
def api_candidates():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        candidates = get_cached_candidates(
            request.args.get('job_id'),
            request.args.get('status'),
        )
        return jsonify(candidates), 200
    except Exception as e:
        logger.error(f"Error in api_candidates: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch candidates", "message": str(e)}), 500


# ── KNN Top 10 ────────────────────────────────────────────────────────────────
@candidates_bp.route('/api/candidates/top10', methods=['GET', 'OPTIONS'])
@rate_limit(max_calls=30, time_window=60)
def api_top10_candidates():
    """
    Returns the top 10 candidates for a job using K-Nearest Neighbors.
    Ideal point = perfect candidate (all scores = 1.0).
    Candidates closest to that point are the best matches.

    Query params:
        job_id (optional) — filter by job
        n      (optional) — number to return, default 10
    """
    if request.method == 'OPTIONS':
        return '', 200

    session = SessionLocal()
    try:
        job_id = request.args.get('job_id')
        n      = min(int(request.args.get('n', 10)), 50)

        query = session.query(Candidate)
        if job_id:
            query = query.filter_by(job_id=str(job_id))

        candidates = query.all()

        # Ideal candidate point — perfect score on every dimension
        ideal = [1.0, 1.0, 1.0, 1.0, 1.0]

        scored = []
        for c in candidates:
            vec  = _knn_vector(c)
            dist = _euclidean(vec, ideal)
            scored.append((dist, c))

        # Sort by distance ascending — closest to ideal first
        scored.sort(key=lambda x: x[0])
        top = scored[:n]

        result = []
        for rank, (dist, c) in enumerate(top, start=1):
            result.append({
                "rank":           rank,
                "knn_distance":   round(dist, 4),
                "id":             c.id,
                "name":           c.name or "Unknown",
                "email":          c.email or "",
                "job_title":      getattr(c, 'job_title', None) or "",
                "ats_score":      float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
                "match_type":     getattr(c, 'match_type',     None),
                "match_score":    getattr(c, 'match_score',    None),
                "recommendation": getattr(c, 'recommendation', None),
                "status":         c.status,
                "matched_skills": _safe_json_list(getattr(c, 'matched_skills', None)),
                "missing_skills": _safe_json_list(getattr(c, 'missing_skills', None)),
                "red_flags":      get_red_flags(c),
                "processed_date": c.processed_date.isoformat() if getattr(c, 'processed_date', None) else None,
            })

        return jsonify({
            "success":   True,
            "job_id":    job_id,
            "algorithm": "KNN euclidean distance to ideal candidate",
            "total_pool":len(candidates),
            "returned":  len(result),
            "top":       result,
        }), 200

    except Exception as e:
        logger.error(f"top10 error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ── Red Flags endpoint ────────────────────────────────────────────────────────
@candidates_bp.route('/api/candidates/red-flags', methods=['GET', 'OPTIONS'])
@rate_limit(max_calls=30, time_window=60)
def api_red_flag_candidates():
    """
    Returns all candidates with at least one active red flag.
    Red flags: cheating, score mismatch, expired link, abandoned assessment, very low score.

    Query params:
        job_id (optional)
        flag   (optional) — filter to a specific flag type
    """
    if request.method == 'OPTIONS':
        return '', 200

    session = SessionLocal()
    try:
        job_id    = request.args.get('job_id')
        flag_type = request.args.get('flag')

        query = session.query(Candidate)
        if job_id:
            query = query.filter_by(job_id=str(job_id))

        candidates = query.all()
        result     = []

        for c in candidates:
            flags = get_red_flags(c)
            if not flags:
                continue
            if flag_type and flag_type not in flags:
                continue

            result.append({
                "id":             c.id,
                "name":           c.name or "Unknown",
                "email":          c.email or "",
                "job_title":      getattr(c, 'job_title', None) or "",
                "ats_score":      float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
                "status":         c.status,
                "red_flags":      flags,
                "flag_count":     len(flags),
                "match_type":     getattr(c, 'match_type',     None),
                "recommendation": getattr(c, 'recommendation', None),
                "processed_date": c.processed_date.isoformat() if getattr(c, 'processed_date', None) else None,
            })

        # Sort by flag_count descending — most flagged first
        result.sort(key=lambda x: x["flag_count"], reverse=True)

        return jsonify({
            "success":    True,
            "job_id":     job_id,
            "total_flagged": len(result),
            "candidates": result,
            "flag_types": ["Cheating Detected", "Score Mismatch", "Assessment Expired",
                           "Assessment Abandoned", "Very Low Score"],
        }), 200

    except Exception as e:
        logger.error(f"red-flags error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@candidates_bp.route('/api/candidates/debug', methods=['GET'])
def debug_candidates():
    session = SessionLocal()
    try:
        all_candidates = session.query(Candidate).all()
        result = []
        for c in all_candidates:
            try:
                result.append({
                    "id":               c.id,
                    "name":             c.name,
                    "email":            c.email,
                    "phone":            getattr(c, 'phone', None),
                    "department":       getattr(c, 'department', None),
                    "job_id":           c.job_id,
                    "status":           c.status,
                    "ats_score":        float(c.ats_score) if getattr(c, 'ats_score', None) else 0.0,
                    "match_type":       getattr(c, 'match_type', None),
                    "recommendation":   getattr(c, 'recommendation', None),
                    "red_flags":        get_red_flags(c),
                    "rejection_summary":getattr(c, 'rejection_summary', None),
                    "rejection_reasons":_safe_json_list(getattr(c, 'rejection_reasons', None)),
                    "missing_skills":   _safe_json_list(getattr(c, 'missing_skills',    None)),
                    "matched_skills":   _safe_json_list(getattr(c, 'matched_skills',    None)),
                    "ok":               True,
                })
            except Exception as e:
                result.append({"id": getattr(c, 'id', 'unknown'), "error": str(e), "ok": False})

        return jsonify({
            "total_in_db":         len(all_candidates),
            "successfully_parsed": len([r for r in result if r.get('ok')]),
            "failed":              len([r for r in result if not r.get('ok')]),
            "with_red_flags":      len([r for r in result if r.get('red_flags')]),
            "candidates":          result,
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()