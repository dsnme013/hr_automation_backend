
# from .misc import misc_bp
# from .jobs import jobs_bp
# from .candidates import candidates_bp
# from .pipeline import pipeline_bp
# from .stats import stats_bp
# from .scraping import scraping_bp
# from .interview import interview_bp
# from .debug import debug_bp

# __all__ = ["misc_bp","jobs_bp","candidates_bp","pipeline_bp","stats_bp","scraping_bp","interview_bp","debug_bp"]
# app/routes/__init__.py
from .health import health_bp
from .auth import auth_bp
from .misc import misc_bp  
# DO NOT import .interview here — import it directly where needed.

__all__ = ["health_bp", "auth_bp","misc_bp"]