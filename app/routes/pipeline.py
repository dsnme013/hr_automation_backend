
from datetime import datetime
import threading
from flask import Blueprint, logging, request, jsonify
import time, asyncio
import logging
from app.extensions import cache, logger, executor
from app.routes.shared import update_pipeline_status, get_pipeline_status, rate_limit
from app.services.clint_recruitment_system import run_recruitment_with_invite_link
from app.services.scraper import scrape_job
from app.services.testlify_scraper import create_programming_assessment
from concurrent.futures import ThreadPoolExecutor
from app.routes.candidates import get_cached_candidates
from app.routes.jobs import get_cached_jobs
from app.services.criteria_automation import runpipeline as create_criteria_assessment_pipeline


pipeline_bp = Blueprint("pipeline", __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
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

@pipeline_bp.route('/api/pipeline_status/<job_id>', methods=['GET','OPTIONS'])
def api_pipeline_status(job_id=None):
    """Get pipeline status for specific job or all jobs"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        if job_id:
            status = get_pipeline_status(job_id)
            if not status:
                return jsonify({"success": False, "message": "Pipeline not found"}), 404
            
            # Clean up the status (remove future object for JSON serialization)
            clean_status = {k: v for k, v in status.items() if k != 'future'}
            return jsonify({"success": True, "status": clean_status}), 200
        else:
            all_status = get_pipeline_status()
            # Clean up all statuses
            clean_statuses = {k: {sk: sv for sk, sv in v.items() if sk != 'future'} 
                            for k, v in all_status.items()}
            return jsonify({"success": True, "pipelines": clean_statuses}), 200
            
    except Exception as e:
        logger.error(f"Error in pipeline_status: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500

@pipeline_bp.route('/api/run_full_pipeline', methods=['POST','OPTIONS'])
@rate_limit(max_calls=5, time_window=300)
def api_run_full_pipeline():
    """Enhanced pipeline API with assessment provider selection"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        job_id = data.get('job_id')
        job_title = data.get('job_title')
        job_desc = data.get('job_desc', "")
        create_assessment = data.get('create_assessment', False)
        assessment_provider = data.get('assessment_provider', 'testlify')  # NEW: Get provider (default to testlify)
        
        logger.info(f"Pipeline request: job_id={job_id}, create_assessment={create_assessment}, provider={assessment_provider}")
        
        # Validate provider
        if assessment_provider not in ['testlify', 'criteria']:
            return jsonify({
                "success": False, 
                "message": "Invalid assessment_provider. Must be 'testlify' or 'criteria'"
            }), 400
        
        if not job_id or not job_title:
            return jsonify({"success": False, "message": "job_id and job_title are required"}), 400
        
        # Check if pipeline is already running
        current_status = get_pipeline_status(job_id)
        if current_status and current_status.get('status') == 'running':
            return jsonify({
                "success": False,
                "message": f"Pipeline already running for {job_title}",
                "status": current_status
            }), 409
        
        # Update status
        update_pipeline_status(job_id, 'starting', f'Initializing pipeline for {job_title}', 0)
        
        # Start pipeline with assessment flag and provider
        future = executor.submit(
            run_pipeline_with_monitoring, 
            job_id, 
            job_title, 
            job_desc, 
            create_assessment,
            assessment_provider  # NEW: Pass provider to pipeline
        )
        
        with pipeline_lock:
            pipeline_status[str(job_id)]['future'] = future
        
        return jsonify({
            "success": True, 
            "message": f"Pipeline started for {job_title}",
            "job_id": job_id,
            "create_assessment": create_assessment,
            "assessment_provider": assessment_provider,  # Include provider in response
            "estimated_time": "5-10 minutes"
        }), 200
        
    except Exception as e:
        logger.error(f"Error in run_full_pipeline: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500

def run_pipeline_with_monitoring(job_id, job_title, job_desc, create_assessment=False, assessment_provider='testlify'):
    """Enhanced pipeline runner with assessment provider support"""
    start_time = time.time()
    
    try:
        logger.info(f"Starting pipeline for job_id={job_id}, create_assessment={create_assessment}, provider={assessment_provider}")
        update_pipeline_status(job_id, 'running', 'Pipeline started', 10)
        
        # Clear caches
        cache.delete_memoized(get_cached_candidates)
        cache.delete_memoized(get_cached_jobs)
        
        # Run modified pipeline with provider
        full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment, assessment_provider)
        
        duration = time.time() - start_time
        update_pipeline_status(job_id, 'completed', f'Pipeline completed in {duration:.1f}s', 100)
        logger.info(f"Pipeline completed in {duration:.2f} seconds")
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Pipeline failed after {duration:.2f} seconds: {str(e)}"
        update_pipeline_status(job_id, 'error', error_msg, None)
        logger.error(error_msg, exc_info=True)

def create_testlify_assessment(job_title, job_desc):
    """Create assessment in Testlify (your existing function)"""
    # Your existing Testlify assessment creation logic
    logger.info(f"Creating Testlify assessment for: {job_title}")
    
    # This should be your existing create_programming_assessment function
    # Replace this with your actual Testlify implementation
    try:
        # Your existing Testlify logic here
        create_programming_assessment(job_title, job_desc)  # Your existing function
        return f"https://candidate.testlify.com/assessment/{job_title.replace(' ', '-').lower()}"
    except Exception as e:
        logger.error(f"Testlify assessment creation failed: {e}")
        raise

# def create_criteria_assessment(job_title, job_desc):
#     """Create assessment in Criteria Corp"""
#     logger.info(f"Creating Criteria assessment for: {job_title}")
    
#     assessment_link = None  # ALWAYS declare it early

#     try:
#         # Determine occupation
#         occupation = extract_occupation_from_job(job_title, job_desc)

#         # Run automation
#         assessment_link = create_criteria_assessment_pipeline(
#             job_title=job_title,
#             occupation=occupation,
#             headless=True
#         )

#         # If link extracted normally
#         if assessment_link:
#             logger.info(f"Criteria assessment created successfully: {assessment_link}")
#             return assessment_link

#         # Link missing (rare case)
#         logger.warning("Criteria assessment created but no link extracted")
#         return f"https://hireselect.criteriacorp.com/jobs/{job_title.replace(' ', '-').lower()}"

#     except Exception as e:
#         # SPECIAL FIX: Playwright closed AFTER success
#         if "Event loop is closed" in str(e) or "playwright already stopped" in str(e).lower():
#             if assessment_link:
#                 logger.warning(
#                     "Playwright closed after generating the link. "
#                     "Returning extracted assessment link anyway."
#                 )
#                 return assessment_link  # RETURN THE VALID LINK

#         # REAL FAILURE → Raise error
#         logger.error(f"Criteria assessment creation failed: {e}", exc_info=True)
#         raise
def create_criteria_assessment(job_title, job_desc):
    """Create assessment in Criteria Corp (fixed version)"""
    logger.info(f"Creating Criteria assessment for: {job_title}")
    
    assessment_link = None  # ALWAYS declare early

    try:
        # Determine occupation
        occupation = extract_occupation_from_job(job_title, job_desc)
        logger.info(f"Detected occupation: {occupation}")

        # 🚨 IMPORTANT FIX: RUN IN NON-HEADLESS MODE
        assessment_link = create_criteria_assessment_pipeline(
            job_title=job_title,
            occupation=occupation,
            headless=False,   # MUST be false or modal won't load
            slowmo=50         # Helps Playwright detect modal and content
        )

        # If link extracted normally
        if assessment_link:
            logger.info(f"✅ Criteria assessment link extracted: {assessment_link}")
            return assessment_link

        # ❗ No link found → return fallback URL
        logger.warning("⚠️ Criteria automation completed but no link extracted.")
        return f"https://hireselect.criteriacorp.com/jobs/{job_title.replace(' ', '-').lower()}"

    except Exception as e:
        # SPECIAL FIX: Playwright closed AFTER success
        if "Event loop is closed" in str(e) or "playwright already stopped" in str(e).lower():
            if assessment_link:
                logger.warning(
                    "⚠️ Playwright closed after generating the link. "
                    "Returning extracted assessment link anyway."
                )
                return assessment_link

        # REAL FAILURE → Raise error
        logger.error(f"❌ Criteria assessment creation failed: {e}", exc_info=True)
        raise



def extract_occupation_from_job(job_title, job_desc):
    """Extract relevant occupation search term for Criteria from job title/description"""
    # Simple extraction logic - you can make this more sophisticated
    job_lower = job_title.lower()
    
    # Map common job titles to Criteria occupation search terms
    occupation_mappings = {
        'python': 'python developer',
        'java': 'java developer',
        'frontend': 'frontend developer',
        'backend': 'backend developer',
        'fullstack': 'full stack developer',
        'full stack': 'full stack developer',
        'devops': 'devops engineer',
        'data scientist': 'data scientist',
        'data analyst': 'data analyst',
        'machine learning': 'machine learning engineer',
        'ai engineer': 'ai engineer',
        'software': 'software developer',
        'web': 'web developer',
        'mobile': 'mobile developer',
        'ios': 'ios developer',
        'android': 'android developer',
        'qa': 'qa engineer',
        'test': 'test engineer',
        'product manager': 'product manager',
        'project manager': 'project manager',
        'designer': 'designer',
        'ux': 'ux designer',
        'ui': 'ui designer'
    }
    
    # Check for matching occupation
    for key, value in occupation_mappings.items():
        if key in job_lower:
            return value
    
    # Default fallback
    return 'software developer'

def full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment=False, assessment_provider='testlify'):
    """Modified pipeline with assessment provider support"""
    try:
        logger.info(f"Starting recruitment pipeline for job_id={job_id}, provider={assessment_provider}")
        
        # STEP 1: Scraping (25% progress)
        try:
            update_pipeline_status(job_id, 'running', 'Scraping resumes...', 25)
            logger.info(f"STEP 1: Scraping resumes for job_id={job_id}")
            asyncio.run(scrape_job(job_id))
            logger.info("Scraping completed successfully")
        except Exception as e:
            logger.error(f"Scraping failed: {str(e)}", exc_info=True)
        
        invite_link = None
        
        # STEP 2 & 3: Only if assessment creation is requested
        if create_assessment:
            provider_name = "Testlify" if assessment_provider == 'testlify' else "Criteria"
            
            # Create assessment based on provider (50% progress)
            try:
                update_pipeline_status(
                    job_id, 
                    'running', 
                    f'Creating assessment in {provider_name}...', 
                    50
                )
                logger.info(f"STEP 2: Creating {provider_name} assessment for '{job_title}'")
                
                # Call appropriate assessment creation function based on provider
                if assessment_provider == 'testlify':
                    invite_link = create_testlify_assessment(job_title, job_desc)
                else:  # criteria
                    invite_link = create_criteria_assessment(job_title, job_desc)
                
                logger.info(f"{provider_name} assessment created successfully")
                
                # Update status to show assessment created (70% progress)
                update_pipeline_status(
                    job_id, 
                    'running', 
                    f'{provider_name} assessment created', 
                    70
                )
                
            except Exception as e:
                logger.error(f"{provider_name} assessment creation failed: {str(e)}", exc_info=True)
                # Continue with pipeline even if assessment fails
                invite_link = None
        
        # STEP 4: Run AI screening (100% progress)
        try:
            update_pipeline_status(job_id, 'running', 'Running AI-powered screening...', 90)
            logger.info("Running AI-powered screening...")
            
            # Your existing screening logic
            run_recruitment_with_invite_link(
                job_id=job_id,
                job_title=job_title,
                job_desc=job_desc,
                invite_link=invite_link  # Will be None if no assessment was created
            )
            
            logger.info("AI screening completed successfully")
        except Exception as e:
            logger.error(f"AI screening failed: {str(e)}", exc_info=True)
            raise
        
        # Clear caches
        cache.delete_memoized(get_cached_candidates)
        cache.delete_memoized(get_cached_jobs)
        
        # Final status update
        assessment_info = ""
        if create_assessment:
            provider_name = "Testlify" if assessment_provider == 'testlify' else "Criteria"
            assessment_info = f" with {provider_name} assessment"
        
        update_pipeline_status(
            job_id, 
            'completed', 
            f'Pipeline completed successfully{assessment_info}', 
            100
        )
        
        logger.info(f"Recruitment pipeline finished successfully{assessment_info}")
            
    except Exception as e:
        logger.error(f"Fatal pipeline error: {e}", exc_info=True)
        raise
