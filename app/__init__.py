# from flask import Flask
# from .extensions import cache, logger, executor
# # from .routes.api import api_bp
# from .routes.health import health_bp
# from .routes.auth import auth_bp
# from .config import ProductionConfig
# from flask_cors import CORS

# def create_app(config_object: str | None = None):
#     app = Flask(__name__)
#     if config_object:
#         app.config.from_object(config_object)
#     else:
#         app.config.from_object(ProductionConfig)

#     cache.init_app(app)
#     CORS(app, 
#          origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://127.0.0.1:3001", "https://yourfrontenddomain.com"],
#          allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Cache-Control","X-Api-Key"],
#          methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
#          supports_credentials=True,
#          expose_headers=["Content-Type", "Authorization"])

#     app.register_blueprint(health_bp)
#     app.register_blueprint(auth_bp)
#     app.register_blueprint(api_bp, url_prefix="/")

#     return app

# # app/__init__.py
# from flask import Flask
# from .extensions import cache, logger, executor
# # from app.routes.api import api_bp
# from app.routes.health import health_bp
# from app.routes.auth import auth_bp
# from app.config import ProductionConfig
# from flask_cors import CORS
# from app.routes.misc import misc_bp
# from app.routes.stats import stats_bp
# # from app.routes.debug import debug_bp
# from app.routes.interview.interview_core import interview_core_bp
# from app.routes.candidates import candidates_bp
# from app.routes.pipeline import pipeline_bp
# from app.routes.shared import shared_bp
# from app.routes.scraping import scraping_bp
# from app.routes.jobs import jobs_bp
# from app.routes.interview.analytics import analytics_bp
# from app.routes.interview.conversation import conversation_bp
# from app.routes.interview.avatar import avatar_bp
# from app.routes.interview.debug import debug_bp
# from app.routes.interview.automation import automation_bp
# from app.routes.interview.helpers import helpers_bp
# from app.routes.interview.kb import kb_bp

# def create_app(config_object: str | None = None):
#     app = Flask(__name__)

#     # Load configuration from the provided object, or default to ProductionConfig
#     if config_object:
#         app.config.from_object(config_object)
#     else:
#         app.config.from_object(ProductionConfig)

#     # Initialize extensions
#     cache.init_app(app)
#     # logger.init_app(app)  # If you need to initialize logging, add it here
#     # executor.init_app(app)  # If you need to initialize the executor, add it here

#     # Set up Cross-Origin Resource Sharing (CORS)
#     CORS(app, 
#          origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://127.0.0.1:3001", "https://yourfrontenddomain.com"],
#          allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Cache-Control", "X-Api-Key"],
#          methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
#          supports_credentials=True,
#          expose_headers=["Content-Type", "Authorization"])

#     # Register blueprints
#     app.register_blueprint(health_bp)
#     app.register_blueprint(auth_bp)
#     app.register_blueprint(misc_bp) 
#     app.register_blueprint(jobs_bp)
#     app.register_blueprint(candidates_bp)
#     app.register_blueprint(pipeline_bp)
#     app.register_blueprint(stats_bp)
#     app.register_blueprint(shared_bp)
#     app.register_blueprint(scraping_bp)
#     app.register_blueprint(interview_core_bp)
#     app.register_blueprint(analytics_bp)
#     app.register_blueprint(conversation_bp)
#     app.register_blueprint(avatar_bp)
#     app.register_blueprint(debug_bp)
#     app.register_blueprint(automation_bp)
#     app.register_blueprint(helpers_bp)
#     app.register_blueprint(kb_bp)
#     # app.register_blueprint(api_bp, url_prefix="/")

#     # Register error handler for 404
#     @app.errorhandler(404)
#     def page_not_found(error):
#         return "Page not found", 404

#     return app

import logging
import traceback
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, jsonify, request
from .extensions import cache, logger, executor
from app.config import ProductionConfig
from flask_cors import CORS
from flask import Flask
from .extensions import cache, logger, executor
# from app.routes.api import api_bp
from app.routes.health import health_bp
from app.routes.auth import auth_bp
from app.config import ProductionConfig
from app.routes.misc import misc_bp
from app.routes.stats import stats_bp
# from app.routes.debug import debug_bp
from app.routes.interview.interview_core import interview_core_bp
from app.routes.candidates import candidates_bp
from app.routes.pipeline import pipeline_bp
from app.routes.shared import shared_bp
from app.routes.scraping import scraping_bp
from app.routes.jobs import jobs_bp
from app.routes.interview.analytics import analytics_bp
from app.routes.interview.conversation import conversation_bp
from app.routes.interview.avatar import avatar_bp
from app.routes.interview.debug import debug_bp
from app.routes.interview.automation import automation_bp
from app.routes.interview.helpers import helpers_bp
from app.routes.interview.kb import kb_bp
# (keep your existing imports — not removing anything)

def create_app(config_object: str | None = None):
    app = Flask(__name__)

    # Load configuration
    if config_object:
        app.config.from_object(config_object)
    else:
        app.config.from_object(ProductionConfig)
    
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
        x_prefix=1
    )

    # ✅ Setup logging for all levels
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

    # ✅ Add request logging
    @app.before_request
    def log_request():
        app.logger.info(f"➡️  {request.method} {request.path}")

    # ✅ Add global error handler with traceback printing
    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error("🔥 Unhandled Exception:")
        traceback.print_exc()  # full traceback in console
        return jsonify({
            "success": False,
            "error": str(e),
            "path": request.path
        }), 500

    # Initialize extensions
    cache.init_app(app)

    # Enable CORS
    CORS(app,
         origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://127.0.0.1:3001"],
         allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "Cache-Control", "X-Api-Key"],
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
         supports_credentials=True,
         expose_headers=["Content-Type", "Authorization"])

    # Register blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(misc_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(candidates_bp)
    app.register_blueprint(pipeline_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(scraping_bp)
    app.register_blueprint(interview_core_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(conversation_bp)
    app.register_blueprint(avatar_bp)
    app.register_blueprint(debug_bp)
    app.register_blueprint(automation_bp)
    app.register_blueprint(helpers_bp)
    app.register_blueprint(kb_bp)

    # ✅ 404 handler
    @app.errorhandler(404)
    def page_not_found(error):
        app.logger.warning(f"❌ 404 on {request.path}")
        return jsonify({"error": "Page not found", "path": request.path}), 404

    return app
