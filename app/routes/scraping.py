# from datetime import datetime
# import os
# from flask import Blueprint, request, jsonify
# import threading, time, asyncio, traceback
# from app.routes.shared import rate_limit
# from app.extensions import logger
# from app.utils.email_util import send_email
# from app.models.db import AssessmentResult, SessionLocal

# scraping_bp = Blueprint("scraping", __name__)

# def notify_admin(subject, message, error_details=None):
#     """Send critical notifications to admin"""
#     try:
#         admin_email = os.getenv('ADMIN_EMAIL')
#         if not admin_email:
#             logger.warning("ADMIN_EMAIL not set, skipping notification")
#             return
        
#         from email_util import send_email
        
#         body_html = f"""
#         <html>
#             <body>
#                 <h2>TalentFlow AI Alert: {subject}</h2>
#                 <p>{message}</p>
#                 {f'<pre>{error_details}</pre>' if error_details else ''}
#                 <p>Time: {datetime.now().isoformat()}</p>
#             </body>
#         </html>
#         """
        
#         send_email(admin_email, f"[TalentFlow Alert] {subject}", body_html)
        
#     except Exception as e:
#         logger.error(f"Failed to send admin notification: {e}")

# @scraping_bp.route('/api/scrape_assessment_results', methods=['POST','OPTIONS'])
# @rate_limit(max_calls=3, time_window=300)  # Max 3 scraping requests per 5 minutes
# def api_scrape_assessment_results():
#     """API endpoint to scrape assessment results for a specific assessment"""
#     if request.method == 'OPTIONS':
#         return '', 200
        
#     try:
#         data = request.json
#         assessment_name = data.get('assessment_name')
#         source = data.get("source", "testlify")  # NEW FIELD

#         if not assessment_name:
#             return jsonify({"success": False, "message": "assessment_name is required"}), 400
        
#         logger.info(f"[SCRAPER] Starting results scraping for assessment: {assessment_name} (source={source})")
        
#         # Start scraping in a separate thread
#         scraping_thread = threading.Thread(
#             target=lambda: run_scraping_with_monitoring(assessment_name, source),
#             daemon=True,
#             name=f"scraping_{source}_{assessment_name.replace(' ', '_')}_{int(time.time())}"
#         )
#         scraping_thread.start()
        
#         return jsonify({
#             "success": True,
#             "message": f"Started scraping ({source}) for '{assessment_name}'",
#             "estimated_time": "2-10 minutes"
#         }), 200
        
#     except Exception as e:
#         logger.error(f"Error in scrape_assessment_results: {e}", exc_info=True)
#         return jsonify({"success": False, "message": str(e)}), 500

# @scraping_bp.route('/api/scrape_all_pending_results', methods=['POST','OPTIONS'])
# @rate_limit(max_calls=1, time_window=600)  # Max 1 bulk scraping per 10 minutes
# def api_scrape_all_pending_results():
#     """API endpoint to scrape all pending assessment results"""
#     if request.method == 'OPTIONS':
#         return '', 200
        
#     try:
#         logger.info("[SCRAPER] Starting bulk results scraping for all pending assessments")
        
#         scraping_thread = threading.Thread(
#             target=lambda: run_bulk_scraping_with_monitoring(),
#             daemon=True,
#             name=f"bulk_scraping_{int(time.time())}"
#         )
#         scraping_thread.start()
        
#         return jsonify({
#             "success": True,
#             "message": "Started bulk scraping for all pending assessments",
#             "estimated_time": "5-15 minutes"
#         }), 200
        
#     except Exception as e:
#         logger.error(f"Error in scrape_all_pending_results: {e}", exc_info=True)
#         return jsonify({"success": False, "message": str(e)}), 500

# @scraping_bp.route('/api/scrape_assessment_results', methods=['GET','OPTIONS'])
# def api_scraping_status():
#     """Get status of running scraping operations"""
#     try:
#         active_threads = []
#         for thread in threading.enumerate():
#             if thread.name.startswith(('scraping_', 'bulk_scraping_')):
#                 thread_info = {
#                     "name": thread.name,
#                     "is_alive": thread.is_alive(),
#                     "daemon": thread.daemon
#                 }
#                 active_threads.append(thread_info)
        
#         return jsonify({
#             "success": True,
#             "active_operations": len(active_threads),
#             "operations": active_threads
#         }), 200
        
#     except Exception as e:
#         logger.error(f"Error in scraping_status: {e}", exc_info=True)
#         return jsonify({"success": False, "message": str(e)}), 500


# def run_scraping_with_monitoring(assessment_name: str, source: str):
#         """Wrapper to run scraping with monitoring and error handling"""
#         start_time = time.time()

#         logger.info(f"[SCRAPER] Running monitored scraping for '{assessment_name}' using {source}")

#         try:
#             if source == "testlify":
#                 run_testlify_scraper(assessment_name)

#             elif source == "criteria":
#                 run_criteria_scraper(assessment_name)

#             else:
#                 logger.error(f"❌ Invalid scraper source: {source}")
#                 return

#             duration = time.time() - start_time
#             logger.info(f"✅ Scraping ({source}) completed in {duration:.2f} seconds.")

#             notify_admin(
#                 f"{source.capitalize()} Scraping Completed",
#                 f"Assessment: {assessment_name}\nDuration: {duration:.2f} seconds"
#             )

#         except Exception as e:
#             duration = time.time() - start_time
#             error_msg = f"❌ Scraping failed ({source}) for '{assessment_name}' after {duration:.2f} seconds"
#             logger.error(error_msg, exc_info=True)

#             notify_admin(
#                 f"{source.capitalize()} Scraping Failed",
#                 error_msg,
#                 error_details=traceback.format_exc()
#         )
# def run_testlify_scraper(assessment_name):
#     try:
#         from testlify_results_scraper import scrape_assessment_results_by_name

#         logger.info(f"[TESTLIFY] Starting scraper for: {assessment_name}")

#         loop = asyncio.new_event_loop()
#         asyncio.set_event_loop(loop)

#         results = loop.run_until_complete(
#             scrape_assessment_results_by_name(assessment_name)
#         )
#         loop.close()

#         logger.info(f"[TESTLIFY] Completed. Results found: {len(results)}")

#     except Exception as e:
#         logger.error(f"[TESTLIFY] Error: {e}", exc_info=True)

# def run_criteria_scraper(assessment_name):
#     try:
#         import subprocess, sys, json
#         from app.models import AssessmentResult, db   # adjust import path

#         logger.info(f"[CRITERIA] Starting scraper for: {assessment_name}")

#         # Run script
#         process = subprocess.Popen(
#             [sys.executable, "Criteria_score.py", assessment_name],
#             stdout=subprocess.PIPE,
#             stderr=subprocess.PIPE,
#             text=True
#         )

#         out, err = process.communicate()

#         if err:
#             logger.error("[CRITERIA] Errors:\n" + err)

#         # Parse JSON output
#         results = json.loads(out)

#         logger.info(f"[CRITERIA] Found {len(results)} results")

#         # Insert each result into DB
#         for r in results:
#             record = AssessmentResult(
#                 assessment_name=assessment_name,
#                 candidate_name=r["name"],
#                 candidate_email=r["email"],
#                 score=r["score"],
#                 status=r["status"],
#                 provider="criteria"
#             )
#             db.session.add(record)

#         db.session.commit()

#         logger.info("[CRITERIA] Results saved to DB")

#     except Exception as e:
#         logger.error(f"[CRITERIA] Failed: {e}", exc_info=True)

            
# def run_bulk_scraping_with_monitoring():
#     """Wrapper to run bulk scraping with monitoring"""
#     start_time = time.time()
    
#     try:
#         logger.info("Starting bulk scraping for all pending assessments")
        
#         # Import and run the bulk scraping function
#         try:
#             from testlify_results_scraper import scrape_all_pending_assessments
#         except ImportError as e:
#             logger.error(f"Failed to import scraper: {e}")
#             notify_admin(
#                 "Scraper Import Error",
#                 f"Could not import results scraper: {str(e)}. Please ensure testlify_results_scraper.py is available."
#             )
#             return
        
#         # Run the async scraping function
#         loop = asyncio.new_event_loop()
#         asyncio.set_event_loop(loop)
#         try:
#             results_summary = loop.run_until_complete(scrape_all_pending_assessments())
#         finally:
#             loop.close()
        
#         duration = time.time() - start_time
#         total_candidates = sum(results_summary.values()) if isinstance(results_summary, dict) else 0
        
#         logger.info(f"Bulk scraping completed in {duration:.2f} seconds. Processed {len(results_summary)} assessments, {total_candidates} candidates.")
        
#         # Send success notification
#         if isinstance(results_summary, dict):
#             summary_text = "\n".join([f"- {assessment}: {count} candidates" for assessment, count in results_summary.items()])
#         else:
#             summary_text = f"Processed {total_candidates} total candidates"
            
#         notify_admin(
#             "Bulk Assessment Results Scraping Completed",
#             f"Assessments processed: {len(results_summary) if isinstance(results_summary, dict) else 'Unknown'}\nTotal candidates: {total_candidates}\nDuration: {duration:.2f} seconds\n\nBreakdown:\n{summary_text}"
#         )
        
#     except Exception as e:
#         duration = time.time() - start_time
#         error_msg = f"Bulk scraping failed after {duration:.2f} seconds"
#         logger.error(error_msg, exc_info=True)
        
#         # Send failure notification
#         notify_admin(
#             "Bulk Assessment Results Scraping Failed",
#             error_msg,
#             error_details=traceback.format_exc()
#         )
#from datetime import datetime
from datetime import datetime
import os
import sys
import json
import subprocess
from flask import Blueprint, request, jsonify
import threading
import time
import asyncio
import traceback
from app.routes.shared import rate_limit
from app.extensions import logger
from app.utils.email_util import send_email
from app.models.db import SessionLocal, Candidate, AssessmentResult

scraping_bp = Blueprint("scraping", __name__)

def notify_admin(subject, message, error_details=None):
    """Send critical notifications to admin"""
    try:
        admin_email = os.getenv('ADMIN_EMAIL')
        if not admin_email:
            logger.warning("ADMIN_EMAIL not set, skipping notification")
            return
        
        body_html = f"""
        <html>
            <body>
                <h2>TalentFlow AI Alert: {subject}</h2>
                <p>{message}</p>
                {f'<pre>{error_details}</pre>' if error_details else ''}
                <p>Time: {datetime.now().isoformat()}</p>
            </body>
        </html>
        """
        
        send_email(admin_email, f"[TalentFlow Alert] {subject}", body_html)
        
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}")

@scraping_bp.route('/api/scrape_assessment_results', methods=['POST', 'OPTIONS'])
@rate_limit(max_calls=3, time_window=300)  # Max 3 scraping requests per 5 minutes
def api_scrape_assessment_results():
    """API endpoint to scrape assessment results for a specific assessment"""
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        data = request.json
        assessment_name = data.get('assessment_name')
        source = data.get("source", "testlify")  # Default to testlify if not specified

        if not assessment_name:
            return jsonify({"success": False, "message": "assessment_name is required"}), 400
        
        logger.info(f"[SCRAPER] Starting results scraping for assessment: {assessment_name} (source={source})")
        
        # Start scraping in a separate thread
        scraping_thread = threading.Thread(
            target=lambda: run_scraping_with_monitoring(assessment_name, source),
            daemon=True,
            name=f"scraping_{source}_{assessment_name.replace(' ', '_')}_{int(time.time())}"
        )
        scraping_thread.start()
        
        return jsonify({
            "success": True,
            "message": f"Started scraping ({source}) for '{assessment_name}'",
            "estimated_time": "2-10 minutes"
        }), 200
        
    except Exception as e:
        logger.error(f"Error in scrape_assessment_results: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500

@scraping_bp.route('/api/scrape_all_pending_results', methods=['POST', 'OPTIONS'])
@rate_limit(max_calls=1, time_window=600)  # Max 1 bulk scraping per 10 minutes
def api_scrape_all_pending_results():
    """API endpoint to scrape all pending assessment results"""
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        logger.info("[SCRAPER] Starting bulk results scraping for all pending assessments")
        
        scraping_thread = threading.Thread(
            target=lambda: run_bulk_scraping_with_monitoring(),
            daemon=True,
            name=f"bulk_scraping_{int(time.time())}"
        )
        scraping_thread.start()
        
        return jsonify({
            "success": True,
            "message": "Started bulk scraping for all pending assessments",
            "estimated_time": "5-15 minutes"
        }), 200
        
    except Exception as e:
        logger.error(f"Error in scrape_all_pending_results: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500

@scraping_bp.route('/api/scraping_status', methods=['GET', 'OPTIONS'])
def api_scraping_status():
    """Get status of running scraping operations"""
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        active_threads = []
        for thread in threading.enumerate():
            if thread.name.startswith(('scraping_', 'bulk_scraping_')):
                thread_info = {
                    "name": thread.name,
                    "is_alive": thread.is_alive(),
                    "daemon": thread.daemon
                }
                active_threads.append(thread_info)
        
        return jsonify({
            "success": True,
            "active_operations": len(active_threads),
            "operations": active_threads
        }), 200
        
    except Exception as e:
        logger.error(f"Error in scraping_status: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500

@scraping_bp.route('/api/assessment_results', methods=['GET', 'OPTIONS'])
def get_all_assessment_results():
    """Get assessment results from both Testlify and Criteria"""
    if request.method == 'OPTIONS':
        return '', 200
        
    session = SessionLocal()
    try:
        provider = request.args.get('provider')  # 'testlify', 'criteria', or None for all
        assessment_name = request.args.get('assessment_name')
        min_score = request.args.get('min_score', type=float)
        max_score = request.args.get('max_score', type=float)
        
        query = session.query(AssessmentResult)
        
        if provider:
            query = query.filter(AssessmentResult.provider == provider)
        if assessment_name:
            query = query.filter(AssessmentResult.assessment_name == assessment_name)
        if min_score is not None:
            query = query.filter(AssessmentResult.score >= min_score)
        if max_score is not None:
            query = query.filter(AssessmentResult.score <= max_score)
        
        results = query.order_by(AssessmentResult.created_at.desc()).all()
        
        results_data = []
        for r in results:
            data = {
                "id": r.id,
                "assessment_name": r.assessment_name,
                "candidate_name": r.candidate_name,
                "candidate_email": r.candidate_email,
                "score": r.score,
                "status": r.status,
                "provider": r.provider,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            
            # Add provider-specific fields
            if r.provider == "criteria" and hasattr(r, 'criteria_percentile_rank'):
                data.update({
                    "percentile_rank": r.criteria_percentile_rank,
                    "test_status": r.criteria_test_status,
                    "recommendation": r.criteria_recommendation,
                    "cognitive_ability": r.criteria_cognitive_ability,
                    "personality_fit": r.criteria_personality_fit,
                    "skills_match": r.criteria_skills_match,
                    "culture_fit": r.criteria_culture_fit,
                    "sub_scores": r.criteria_sub_scores,
                    "questions_answered": r.criteria_questions_answered,
                    "questions_total": r.criteria_questions_total,
                    "report_url": r.criteria_report_url
                })
            elif r.provider == "testlify" and hasattr(r, 'testlify_test_id'):
                data.update({
                    "test_id": r.testlify_test_id,
                    "invitation_id": r.testlify_invitation_id,
                    "completion_date": r.testlify_completion_date.isoformat() if r.testlify_completion_date else None
                })
            
            results_data.append(data)
        
        return jsonify({
            "success": True,
            "count": len(results_data),
            "results": results_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching results: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        session.close()

def determine_test_status(score):
    """Determine test status based on score"""
    if score is None:
        return "pending"
    elif score >= 70:
        return "passed"
    elif score >= 50:
        return "review"
    else:
        return "failed"

def determine_recommendation(score):
    """Determine recommendation based on score"""
    if score is None:
        return "pending"
    elif score >= 80:
        return "strongly_recommend"
    elif score >= 60:
        return "recommend"
    elif score >= 40:
        return "consider"
    else:
        return "not_recommend"

def run_scraping_with_monitoring(assessment_name: str, source: str):
    """Wrapper to run scraping with monitoring and error handling"""
    start_time = time.time()
    
    logger.info(f"[SCRAPER] Running monitored scraping for '{assessment_name}' using {source}")
    
    try:
        if source == "testlify":
            run_testlify_scraper(assessment_name)
        elif source == "criteria":
            run_criteria_scraper(assessment_name)
        else:
            logger.error(f"❌ Invalid scraper source: {source}")
            notify_admin(
                "Invalid Scraper Source",
                f"Attempted to use unknown scraper source: {source}"
            )
            return
            
        duration = time.time() - start_time
        logger.info(f"✅ Scraping ({source}) completed in {duration:.2f} seconds.")
        
        notify_admin(
            f"{source.capitalize()} Scraping Completed",
            f"Assessment: {assessment_name}\nDuration: {duration:.2f} seconds"
        )
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"❌ Scraping failed ({source}) for '{assessment_name}' after {duration:.2f} seconds"
        logger.error(error_msg, exc_info=True)
        
        notify_admin(
            f"{source.capitalize()} Scraping Failed",
            error_msg,
            error_details=traceback.format_exc()
        )

def run_testlify_scraper(assessment_name: str):
    """Run Testlify scraper for a specific assessment"""
    try:
        # Import the scraper module
        try:
            from testlify_results_scraper import scrape_assessment_results_by_name
        except ImportError as e:
            logger.error(f"[TESTLIFY] Failed to import scraper: {e}")
            raise Exception("Testlify scraper module not found")
        
        logger.info(f"[TESTLIFY] Starting scraper for: {assessment_name}")
        
        # Create new event loop for async operation
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results = loop.run_until_complete(
                scrape_assessment_results_by_name(assessment_name)
            )
        finally:
            loop.close()
        
        logger.info(f"[TESTLIFY] Completed. Results found: {len(results) if results else 0}")
        return results
        
    except Exception as e:
        logger.error(f"[TESTLIFY] Error: {e}", exc_info=True)
        raise

def run_criteria_scraper(assessment_name: str):
    """Run Criteria Corp scraper with detailed data storage"""
    session = SessionLocal()
    try:
        logger.info(f"[CRITERIA] Starting scraper for: {assessment_name}")
        
        # Get the script path (assuming it's in the same directory or project root)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, "Criteria_score.py")
        
        # Check if script exists
        if not os.path.exists(script_path):
            # Try parent directory
            script_path = os.path.join(os.path.dirname(script_dir), "Criteria_score.py")
            
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Criteria_score.py not found. Searched in {script_dir}")
        
        # Run the Criteria scraper script
        process = subprocess.Popen(
            [sys.executable, script_path, assessment_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate()
        
        # Log any errors from the script
        if stderr:
            logger.warning(f"[CRITERIA] Script stderr output:\n{stderr}")
        
        # Check return code
        if process.returncode != 0:
            raise Exception(f"Criteria script failed with return code {process.returncode}")
        
        # Parse JSON output
        try:
            results = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error(f"[CRITERIA] Failed to parse JSON output: {e}")
            logger.error(f"[CRITERIA] Raw output: {stdout}")
            raise Exception("Invalid JSON output from Criteria scraper")
        
        logger.info(f"[CRITERIA] Found {len(results)} results")
        
        # Insert each result into database with Criteria-specific fields
        for result in results:
            # Check if record already exists
            existing = session.query(AssessmentResult).filter_by(
                assessment_name=assessment_name,
                candidate_email=result.get("email"),
                provider="criteria"
            ).first()
            
            if existing:
                # Update existing record with all Criteria-specific data
                existing.candidate_name = result.get("name")
                existing.score = result.get("score")
                existing.status = result.get("status")
                existing.provider = "criteria"
                
                # Update Criteria-specific fields if they exist in the model
                if hasattr(existing, 'criteria_assessment_id'):
                    existing.criteria_assessment_id = result.get("assessment_id")
                    existing.criteria_candidate_id = result.get("candidate_id")
                    existing.criteria_assessment_type = result.get("assessment_type", "Cognitive")
                    existing.criteria_percentile_rank = result.get("percentile")
                    existing.criteria_raw_score = result.get("raw_score")
                    existing.criteria_scaled_score = result.get("scaled_score")
                    existing.criteria_stanine_score = result.get("stanine")
                    existing.criteria_sub_scores = result.get("sub_scores", {})
                    existing.criteria_test_date = datetime.fromisoformat(result["test_date"]) if result.get("test_date") else None
                    existing.criteria_completion_time = result.get("completion_time")
                    existing.criteria_questions_answered = result.get("questions_answered")
                    existing.criteria_questions_total = result.get("questions_total")
                    existing.criteria_test_status = determine_test_status(result.get("score"))
                    existing.criteria_recommendation = determine_recommendation(result.get("score"))
                    existing.criteria_cognitive_ability = result.get("cognitive_ability")
                    existing.criteria_personality_fit = result.get("personality_fit")
                    existing.criteria_skills_match = result.get("skills_match")
                    existing.criteria_culture_fit = result.get("culture_fit")
                    existing.criteria_report_url = result.get("report_url")
                    existing.criteria_detailed_report_url = result.get("detailed_report_url")
                
                # Update metadata
                if hasattr(existing, 'raw_data'):
                    existing.raw_data = result
                if hasattr(existing, 'synced_at'):
                    existing.synced_at = datetime.utcnow()
                existing.updated_at = datetime.utcnow()
                
            else:
                # Create new record - first check what columns exist in the model
                record_data = {
                    "assessment_name": assessment_name,
                    "candidate_name": result.get("name"),
                    "candidate_email": result.get("email"),
                    "score": result.get("score"),
                    "status": result.get("status"),
                    "provider": "criteria"
                }
                
                # Create the base record
                record = AssessmentResult(**record_data)
                
                # Add Criteria-specific fields if they exist in the model
                if hasattr(AssessmentResult, 'criteria_assessment_id'):
                    record.criteria_assessment_id = result.get("assessment_id")
                    record.criteria_candidate_id = result.get("candidate_id")
                    record.criteria_assessment_type = result.get("assessment_type", "Cognitive")
                    record.criteria_percentile_rank = result.get("percentile")
                    record.criteria_raw_score = result.get("raw_score")
                    record.criteria_scaled_score = result.get("scaled_score")
                    record.criteria_stanine_score = result.get("stanine")
                    record.criteria_sub_scores = result.get("sub_scores", {})
                    record.criteria_test_date = datetime.fromisoformat(result["test_date"]) if result.get("test_date") else None
                    record.criteria_completion_time = result.get("completion_time")
                    record.criteria_questions_answered = result.get("questions_answered")
                    record.criteria_questions_total = result.get("questions_total")
                    record.criteria_test_status = determine_test_status(result.get("score"))
                    record.criteria_recommendation = determine_recommendation(result.get("score"))
                    record.criteria_cognitive_ability = result.get("cognitive_ability")
                    record.criteria_personality_fit = result.get("personality_fit")
                    record.criteria_skills_match = result.get("skills_match")
                    record.criteria_culture_fit = result.get("culture_fit")
                    record.criteria_report_url = result.get("report_url")
                    record.criteria_detailed_report_url = result.get("detailed_report_url")
                
                # Add metadata if fields exist
                if hasattr(record, 'raw_data'):
                    record.raw_data = result
                if hasattr(record, 'synced_at'):
                    record.synced_at = datetime.utcnow()
                
                session.add(record)
        
        session.commit()
        logger.info(f"[CRITERIA] Results saved to database")
        return results
        
    except Exception as e:
        session.rollback()
        logger.error(f"[CRITERIA] Failed: {e}", exc_info=True)
        raise
    finally:
        session.close()

def run_bulk_scraping_with_monitoring():
    """Wrapper to run bulk scraping with monitoring"""
    start_time = time.time()
    
    try:
        logger.info("Starting bulk scraping for all pending assessments")
        
        # Import the bulk scraping function
        try:
            from testlify_results_scraper import scrape_all_pending_assessments
        except ImportError as e:
            logger.error(f"Failed to import scraper: {e}")
            notify_admin(
                "Scraper Import Error",
                f"Could not import results scraper: {str(e)}. Please ensure testlify_results_scraper.py is available."
            )
            return
        
        # Create new event loop for async operation
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            results_summary = loop.run_until_complete(scrape_all_pending_assessments())
        finally:
            loop.close()
        
        duration = time.time() - start_time
        total_candidates = sum(results_summary.values()) if isinstance(results_summary, dict) else 0
        
        logger.info(
            f"Bulk scraping completed in {duration:.2f} seconds. "
            f"Processed {len(results_summary) if results_summary else 0} assessments, "
            f"{total_candidates} candidates."
        )
        
        # Prepare summary text
        if isinstance(results_summary, dict) and results_summary:
            summary_text = "\n".join([
                f"- {assessment}: {count} candidates" 
                for assessment, count in results_summary.items()
            ])
        else:
            summary_text = f"Processed {total_candidates} total candidates"
        
        # Send success notification
        notify_admin(
            "Bulk Assessment Results Scraping Completed",
            f"Assessments processed: {len(results_summary) if results_summary else 0}\n"
            f"Total candidates: {total_candidates}\n"
            f"Duration: {duration:.2f} seconds\n\n"
            f"Breakdown:\n{summary_text}"
        )
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Bulk scraping failed after {duration:.2f} seconds"
        logger.error(error_msg, exc_info=True)
        
        # Send failure notification
        notify_admin(
            "Bulk Assessment Results Scraping Failed",
            error_msg,
            error_details=traceback.format_exc()
        )

# Additional API endpoints for Criteria-specific queries
@scraping_bp.route('/api/criteria/statistics', methods=['GET', 'OPTIONS'])
def get_criteria_statistics():
    """Get statistics for Criteria assessments"""
    if request.method == 'OPTIONS':
        return '', 200
        
    session = SessionLocal()
    try:
        from sqlalchemy import func
        
        assessment_name = request.args.get('assessment_name')
        
        # Build base query
        query = session.query(AssessmentResult).filter(AssessmentResult.provider == "criteria")
        
        if assessment_name:
            query = query.filter(AssessmentResult.assessment_name == assessment_name)
        
        results = query.all()
        
        if not results:
            return jsonify({
                "success": True,
                "statistics": {
                    "total_candidates": 0,
                    "average_score": 0,
                    "min_score": 0,
                    "max_score": 0
                }
            }), 200
        
        # Calculate statistics
        scores = [r.score for r in results if r.score is not None]
        
        statistics = {
            "total_candidates": len(results),
            "average_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "pass_rate": round(len([s for s in scores if s >= 70]) / len(scores) * 100, 2) if scores else 0
        }
        
        # Add Criteria-specific statistics if columns exist
        if hasattr(results[0], 'criteria_percentile_rank'):
            percentiles = [r.criteria_percentile_rank for r in results if r.criteria_percentile_rank is not None]
            if percentiles:
                statistics["average_percentile"] = round(sum(percentiles) / len(percentiles), 2)
            
            # Test status distribution
            if hasattr(results[0], 'criteria_test_status'):
                status_counts = {}
                for r in results:
                    if r.criteria_test_status:
                        status_counts[r.criteria_test_status] = status_counts.get(r.criteria_test_status, 0) + 1
                statistics["status_distribution"] = status_counts
            
            # Recommendation distribution
            if hasattr(results[0], 'criteria_recommendation'):
                rec_counts = {}
                for r in results:
                    if r.criteria_recommendation:
                        rec_counts[r.criteria_recommendation] = rec_counts.get(r.criteria_recommendation, 0) + 1
                statistics["recommendation_distribution"] = rec_counts
        
        return jsonify({
            "success": True,
            "statistics": statistics
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching Criteria statistics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        session.close()