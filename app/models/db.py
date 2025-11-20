# app/models/db.py
"""
Database models and engine/session setup for the TalentFlow backend.
- Uses env var DATABASE_URL (falls back to SQLite file).
- Provides Base, engine, SessionLocal, and init/migration helpers.
- Models: Candidate, PipelineRun, EmailLog, User.
"""

import os
import logging
from datetime import datetime


from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, Text,
    Index, UniqueConstraint, inspect, text
)
from sqlalchemy.dialects.postgresql import JSON

from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# ---------- Core SQLAlchemy objects ----------
Base = declarative_base()

def get_database_url() -> str:
    """Resolve DB URL from env (DATABASE_URL). Defaults to a local SQLite file."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # If you use old postgres:// URIs, uncomment the next 2 lines
        # if db_url.startswith("postgres://"):
        #     db_url = db_url.replace("postgres://", "postgresql://", 1)
        return db_url

    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "..", "..", "hr_frontend.db")
    db_path = os.path.normpath(db_path)
    return f"sqlite:///{db_path}"

DB_URL = get_database_url()

engine = create_engine(
    DB_URL,
    poolclass=QueuePool,
    pool_size=10,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
    echo=os.getenv("FLASK_ENV") == "development",
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
    future=True,
)

# ---------- Models ----------
class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("idx_job_id", "job_id"),
        Index("idx_email", "email"),
        Index("idx_status", "status"),
        Index("idx_exam_completed", "exam_completed"),
        Index("idx_processed_date", "processed_date"),
        UniqueConstraint("email", "job_id", name="unique_email_job"),
    )

    id = Column(Integer, primary_key=True)

    # Job info
    job_id = Column(String(100), nullable=False)
    job_title = Column(String(200), nullable=False)

    # Basic info
    name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False)
    linkedin = Column(String(500))
    github = Column(String(500))
    resume_path = Column(String(500))
    phone = Column(String(50))

    # Resume processing / ATS
    processed_date = Column(DateTime, default=datetime.now, nullable=False)
    ats_score = Column(Float, default=0.0)
    status = Column(String(50))  # Shortlisted/Rejected/...
    score_reasoning = Column(Text)
    decision_reason = Column(Text)

    # Email notifications
    notification_sent = Column(Boolean, default=False)
    notification_sent_date = Column(DateTime)
    reminder_sent = Column(Boolean, default=False)
    reminder_sent_date = Column(DateTime)

    # Assessments
    assessment_invite_link = Column(String(500))
    assessment_id = Column(String(100))
    link_clicked = Column(Boolean, default=False)
    link_clicked_date = Column(DateTime)

    # Exam lifecycle
    exam_link_sent = Column(Boolean, default=False)
    exam_link_sent_date = Column(DateTime)
    exam_started = Column(Boolean, default=False)
    exam_started_date = Column(DateTime)
    exam_completed = Column(Boolean, default=False)
    exam_completed_date = Column(DateTime)

    # Exam results
    exam_score = Column(Integer, default=0)
    exam_total_questions = Column(Integer, default=0)
    exam_correct_answers = Column(Integer, default=0)
    exam_percentage = Column(Float, default=0.0)
    exam_time_taken = Column(Integer)  # minutes
    exam_feedback = Column(Text)
    exam_sections_scores = Column(Text)        # JSON
    exam_difficulty_level = Column(String(50)) # Easy/Medium/Hard
    exam_cheating_flag = Column(Boolean, default=False)

    # Interview scheduling/status
    interview_scheduled = Column(Boolean, default=False)
    interview_date = Column(DateTime)
    interview_link = Column(String(500))
    interview_type = Column(String(50))
    interviewer_name = Column(String(200))
    interview_feedback = Column(Text)
    interview_score = Column(Float)

    # Final status
    final_status = Column(String(100))
    rejection_reason = Column(Text)

    # Offer
    offer_extended = Column(Boolean, default=False)
    offer_extended_date = Column(DateTime)
    offer_accepted = Column(Boolean, default=False)
    offer_accepted_date = Column(DateTime)
    joining_date = Column(DateTime)
    offered_salary = Column(Float)

    # Analytics/meta
    source = Column(String(100))
    recruiter_notes = Column(Text)
    tags = Column(Text)  # JSON

    # Interview Automation / Avatar
    interview_kb_id = Column(String(200))
    interview_token = Column(String(255), unique=True, nullable=True)
    interview_created_at = Column(DateTime)
    interview_expires_at = Column(DateTime)
    interview_started_at = Column(DateTime)
    interview_completed_at = Column(DateTime)
    interview_transcript = Column(Text)
    interview_recording_url = Column(String(500))
    interview_ai_summary = Column(Text)
    interview_ai_score = Column(Float)

    # Interview Recording/Session
    interview_session_id = Column(String(200))
    interview_recording_file = Column(String(500))
    interview_recording_duration = Column(Integer) # seconds
    interview_recording_size = Column(Integer)     # bytes
    interview_recording_format = Column(String(50))
    interview_recording_quality = Column(String(50))

    # Q&A / Progress
    interview_questions_asked = Column(Text)     # JSON
    interview_answers_given = Column(Text)       # JSON
    interview_question_timestamps = Column(Text) # JSON
    interview_answer_timestamps = Column(Text)   # JSON
    interview_total_questions = Column(Integer, default=0)
    interview_answered_questions = Column(Integer, default=0)
    interview_progress_percentage = Column(Float, default=0.0)
    interview_last_activity = Column(DateTime)
    interview_qa_pairs = Column(Text, default="[]")
    interview_duration = Column(Integer)  # seconds
    interview_link_clicked = Column(Boolean, default=False)
    interview_link_clicked_at = Column(DateTime)
    interview_status = Column(String(50))
    interview_voice_transcripts = Column(Text)

    # AI Analysis
    interview_ai_questions_analysis = Column(Text)
    interview_ai_overall_feedback = Column(Text)
    interview_ai_technical_score = Column(Float)
    interview_ai_communication_score = Column(Float)
    interview_ai_problem_solving_score = Column(Float)
    interview_ai_cultural_fit_score = Column(Float)
    interview_ai_strengths = Column(Text)  # JSON
    interview_ai_weaknesses = Column(Text) # JSON
    interview_confidence_score = Column(Float)
    interview_scoring_method = Column(String(50)) # 'ai' | 'rule-based'

    # Extra meta
    company_name = Column(String(200))
    job_description = Column(Text)

    # Email workflow flags
    interview_time_slot = Column(String(100))
    interview_email_sent = Column(Boolean, default=False)
    interview_email_sent_date = Column(DateTime)
    interview_email_attempts = Column(Integer, default=0)

    # Auto-scoring trigger flags
    interview_auto_score_triggered = Column(Boolean, default=False)
    interview_analysis_started_at = Column(DateTime)
    interview_analysis_completed_at = Column(DateTime)

    # Timestamps
    created_at = Column(DateTime, default=datetime.now, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} email={self.email!r} job_id={self.job_id!r}>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "job_id": self.job_id,
            "job_title": self.job_title,
            "status": self.status,
            "ats_score": self.ats_score,
            "final_status": self.final_status,
            "exam_completed": self.exam_completed,
            "exam_percentage": self.exam_percentage,
            "interview_scheduled": self.interview_scheduled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("idx_pipeline_job_id", "job_id"),
        Index("idx_pipeline_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(String(100), nullable=False)
    job_title = Column(String(200))
    started_at = Column(DateTime, default=datetime.now, nullable=False)
    completed_at = Column(DateTime)
    status = Column(String(50))  # running/completed/failed
    total_candidates = Column(Integer, default=0)
    shortlisted_count = Column(Integer, default=0)
    error_message = Column(Text)
    steps_completed = Column(Text)  # JSON array


class EmailLog(Base):
    __tablename__ = "email_logs"
    __table_args__ = (
        Index("idx_email_candidate", "candidate_id"),
        Index("idx_email_type", "email_type"),
    )

    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, nullable=False)
    email_type = Column(String(50))  # assessment_invite/reminder/interview/rejection
    sent_at = Column(DateTime, default=datetime.now, nullable=False)
    success = Column(Boolean, default=True)
    error_message = Column(Text)
    email_content = Column(Text)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    first_name = Column(String(100), nullable=False)
    last_name  = Column(String(100), nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    password_reset_at = Column(DateTime)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"

class AssessmentResult(Base):
    __tablename__ = 'assessment_results'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Common fields for both providers
    assessment_name = Column(String(255), nullable=False, index=True)
    candidate_name = Column(String(255), nullable=False)
    candidate_email = Column(String(255), nullable=False, index=True)
    score = Column(Float)  # Overall score
    status = Column(String(50))
    provider = Column(String(50))  # 'testlify' or 'criteria'
    
    # Testlify-specific fields (existing)
    testlify_test_id = Column(String(100))
    testlify_invitation_id = Column(String(100))
    testlify_completion_date = Column(DateTime)
    
    # Criteria-specific fields (NEW)
    criteria_assessment_id = Column(String(100))
    criteria_candidate_id = Column(String(100))
    criteria_assessment_type = Column(String(100))  # Cognitive, Personality, Skills
    criteria_percentile_rank = Column(Float)
    criteria_raw_score = Column(Float)
    criteria_scaled_score = Column(Float)
    criteria_stanine_score = Column(Integer)  # 1-9 scale
    criteria_sub_scores = Column(JSON)  # type: ignore # {"verbal": 85, "numerical": 92, etc.}
    criteria_test_date = Column(DateTime)
    criteria_completion_time = Column(Integer)  # minutes
    criteria_questions_answered = Column(Integer)
    criteria_questions_total = Column(Integer)
    criteria_test_status = Column(String(50))  # passed, failed, review
    criteria_recommendation = Column(String(100))  # strongly_recommend, recommend, etc.
    criteria_cognitive_ability = Column(Float)
    criteria_personality_fit = Column(Float)
    criteria_skills_match = Column(Float)
    criteria_culture_fit = Column(Float)
    criteria_report_url = Column(Text)
    criteria_detailed_report_url = Column(Text)
    
    # Common metadata
    raw_data = Column(JSON)  # Store complete response from either provider
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    synced_at = Column(DateTime)
    
    def __repr__(self):
        return f"<AssessmentResult({self.candidate_name}, {self.assessment_name}, {self.provider})>"


# ---------- Initialization / Migration helpers ----------
def init_db() -> None:
    """Create tables if they do not exist."""
    try:
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.exception("Error creating database tables: %s", e)
        raise

def add_column_if_not_exists(table_name: str, column_name: str, column_type_sql: str) -> None:
    """Add a column to an existing table if missing (simple SQL-based migration)."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns(table_name)]
    if column_name in cols:
        return

    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type_sql}"))
        conn.commit()
    logger.info("Added column %s to %s", column_name, table_name)

def run_migrations() -> None:
    """Best-effort migrations for added fields over time."""
    try:
        # (SQLite syntax used; for Postgres/MySQL, the SQL above still works for basic ADD COLUMN)
        migrations = [
            ("candidates", "phone", "VARCHAR(50)"),
            ("candidates", "assessment_id", "VARCHAR(100)"),
            ("candidates", "reminder_sent", "BOOLEAN DEFAULT FALSE"),
            ("candidates", "reminder_sent_date", "DATETIME"),
            ("candidates", "exam_sections_scores", "TEXT"),
            ("candidates", "exam_difficulty_level", "VARCHAR(50)"),
            ("candidates", "exam_cheating_flag", "BOOLEAN DEFAULT FALSE"),
            ("candidates", "interview_type", "VARCHAR(50)"),
            ("candidates", "interview_feedback", "TEXT"),
            ("candidates", "interview_score", "FLOAT"),
            ("candidates", "interviewer_name", "VARCHAR(200)"),
            ("candidates", "rejection_reason", "TEXT"),
            ("candidates", "offer_extended", "BOOLEAN DEFAULT FALSE"),
            ("candidates", "offer_extended_date", "DATETIME"),
            ("candidates", "offer_accepted", "BOOLEAN DEFAULT FALSE"),
            ("candidates", "offer_accepted_date", "DATETIME"),
            ("candidates", "joining_date", "DATETIME"),
            ("candidates", "offered_salary", "FLOAT"),
            ("candidates", "source", "VARCHAR(100)"),
            ("candidates", "recruiter_notes", "TEXT"),
            ("candidates", "tags", "TEXT"),
            ("candidates", "created_at", "DATETIME"),
            ("candidates", "updated_at", "DATETIME"),
            # interview/automation extras (if upgrading existing DBs)
            ("candidates", "interview_kb_id", "VARCHAR(200)"),
            ("candidates", "interview_token", "VARCHAR(255)"),
            ("candidates", "interview_created_at", "DATETIME"),
            ("candidates", "interview_expires_at", "DATETIME"),
            ("candidates", "interview_started_at", "DATETIME"),
            ("candidates", "interview_completed_at", "DATETIME"),
            ("candidates", "interview_transcript", "TEXT"),
            ("candidates", "interview_recording_url", "VARCHAR(500)"),
            ("candidates", "interview_ai_summary", "TEXT"),
            ("candidates", "interview_ai_score", "FLOAT"),
            ("candidates", "interview_time_slot", "VARCHAR(100)"),
            ("candidates", "interview_email_sent", "BOOLEAN DEFAULT FALSE"),
            ("candidates", "interview_email_sent_date", "DATETIME"),
            ("candidates", "interview_email_attempts", "INTEGER DEFAULT 0"),
            ("candidates", "company_name", "VARCHAR(200)"),
            ("candidates", "job_description", "TEXT"),
            ("candidates", "interview_auto_score_triggered", "BOOLEAN DEFAULT FALSE"),
        ]
        for table, column, typ in migrations:
            try:
                add_column_if_not_exists(table, column, typ)
            except Exception as e:
                logger.warning("Migration for %s.%s failed: %s", table, column, e)

        logger.info("Database migrations completed")
    except Exception as e:
        logger.exception("Migration error: %s", e)

# ---------- Utilities ----------
def get_db():
    """Yield a SQLAlchemy session (context-manager style if desired)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

__all__ = [
    "Base", "engine", "SessionLocal",
    "Candidate", "PipelineRun", "EmailLog", "User",
    "init_db", "run_migrations", "get_db",
]

