# # from app import create_app

# # app = create_app()

# # if __name__ == "__main__":
# #     app.run(host="0.0.0.0", port=5000, debug=True)

# """
# run.py — TalentFlow AI entry point

# Starts:
#   - Flask app
#   - PostAssessmentAutomation (24/7 background thread)
#       Every 15 min: scrape RecruitAI -> save score -> send interview/rejection email
# """

# import logging
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s  %(name)s  %(levelname)s  %(message)s"
# )

# logger = logging.getLogger(__name__)
# from app import create_app

# app = create_app()

# with app.app_context():
#     try:
#         from app.models.db import init_db, run_migrations
#         logger.info("Checking database...")
#         init_db()           # creates missing tables
#         run_migrations()    # adds missing columns
#         logger.info("Database ready.")
#     except Exception as e:
#         logger.error("DB setup error: %s", e, exc_info=True)
#         # Don't crash Flask — app still starts

# # ── Start 24/7 post-assessment background service ─────────────────────────────
# with app.app_context():
#     try:
#         from app.services.post_assessment_automation import start_post_assessment_automation
#         start_post_assessment_automation()
#     except Exception as e:
#         logging.getLogger(__name__).error(
#             "Failed to start PostAssessmentAutomation: %s", e, exc_info=True
#         )

# if __name__ == "__main__":
#     # use_reloader=False is critical — reloader spawns a second process
#     # which would start a duplicate background thread
#     app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
# from app import create_app

# app = create_app()

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000, debug=True)

"""
run.py — TalentFlow AI entry point

Starts:
  - Flask app
  - PostAssessmentAutomation (24/7 background thread)
      Every 15 min: scrape RecruitAI -> save score -> send interview/rejection email
"""

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s"
)

logger = logging.getLogger(__name__)
from app import create_app

app = create_app()

with app.app_context():
    try:
        from app.models.db import init_db, run_migrations
        logger.info("Checking database...")
        init_db()           # creates missing tables
        run_migrations()    # adds missing columns
        logger.info("Database ready.")
    except Exception as e:
        logger.error("DB setup error: %s", e, exc_info=True)
        # Don't crash Flask — app still starts

# ── Start 24/7 post-assessment background service ─────────────────────────────
with app.app_context():
    try:
        from app.services.post_assessment_automation import start_post_assessment_automation
        start_post_assessment_automation()
    except Exception as e:
        logging.getLogger(__name__).error(
            "Failed to start PostAssessmentAutomation: %s", e, exc_info=True
        )

if __name__ == "__main__":
    # use_reloader=False is critical — reloader spawns a second process
    # which would start a duplicate background thread
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)