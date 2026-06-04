# from datetime import datetime
# import threading
# from flask import Blueprint, logging, request, jsonify
# import time, asyncio
# import logging
# from app.extensions import cache, logger, executor
# from app.routes.shared import update_pipeline_status, get_pipeline_status, rate_limit
# from app.services.clint_recruitment_system import run_recruitment_with_invite_link
# from app.services.resumescraper import scrape
# from app.services.assessment_scraper import create_assessment, generate_topics  # ← replaces testlify & criteria
# from concurrent.futures import ThreadPoolExecutor
# from app.routes.candidates import get_cached_candidates
# from app.routes.jobs import get_cached_jobs


# pipeline_bp = Blueprint("pipeline", __name__)

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
# pipeline_status = {}
# pipeline_lock = threading.Lock()


# def update_pipeline_status(job_id, status, message, progress=None):
#     """Thread-safe pipeline status updates"""
#     with pipeline_lock:
#         pipeline_status[str(job_id)] = {
#             'status': status,
#             'message': message,
#             'progress': progress,
#             'timestamp': datetime.now().isoformat(),
#             'job_id': str(job_id)
#         }
#     logger.info(f"Pipeline {job_id}: {status} - {message}")


# def get_pipeline_status(job_id=None):
#     """Get pipeline status (thread-safe)"""
#     with pipeline_lock:
#         if job_id:
#             return pipeline_status.get(str(job_id))
#         return pipeline_status.copy()


# @pipeline_bp.route('/api/pipeline_status/<job_id>', methods=['GET', 'OPTIONS'])
# def api_pipeline_status(job_id=None):
#     """Get pipeline status for specific job or all jobs"""
#     if request.method == 'OPTIONS':
#         return '', 200

#     try:
#         if job_id:
#             status = get_pipeline_status(job_id)
#             if not status:
#                 return jsonify({"success": False, "message": "Pipeline not found"}), 404

#             clean_status = {k: v for k, v in status.items() if k != 'future'}
#             return jsonify({"success": True, "status": clean_status}), 200
#         else:
#             all_status = get_pipeline_status()
#             clean_statuses = {k: {sk: sv for sk, sv in v.items() if sk != 'future'}
#                               for k, v in all_status.items()}
#             return jsonify({"success": True, "pipelines": clean_statuses}), 200

#     except Exception as e:
#         logger.error(f"Error in pipeline_status: {e}", exc_info=True)
#         return jsonify({"success": False, "message": str(e)}), 500


# @pipeline_bp.route('/api/run_full_pipeline', methods=['POST', 'OPTIONS'])
# @rate_limit(max_calls=5, time_window=300)
# def api_run_full_pipeline():
#     """Pipeline API with assessment creation via assessment_scraper"""
#     if request.method == 'OPTIONS':
#         return '', 200

#     try:
#         data = request.json
#         job_id                 = data.get('job_id')
#         job_title              = data.get('job_title')
#         job_desc               = data.get('job_desc', "")
#         create_assessment_flag = data.get('create_assessment', True)

#         logger.info(f"Pipeline request: job_id={job_id}, create_assessment={create_assessment_flag}")

#         if not job_id or not job_title:
#             return jsonify({"success": False, "message": "job_id and job_title are required"}), 400

#         current_status = get_pipeline_status(job_id)
#         if current_status and current_status.get('status') in ('running','starting'):
#             return jsonify({
#                 "success": False,
#                 "message": f"Pipeline already running for {job_title}",
#                 "status": current_status
#             }), 409

#         update_pipeline_status(job_id, 'starting', f'Initializing pipeline for {job_title}', 0)

#         future = executor.submit(
#             run_pipeline_with_monitoring,
#             job_id,
#             job_title,
#             job_desc,
#             create_assessment_flag,
#         )

#         with pipeline_lock:
#             pipeline_status[str(job_id)]['future'] = future

#         return jsonify({
#             "success": True,
#             "message": f"Pipeline started for {job_title}",
#             "job_id": job_id,
#             "create_assessment": create_assessment_flag,
#             "estimated_time": "5-10 minutes"
#         }), 200

#     except Exception as e:
#         logger.error(f"Error in run_full_pipeline: {e}", exc_info=True)
#         return jsonify({"success": False, "message": str(e)}), 500


# def run_pipeline_with_monitoring(job_id, job_title, job_desc, create_assessment_flag=False):
#     """Pipeline runner"""
#     start_time = time.time()

#     try:
#         logger.info(f"Starting pipeline for job_id={job_id}, create_assessment={create_assessment_flag}")
#         update_pipeline_status(job_id, 'running', 'Pipeline started', 10)

#         cache.delete_memoized(get_cached_candidates)
#         cache.delete_memoized(get_cached_jobs)

#         full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment_flag)

#         duration = time.time() - start_time
#         update_pipeline_status(job_id, 'completed', f'Pipeline completed in {duration:.1f}s', 100)
#         logger.info(f"Pipeline completed in {duration:.2f} seconds")

#     except Exception as e:
#         duration = time.time() - start_time
#         error_msg = f"Pipeline failed after {duration:.2f} seconds: {str(e)}"
#         update_pipeline_status(job_id, 'error', error_msg, None)
#         logger.error(error_msg, exc_info=True)


# def full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment_flag=False):
#     """
#     STEP 1 → Scrape resumes from http://65.1.136.77  (resumescraper)
#     STEP 2 → Create assessment via assessment_scraper (BASE_URL ngrok site)  [optional]
#     STEP 3 → Run AI screening (clint_recruitment_system)
#     """
#     try:
#         logger.info(f"Starting recruitment pipeline for job_id={job_id}")

#         # ── STEP 1: Scrape resumes from HR dashboard (25%) ───────────────────
#         try:
#             update_pipeline_status(job_id, 'running', 'Scraping resumes from HR dashboard...', 25)
#             logger.info(f"STEP 1: Scraping resumes for job_title={job_title}")
#             asyncio.run(scrape(target_role=job_title))
#             logger.info("Scraping completed successfully")
#         except Exception as e:
#             logger.error(f"Scraping failed: {str(e)}", exc_info=True)

#         invite_link = None

#         # ── STEP 2: Create assessment via assessment_scraper (50-70%) ────────
#         if create_assessment_flag:
#             try:
#                 update_pipeline_status(job_id, 'running', 'Creating assessment...', 50)
#                 logger.info(f"STEP 2: Creating assessment for '{job_title}'")

#                 # Auto-generate topics from job title
#                 topics = generate_topics(job_title)
#                 logger.info(f"Generated topics: {topics}")

#                 # Run assessment_scraper automation against BASE_URL (ngrok site)
#                 invite_link = asyncio.run(
#                     create_assessment(
#                         job_role=job_title,
#                         topics=topics,
#                         duration=60,
#                     )
#                 )

#                 if invite_link:
#                     logger.info(f"Assessment created. Link: {invite_link}")
#                     update_pipeline_status(job_id, 'running', 'Assessment created', 70)
#                 else:
#                     logger.warning("Assessment created but no invite link returned")
#                     update_pipeline_status(job_id, 'running', 'Assessment created (no link captured)', 70)

#             except Exception as e:
#                 logger.error(f"Assessment creation failed: {str(e)}", exc_info=True)
#                 invite_link = None  # continue pipeline even if assessment fails

#         # ── STEP 3: AI screening (90%) ────────────────────────────────────────
#         try:
#             update_pipeline_status(job_id, 'running', 'Running AI-powered screening...', 90)
#             logger.info("STEP 3: Running AI-powered screening...")

#             run_recruitment_with_invite_link(
#                 job_id=job_id,
#                 job_title=job_title,
#                 job_desc=job_desc,
#                 invite_link=invite_link
#             )

#             logger.info("AI screening completed successfully")
#         except Exception as e:
#             logger.error(f"AI screening failed: {str(e)}", exc_info=True)
#             raise

#         # Clear caches
#         cache.delete_memoized(get_cached_candidates)
#         cache.delete_memoized(get_cached_jobs)

#         assessment_info = " with assessment" if create_assessment_flag else ""
#         update_pipeline_status(
#             job_id,
#             'completed',
#             f'Pipeline completed successfully{assessment_info}',
#             100
#         )
#         logger.info(f"Recruitment pipeline finished successfully{assessment_info}")

#     except Exception as e:
#         logger.error(f"Fatal pipeline error: {e}", exc_info=True)
#         raise
# from datetime import datetime
# import threading
# from flask import Blueprint, logging, request, jsonify
# import time, asyncio
# import logging
# from app.extensions import cache, logger, executor
# from app.routes.shared import update_pipeline_status, get_pipeline_status, rate_limit
# from app.services.clint_recruitment_system import run_recruitment_with_invite_link
# from app.services.resumescraper import scrape
# from app.services.assessment_scraper import create_assessment, generate_topics  # ← replaces testlify & criteria
# from concurrent.futures import ThreadPoolExecutor
# from app.routes.candidates import get_cached_candidates
# from app.routes.jobs import get_cached_jobs


# pipeline_bp = Blueprint("pipeline", __name__)

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
# pipeline_status = {}
# pipeline_lock = threading.Lock()


# def update_pipeline_status(job_id, status, message, progress=None):
#     """Thread-safe pipeline status updates"""
#     with pipeline_lock:
#         pipeline_status[str(job_id)] = {
#             'status': status,
#             'message': message,
#             'progress': progress,
#             'timestamp': datetime.now().isoformat(),
#             'job_id': str(job_id)
#         }
#     logger.info(f"Pipeline {job_id}: {status} - {message}")


# def get_pipeline_status(job_id=None):
#     """Get pipeline status (thread-safe)"""
#     with pipeline_lock:
#         if job_id:
#             return pipeline_status.get(str(job_id))
#         return pipeline_status.copy()


# @pipeline_bp.route('/api/pipeline_status/<job_id>', methods=['GET', 'OPTIONS'])
# def api_pipeline_status(job_id=None):
#     """Get pipeline status for specific job or all jobs"""
#     if request.method == 'OPTIONS':
#         return '', 200

#     try:
#         if job_id:
#             status = get_pipeline_status(job_id)
#             if not status:
#                 return jsonify({"success": False, "message": "Pipeline not found"}), 404

#             clean_status = {k: v for k, v in status.items() if k != 'future'}
#             return jsonify({"success": True, "status": clean_status}), 200
#         else:
#             all_status = get_pipeline_status()
#             clean_statuses = {k: {sk: sv for sk, sv in v.items() if sk != 'future'}
#                               for k, v in all_status.items()}
#             return jsonify({"success": True, "pipelines": clean_statuses}), 200

#     except Exception as e:
#         logger.error(f"Error in pipeline_status: {e}", exc_info=True)
#         return jsonify({"success": False, "message": str(e)}), 500


# @pipeline_bp.route('/api/run_full_pipeline', methods=['POST', 'OPTIONS'])
# @rate_limit(max_calls=5, time_window=300)
# def api_run_full_pipeline():
#     """Pipeline API with assessment creation via assessment_scraper"""
#     if request.method == 'OPTIONS':
#         return '', 200

#     try:
#         data = request.json
#         job_id                 = data.get('job_id')
#         job_title              = data.get('job_title')
#         job_desc               = data.get('job_desc', "")
#         create_assessment_flag = data.get('create_assessment', True)

#         logger.info(f"Pipeline request: job_id={job_id}, create_assessment={create_assessment_flag}")

#         if not job_id or not job_title:
#             return jsonify({"success": False, "message": "job_id and job_title are required"}), 400

#         current_status = get_pipeline_status(job_id)
#         if current_status and current_status.get('status') in ('running','starting'):
#             return jsonify({
#                 "success": False,
#                 "message": f"Pipeline already running for {job_title}",
#                 "status": current_status
#             }), 409

#         update_pipeline_status(job_id, 'starting', f'Initializing pipeline for {job_title}', 0)

#         future = executor.submit(
#             run_pipeline_with_monitoring,
#             job_id,
#             job_title,
#             job_desc,
#             create_assessment_flag,
#         )

#         with pipeline_lock:
#             pipeline_status[str(job_id)]['future'] = future

#         return jsonify({
#             "success": True,
#             "message": f"Pipeline started for {job_title}",
#             "job_id": job_id,
#             "create_assessment": create_assessment_flag,
#             "estimated_time": "5-10 minutes"
#         }), 200

#     except Exception as e:
#         logger.error(f"Error in run_full_pipeline: {e}", exc_info=True)
#         return jsonify({"success": False, "message": str(e)}), 500


# def run_pipeline_with_monitoring(job_id, job_title, job_desc, create_assessment_flag=False):
#     """Pipeline runner"""
#     start_time = time.time()

#     try:
#         logger.info(f"Starting pipeline for job_id={job_id}, create_assessment={create_assessment_flag}")
#         update_pipeline_status(job_id, 'running', 'Pipeline started', 10)

#         cache.delete_memoized(get_cached_candidates)
#         cache.delete_memoized(get_cached_jobs)

#         full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment_flag)

#         duration = time.time() - start_time
#         update_pipeline_status(job_id, 'completed', f'Pipeline completed in {duration:.1f}s', 100)
#         logger.info(f"Pipeline completed in {duration:.2f} seconds")

#     except Exception as e:
#         duration = time.time() - start_time
#         error_msg = f"Pipeline failed after {duration:.2f} seconds: {str(e)}"
#         update_pipeline_status(job_id, 'error', error_msg, None)
#         logger.error(error_msg, exc_info=True)


# def full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment_flag=False):
#     """
#     STEP 1 → Scrape resumes from http://65.1.136.77  (resumescraper)
#     STEP 2 → Create assessment via assessment_scraper (BASE_URL ngrok site)  [optional]
#     STEP 3 → Run AI screening (clint_recruitment_system)
#     """
#     try:
#         logger.info(f"Starting recruitment pipeline for job_id={job_id}")

#         # ── STEP 1: Scrape resumes from HR dashboard (25%) ───────────────────
#         try:
#             update_pipeline_status(job_id, 'running', 'Scraping resumes from HR dashboard...', 25)
#             logger.info(f"STEP 1: Scraping resumes for job_title={job_title}")
#             asyncio.run(scrape(target_role=job_title))
#             logger.info("Scraping completed successfully")
#         except Exception as e:
#             logger.error(f"Scraping failed: {str(e)}", exc_info=True)

#         invite_link = None

#         # ── STEP 2: Create assessment via assessment_scraper (50-70%) ────────
#         if create_assessment_flag:
#             try:
#                 update_pipeline_status(job_id, 'running', 'Creating assessment...', 50)
#                 logger.info(f"STEP 2: Creating assessment for '{job_title}'")

#                 # Auto-generate topics from job title
#                 topics = generate_topics(job_title)
#                 logger.info(f"Generated topics: {topics}")

#                 # Run assessment_scraper automation against BASE_URL (ngrok site)
#                 invite_link = asyncio.run(
#                     create_assessment(
#                         job_role=job_title,
#                         topics=topics,
#                         duration=60,
#                     )
#                 )

#                 if invite_link:
#                     logger.info(f"Assessment created. Link: {invite_link}")
#                     update_pipeline_status(job_id, 'running', 'Assessment created', 70)
#                 else:
#                     logger.warning("Assessment created but no invite link returned")
#                     update_pipeline_status(job_id, 'running', 'Assessment created (no link captured)', 70)

#             except Exception as e:
#                 logger.error(f"Assessment creation failed: {str(e)}", exc_info=True)
#                 invite_link = None  # continue pipeline even if assessment fails

#         # ── STEP 3: AI screening (90%) ────────────────────────────────────────
#         try:
#             update_pipeline_status(job_id, 'running', 'Running AI-powered screening...', 90)
#             logger.info("STEP 3: Running AI-powered screening...")

#             run_recruitment_with_invite_link(
#                 job_id=job_id,
#                 job_title=job_title,
#                 job_desc=job_desc,
#                 invite_link=invite_link
#             )

#             logger.info("AI screening completed successfully")
#         except Exception as e:
#             logger.error(f"AI screening failed: {str(e)}", exc_info=True)
#             raise

#         # Clear caches
#         cache.delete_memoized(get_cached_candidates)
#         cache.delete_memoized(get_cached_jobs)

#         assessment_info = " with assessment" if create_assessment_flag else ""
#         update_pipeline_status(
#             job_id,
#             'completed',
#             f'Pipeline completed successfully{assessment_info}',
#             100
#         )
#         logger.info(f"Recruitment pipeline finished successfully{assessment_info}")

#     except Exception as e:
#         logger.error(f"Fatal pipeline error: {e}", exc_info=True)
#         raise
from datetime import datetime
import threading
import asyncio
from flask import Blueprint, request, jsonify
import time
import logging
from app.extensions import cache, logger, executor
from app.routes.shared import update_pipeline_status, get_pipeline_status, rate_limit
from app.services.clint_recruitment_system import run_recruitment_with_invite_link
from app.services.resumescraper import scrape
from app.services.assessment_scraper import create_assessment, generate_topics
from concurrent.futures import ThreadPoolExecutor
from app.routes.candidates import get_cached_candidates
from app.routes.jobs import get_cached_jobs


pipeline_bp = Blueprint("pipeline", __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
pipeline_status = {}
pipeline_lock = threading.Lock()


# ── Safe async runner ─────────────────────────────────────────────────────────
def _run_async(coro, timeout_seconds: int = 300):
    """
    Run an async coroutine safely from a synchronous Flask/thread context.

    WHY this exists
    ───────────────
    asyncio.run() is NOT safe to call more than once per thread:
      • It creates a new event loop, runs the coroutine, then CLOSES the loop.
      • Closing the loop triggers Python atexit / threading cleanup handlers.
      • A second asyncio.run() in the same thread finds a partially-torn-down
        runtime, so:
          - Playwright's browser page gets force-killed mid-wait
            ("Target page, context or browser has been closed")
          - Any ThreadPoolExecutor in subsequent steps raises
            "cannot schedule new futures after interpreter shutdown"

    This wrapper runs each coroutine in its own isolated daemon thread with
    its own fresh event loop, completely decoupled from the Flask worker
    thread's lifecycle.  Steps 1, 2, and 3 can never poison each other.

    Parameters
    ──────────
    coro            : coroutine to run  (e.g. scrape(target_role=job_title))
    timeout_seconds : hard wall-clock limit; raises TimeoutError if exceeded
    """
    result_box: list = [None]
    error_box:  list = [None]

    def _target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_box[0] = loop.run_until_complete(coro)
        except Exception as exc:
            error_box[0] = exc
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    t = threading.Thread(target=_target, daemon=True, name="async-worker")
    t.start()
    t.join(timeout=timeout_seconds)

    if t.is_alive():
        raise TimeoutError(
            f"Async operation did not finish within {timeout_seconds}s"
        )
    if error_box[0] is not None:
        raise error_box[0]
    return result_box[0]


# ── Pipeline status helpers ───────────────────────────────────────────────────
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
        return pipeline_status.copy()


# ── Routes ────────────────────────────────────────────────────────────────────
@pipeline_bp.route('/api/pipeline_status/<job_id>', methods=['GET', 'OPTIONS'])
def api_pipeline_status(job_id=None):
    """Get pipeline status for specific job or all jobs"""
    if request.method == 'OPTIONS':
        return '', 200

    try:
        if job_id:
            status = get_pipeline_status(job_id)
            if not status:
                return jsonify({"success": False, "message": "Pipeline not found"}), 404

            clean_status = {k: v for k, v in status.items() if k != 'future'}
            return jsonify({"success": True, "status": clean_status}), 200
        else:
            all_status = get_pipeline_status()
            clean_statuses = {k: {sk: sv for sk, sv in v.items() if sk != 'future'}
                              for k, v in all_status.items()}
            return jsonify({"success": True, "pipelines": clean_statuses}), 200

    except Exception as e:
        logger.error(f"Error in pipeline_status: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@pipeline_bp.route('/api/run_full_pipeline', methods=['POST', 'OPTIONS'])
@rate_limit(max_calls=5, time_window=300)
def api_run_full_pipeline():
    """Pipeline API with assessment creation via assessment_scraper"""
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.json
        job_id                 = data.get('job_id')
        job_title              = data.get('job_title')
        job_desc               = data.get('job_desc', "")
        create_assessment_flag = data.get('create_assessment', True)

        logger.info(f"Pipeline request: job_id={job_id}, create_assessment={create_assessment_flag}")

        if not job_id or not job_title:
            return jsonify({"success": False, "message": "job_id and job_title are required"}), 400

        current_status = get_pipeline_status(job_id)
        if current_status and current_status.get('status') in ('running', 'starting'):
            return jsonify({
                "success": False,
                "message": f"Pipeline already running for {job_title}",
                "status": current_status
            }), 409

        update_pipeline_status(job_id, 'starting', f'Initializing pipeline for {job_title}', 0)

        future = executor.submit(
            run_pipeline_with_monitoring,
            job_id,
            job_title,
            job_desc,
            create_assessment_flag,
        )

        with pipeline_lock:
            pipeline_status[str(job_id)]['future'] = future

        return jsonify({
            "success": True,
            "message": f"Pipeline started for {job_title}",
            "job_id": job_id,
            "create_assessment": create_assessment_flag,
            "estimated_time": "5-10 minutes"
        }), 200

    except Exception as e:
        logger.error(f"Error in run_full_pipeline: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


# ── Pipeline runners ──────────────────────────────────────────────────────────
def run_pipeline_with_monitoring(job_id, job_title, job_desc, create_assessment_flag=False):
    """Pipeline runner"""
    start_time = time.time()

    try:
        logger.info(f"Starting pipeline for job_id={job_id}, create_assessment={create_assessment_flag}")
        update_pipeline_status(job_id, 'running', 'Pipeline started', 10)

        cache.delete_memoized(get_cached_candidates)
        cache.delete_memoized(get_cached_jobs)

        full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment_flag)

        duration = time.time() - start_time
        update_pipeline_status(job_id, 'completed', f'Pipeline completed in {duration:.1f}s', 100)
        logger.info(f"Pipeline completed in {duration:.2f} seconds")

    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Pipeline failed after {duration:.2f} seconds: {str(e)}"
        update_pipeline_status(job_id, 'error', error_msg, None)
        logger.error(error_msg, exc_info=True)


def full_recruitment_pipeline(job_id, job_title, job_desc, create_assessment_flag=False):
    """
    STEP 1 → Scrape resumes from http://65.1.136.77  (resumescraper)
    STEP 2 → Create assessment via assessment_scraper (BASE_URL ngrok site)  [optional]
    STEP 3 → Run AI screening (clint_recruitment_system)
    """
    try:
        logger.info(f"Starting recruitment pipeline for job_id={job_id}")

        # ── STEP 1: Scrape resumes from HR dashboard (25%) ───────────────────
        try:
            update_pipeline_status(job_id, 'running', 'Scraping resumes from HR dashboard...', 25)
            logger.info(f"STEP 1: Scraping resumes for job_title={job_title}")
            # Use _run_async — NOT asyncio.run() — so the event loop lives in
            # an isolated daemon thread.  A timeout or crash here cannot
            # poison the loop used by the assessment step below.
            _run_async(scrape(target_role=job_title), timeout_seconds=120)
            logger.info("Scraping completed successfully")
        except TimeoutError:
            logger.warning("STEP 1: Scraping timed out after 120s — continuing with cached resumes")
        except Exception as e:
            logger.error(f"Scraping failed: {str(e)}", exc_info=True)
            # Non-fatal: pipeline continues with whatever resumes are already on disk

        invite_link = None

        # ── STEP 2: Create assessment via assessment_scraper (50-70%) ────────
        if create_assessment_flag:
            try:
                update_pipeline_status(job_id, 'running', 'Creating assessment...', 50)
                logger.info(f"STEP 2: Creating assessment for '{job_title}'")

                topics = generate_topics(job_title)
                logger.info(f"Generated topics: {topics}")

                # Each _run_async call gets its own fresh event loop so
                # Playwright browser contexts are never shared or killed
                # by teardown from a previous step.
                invite_link = _run_async(
                    create_assessment(
                        job_role=job_title,
                        topics=topics,
                        duration=60,
                    ),
                    timeout_seconds=300,   # assessment creation can take up to 5 min
                )

                if invite_link:
                    logger.info(f"Assessment created. Link: {invite_link}")
                    update_pipeline_status(job_id, 'running', 'Assessment created', 70)
                else:
                    logger.warning("Assessment created but no invite link returned")
                    update_pipeline_status(job_id, 'running', 'Assessment created (no link captured)', 70)

            except TimeoutError:
                logger.warning("STEP 2: Assessment creation timed out after 300s — continuing without link")
                invite_link = None
            except Exception as e:
                logger.error(f"Assessment creation failed: {str(e)}", exc_info=True)
                invite_link = None  # continue pipeline even if assessment fails

        # ── STEP 3: AI screening (90%) ────────────────────────────────────────
        # By the time we reach here, no asyncio.run() / event-loop teardown
        # has touched the interpreter — ThreadPoolExecutor.submit() is safe.
        # try:
        #     update_pipeline_status(job_id, 'running', 'Running AI-powered screening...', 90)
        #     logger.info("STEP 3: Running AI-powered screening...")

        #     run_recruitment_with_invite_link(
        #         job_id=job_id,
        #         job_title=job_title,
        #         job_desc=job_desc,
        #         invite_link=invite_link
        #     )

        #     logger.info("AI screening completed successfully")
        # except Exception as e:
        #     logger.error(f"AI screening failed: {str(e)}", exc_info=True)
        #     raise

        # # Clear caches
        # cache.delete_memoized(get_cached_candidates)
        # cache.delete_memoized(get_cached_jobs)

        # assessment_info = " with assessment" if create_assessment_flag else ""
        # update_pipeline_status(
        #     job_id,
        #     'completed',
        #     f'Pipeline completed successfully{assessment_info}',
        #     100
        # )
        # logger.info(f"Recruitment pipeline finished successfully{assessment_info}")
        # ── STEP 3: AI screening (90%) ────────────────────────────────────────
        try:
            update_pipeline_status(job_id, 'running', 'Running AI-powered screening...', 90)
            logger.info("STEP 3: Running AI-powered screening...")

            run_recruitment_with_invite_link(
                job_id=job_id,
                job_title=job_title,
                job_desc=job_desc,
                invite_link=invite_link
            )
            logger.info("AI screening completed successfully")

        except Exception as e:
            logger.error(f"AI screening failed: {str(e)}", exc_info=True)
            raise
                # ── STEP 3b: Auto-approve and send emails ────────────────────────────
        try:
            update_pipeline_status(job_id, 'running', 'Sending candidate notifications...', 93)
            logger.info("STEP 3b: Auto-approving and dispatching emails...")

            from app.services.clint_recruitment_system import approve_and_notify
            result = approve_and_notify(job_id=job_id)

            logger.info(
                f"Emails dispatched — approved: {result['approved']}, "
                f"rejected: {result['rejected']}, "
                f"sent: {result['emails_sent']}, "
                f"failed: {result['emails_failed']}"
            )
        except Exception as e:
            logger.error(f"Auto-notify step failed: {str(e)}", exc_info=True)

        # ── STEP 4: JD match + auto-decision (95%) ── MUST come before completed
        try:
            update_pipeline_status(job_id, 'running', 'Running JD match and auto-decisions...', 95)
            from app.routes.interview.jd_matching import run_pipeline_decision
            from app.models.db import Candidate, SessionLocal

            session = SessionLocal()
            try:
                fresh_candidates = session.query(Candidate).filter_by(
                    job_id=str(job_id)
                ).all()
                for c in fresh_candidates:
                    run_pipeline_decision(
                        candidate_id=c.id,
                        jd_text=job_desc,
                    )
                logger.info(f"JD match + auto-decision done for {len(fresh_candidates)} candidates")
            finally:
                session.close()

        except Exception as e:
            logger.error(f"JD match step failed: {e}", exc_info=True)
            # Non-fatal — screening data is already saved

        # ── Clear caches AFTER all data is written ────────────────────────────
        cache.delete_memoized(get_cached_candidates)
        cache.delete_memoized(get_cached_jobs)

        # ── Mark completed LAST ───────────────────────────────────────────────
        assessment_info = " with assessment" if create_assessment_flag else ""
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