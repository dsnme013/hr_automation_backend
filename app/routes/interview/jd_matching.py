# app/routes/interview/jd_matching.py
#
# ── What this file adds ───────────────────────────────────────────────────────
#   Feature 1 — JD Deconstruction      POST /api/jobs/<job_id>/analyze
#   Feature 2 — Semantic JD Matching   run_jd_match()   (called from pipeline)
#   Feature 3 — Auto-decision trigger  POST /api/candidates/<id>/auto-decision
#   Bonus     — Match report           GET  /api/candidates/<id>/match-report
# ─────────────────────────────────────────────────────────────────────────────
#
# HOW TO WIRE UP (see bottom of file for copy-paste snippets):
#   1. Add `jd_matching_bp` to app/routes/interview/__init__.py
#   2. Call `run_jd_match(candidate, session)` inside your screening pipeline
#      right after you save the ATS score.
#   3. Add two columns to your Candidate model (see DB COLUMNS section below).
# ─────────────────────────────────────────────────────────────────────────────

from flask import Blueprint, jsonify, request
from datetime import datetime
import json, os

from app.extensions import cache, logger
from app.models.db import Candidate, SessionLocal
from app.routes.shared import rate_limit

try:
    # Job model — import only if it exists in your db module
    from app.models.db import Job
    _HAS_JOB_MODEL = True
except ImportError:
    _HAS_JOB_MODEL = False

jd_matching_bp = Blueprint("jd_matching", __name__)

# ── Anthropic client (lazy init so missing key doesn't crash startup) ─────────
_anthropic_client = None

def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
    return _anthropic_client


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER — safe JSON list (mirrors your existing _safe_json_list in candidates.py)
# ═══════════════════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 1 — JD DECONSTRUCTION
# POST /api/jobs/<job_id>/analyze
#
# Call this once when a job is created or its description is updated.
# Stores structured JD data back to the Job row so Feature 2 can use it.
# ═══════════════════════════════════════════════════════════════════════════════
@jd_matching_bp.route("/api/jobs/<job_id>/analyze", methods=["POST", "OPTIONS"])
@rate_limit(max_calls=20, time_window=60)
def analyze_jd(job_id):
    """
    Deconstruct a messy job description into structured hiring criteria.

    Request body (optional):
        { "jd_text": "...raw job description..." }
        If omitted, fetches description from the Job table using job_id.

    Response:
        {
          "must_have_skills":    ["Python", "FastAPI"],
          "good_to_have_skills": ["Docker"],
          "seniority_level":     "mid",
          "experience_type":     "startup",
          "hidden_expectations": ["on-call", "ownership"],
          "min_years_experience": 3
        }
    """
    if request.method == "OPTIONS":
        return "", 200

    session = SessionLocal()
    try:
        # ── Get JD text ───────────────────────────────────────────────────────
        data    = request.get_json(silent=True) or {}
        jd_text = data.get("jd_text", "").strip()

        if not jd_text and _HAS_JOB_MODEL:
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                return jsonify({"error": "Job not found", "job_id": job_id}), 404
            jd_text = getattr(job, "description", "") or ""

        if not jd_text:
            return jsonify({"error": "No job description found or provided"}), 400

        # ── Call Claude ───────────────────────────────────────────────────────
        client   = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": (
                    "Analyze this job description and return ONLY a JSON object.\n"
                    "No explanation. No markdown. No backticks.\n\n"
                    f"JOB DESCRIPTION:\n{jd_text[:3000]}\n\n"
                    "Return EXACTLY this structure:\n"
                    "{\n"
                    '  "must_have_skills": ["skill1", "skill2"],\n'
                    '  "good_to_have_skills": ["skill1"],\n'
                    '  "seniority_level": "junior|mid|senior|lead",\n'
                    '  "experience_type": "startup|enterprise|domain-specific",\n'
                    '  "hidden_expectations": ["ownership", "on-call"],\n'
                    '  "min_years_experience": 3\n'
                    "}"
                ),
            }],
        )

        raw_text   = response.content[0].text.strip()
        jd_breakdown = json.loads(raw_text)

        # ── Save back to Job row if model exists ──────────────────────────────
        if _HAS_JOB_MODEL:
            job = session.query(Job).filter_by(id=job_id).first()
            if job and hasattr(job, "jd_breakdown"):
                job.jd_breakdown = json.dumps(jd_breakdown)
                session.commit()
                logger.info(f"JD breakdown saved for job {job_id}")

        return jsonify({
            "success":      True,
            "job_id":       job_id,
            "jd_breakdown": jd_breakdown,
        }), 200

    except json.JSONDecodeError as e:
        logger.error(f"Claude returned invalid JSON for JD {job_id}: {e}")
        return jsonify({"error": "AI returned invalid JSON", "detail": str(e)}), 500
    except Exception as e:
        logger.error(f"JD analysis error for job {job_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 2 — SEMANTIC JD MATCHING  (called from your screening pipeline)
#
# This is a FUNCTION, not an endpoint. Call it right after you compute
# the ATS score in your existing screening pipeline:
#
#     from app.routes.interview.jd_matching import run_jd_match
#     match_result = run_jd_match(candidate, session, jd_text=job_description)
#
# It writes directly to the candidate row and commits.
# ═══════════════════════════════════════════════════════════════════════════════
def run_jd_match(candidate, session, jd_text: str = "") -> dict | None:
    """
    Semantic match between candidate resume and job requirements.

    NOT keyword matching — Claude reasons about meaning:
      "Built ML pipeline" → matches "data engineering exposure"

    Output saved to candidate:
        match_type          "Strong Fit" | "Partial Fit" | "Weak Fit"
        match_score         0-100
        rejection_summary   one-sentence explanation
        rejection_reasons   JSON list of gap strings
        matched_skills      JSON list
        missing_skills      JSON list
        recommendation      "Proceed" | "HR Review" | "Reject"

    Returns the parsed dict or None on failure.
    """
    try:
        score         = float(getattr(candidate, "ats_score", 0) or 0)
        resume_text   = getattr(candidate, "score_reasoning", "") or ""
        position      = getattr(candidate, "job_title",      "") or "this role"

        # Try to get JD breakdown from Job table if jd_text not passed
        jd_info = jd_text
        if not jd_info and _HAS_JOB_MODEL:
            s = session
            job = s.query(Job).filter_by(id=getattr(candidate, "job_id", None)).first()
            if job:
                raw_bd = getattr(job, "jd_breakdown", None)
                if raw_bd:
                    try:
                        jd_info = json.dumps(json.loads(raw_bd))
                    except Exception:
                        jd_info = getattr(job, "description", "") or ""
                else:
                    jd_info = getattr(job, "description", "") or ""

        if not jd_info and not resume_text:
            logger.warning(f"run_jd_match: no JD or resume data for candidate {candidate.id}")
            return None

        # ── Call Claude ───────────────────────────────────────────────────────
        client   = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": (
                    "You are a senior technical recruiter. "
                    "Compare this candidate against job requirements SEMANTICALLY — not by keywords.\n"
                    "Return ONLY a JSON object. No explanation. No markdown. No backticks.\n\n"
                    f"JOB REQUIREMENTS / DESCRIPTION:\n{str(jd_info)[:1500]}\n\n"
                    f"CANDIDATE PROFILE (ATS Score: {score}/100):\n{resume_text[:1500]}\n\n"
                    f"ROLE: {position}\n\n"
                    "Return EXACTLY:\n"
                    "{\n"
                    '  "match_type": "Strong Fit|Partial Fit|Weak Fit",\n'
                    '  "match_score": 85,\n'
                    '  "requirements_met": 4,\n'
                    '  "requirements_total": 5,\n'
                    '  "match_explanation": "One concise sentence — why they fit or do not fit",\n'
                    '  "matched_skills": ["skill1", "skill2"],\n'
                    '  "missing_skills": ["skill3"],\n'
                    '  "gap_analysis": ["Lacks production deployment", "No domain exposure"],\n'
                    '  "recommendation": "Proceed|HR Review|Reject"\n'
                    "}"
                ),
            }],
        )

        result = json.loads(response.content[0].text.strip())

        # ── Write to candidate row ────────────────────────────────────────────
        _set_if_exists(candidate, "match_type",        result.get("match_type"))
        _set_if_exists(candidate, "match_score",       result.get("match_score"))
        _set_if_exists(candidate, "recommendation",    result.get("recommendation"))
        _set_if_exists(candidate, "rejection_summary", result.get("match_explanation", ""))
        _set_if_exists(candidate, "matched_skills",
                       json.dumps(result.get("matched_skills", [])))
        _set_if_exists(candidate, "missing_skills",
                       json.dumps(result.get("missing_skills", [])))
        _set_if_exists(candidate, "rejection_reasons",
                       json.dumps(result.get("gap_analysis", [])))

        session.commit()
        logger.info(
            f"JD match for candidate {candidate.id}: "
            f"{result.get('match_type')} / rec={result.get('recommendation')}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"run_jd_match JSON error for candidate {candidate.id}: {e}")
        return None
    except Exception as e:
        logger.error(f"run_jd_match error for candidate {candidate.id}: {e}", exc_info=True)
        return None


def _set_if_exists(obj, attr, value):
    """Write attr only if the column already exists on the model."""
    if hasattr(obj, attr):
        setattr(obj, attr, value)


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 3 — AUTO-DECISION TRIGGER
# POST /api/candidates/<candidate_id>/auto-decision
#
# Scoring rules (match your existing thresholds):
#   ATS score >= 80  → Shortlisted + auto-schedule interview
#   ATS score 60-79  → Pending Review (HR sees a notification)
#   ATS score < 60   → Rejected automatically
#
# Call this endpoint from your pipeline after run_jd_match(), OR
# let HR trigger it manually from the frontend.
# ═══════════════════════════════════════════════════════════════════════════════
@jd_matching_bp.route(
    "/api/candidates/<int:candidate_id>/auto-decision",
    methods=["POST", "OPTIONS"]
)
@rate_limit(max_calls=30, time_window=60)
def auto_decision(candidate_id):
    """
    Score-based auto-decision gate.

    Optionally accept overrides:
        { "threshold_auto_schedule": 80, "threshold_hr_review": 60 }

    Response:
        {
          "candidate_id": 42,
          "score": 83,
          "action": "auto_scheduled" | "hr_review_required" | "auto_rejected",
          "status": "Shortlisted",
          "match_type": "Strong Fit",
          "recommendation": "Proceed"
        }
    """
    if request.method == "OPTIONS":
        return "", 200

    session = SessionLocal()
    try:
        c = session.query(Candidate).filter_by(id=candidate_id).first()
        if not c:
            return jsonify({"error": "Candidate not found"}), 404

        data = request.get_json(silent=True) or {}
        threshold_schedule  = int(data.get("threshold_auto_schedule", 80))
        threshold_hr_review = int(data.get("threshold_hr_review",      60))

        score  = float(getattr(c, "ats_score", 0) or 0)
        action = None

        # ── Decision logic ────────────────────────────────────────────────────
        if score >= threshold_schedule:
            # Strong candidate — shortlist and flag for interview scheduling
            c.status = "Shortlisted"
            _set_if_exists(c, "auto_decision_taken", True)
            action = "auto_scheduled"
            logger.info(
                f"AUTO-SCHEDULE: candidate {candidate_id} score={score} "
                f">= {threshold_schedule}"
            )

        elif score >= threshold_hr_review:
            # Borderline — surface to HR with context
            _set_if_exists(c, "status", "Pending Review")
            _set_if_exists(c, "auto_decision_taken", False)
            action = "hr_review_required"
            logger.info(
                f"HR REVIEW: candidate {candidate_id} score={score} "
                f"in [{threshold_hr_review}, {threshold_schedule})"
            )

        else:
            # Weak match — auto reject
            c.status = "Rejected"
            _set_if_exists(c, "final_status", "Rejected After Screening")
            _set_if_exists(c, "auto_decision_taken", True)
            action = "auto_rejected"
            logger.info(
                f"AUTO-REJECT: candidate {candidate_id} score={score} "
                f"< {threshold_hr_review}"
            )

        session.commit()

        # Bust candidate list cache so frontend reflects the new status
        try:
            cache.delete_memoized(
                # import here to avoid circular import
                __import__(
                    "app.routes.candidates",
                    fromlist=["get_cached_candidates"]
                ).get_cached_candidates
            )
        except Exception:
            pass  # Non-fatal — cache will expire naturally

        return jsonify({
            "success":        True,
            "candidate_id":   candidate_id,
            "candidate_name": getattr(c, "name", ""),
            "score":          score,
            "action":         action,
            "status":         c.status,
            "match_type":     getattr(c, "match_type",     None),
            "recommendation": getattr(c, "recommendation", None),
            "thresholds_used": {
                "auto_schedule":  threshold_schedule,
                "hr_review":      threshold_hr_review,
            },
        }), 200

    except Exception as e:
        session.rollback()
        logger.error(f"auto_decision error for candidate {candidate_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# BONUS — MATCH REPORT  GET /api/candidates/<id>/match-report
#
# Frontend reads this to show the "Why Shortlisted / Why Rejected" panel
# without duplicating data (replaces the double-render bug from the old code).
# ═══════════════════════════════════════════════════════════════════════════════
@jd_matching_bp.route(
    "/api/candidates/<int:candidate_id>/match-report",
    methods=["GET", "OPTIONS"]
)
@rate_limit(max_calls=60, time_window=60)
def match_report(candidate_id):
    """
    Single source of truth for the candidate detail panel.

    Returns all match + rejection data in one clean structure so the
    frontend never needs to read the same field from two places.
    """
    if request.method == "OPTIONS":
        return "", 200

    session = SessionLocal()
    try:
        c = session.query(Candidate).filter_by(id=candidate_id).first()
        if not c:
            return jsonify({"error": "Candidate not found"}), 404

        score = float(getattr(c, "ats_score", 0) or 0)

        return jsonify({
            "candidate_id":    candidate_id,
            "name":            getattr(c, "name", ""),
            "ats_score":       score,

            # ── Match summary ─────────────────────────────────────────────────
            "match_type":      getattr(c, "match_type",      None),
            "match_score":     getattr(c, "match_score",     None),
            "recommendation":  getattr(c, "recommendation",  None),
            "explanation":     getattr(c, "rejection_summary", ""),

            # ── Skill breakdown ───────────────────────────────────────────────
            "matched_skills":  _safe_json_list(getattr(c, "matched_skills",  None)),
            "missing_skills":  _safe_json_list(getattr(c, "missing_skills",  None)),
            "gap_analysis":    _safe_json_list(getattr(c, "rejection_reasons", None)),

            # ── Decision metadata ─────────────────────────────────────────────
            "status":          getattr(c, "status",           ""),
            "final_status":    getattr(c, "final_status",     ""),
            "auto_decision":   getattr(c, "auto_decision_taken", None),
            "generated_at":    datetime.utcnow().isoformat(),
        }), 200

    except Exception as e:
        logger.error(f"match_report error for candidate {candidate_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE HELPER — call this from your existing screening code
#
# Usage (copy into wherever you process new resumes):
#
#   from app.routes.interview.jd_matching import run_pipeline_decision
#
#   # After ATS score is saved:
#   run_pipeline_decision(candidate_id=c.id, jd_text=job_description)
#
# This runs Feature 2 + Feature 3 in one call.
# ═══════════════════════════════════════════════════════════════════════════════
def run_pipeline_decision(candidate_id: int, jd_text: str = "") -> dict:
    """
    Convenience wrapper: run JD match then auto-decision in one call.
    Designed to be called from your background screening thread.

    Returns:
        { "match": <match_result>, "decision": <action_taken> }
    """
    session = SessionLocal()
    try:
        c = session.query(Candidate).filter_by(id=candidate_id).first()
        if not c:
            return {"error": f"Candidate {candidate_id} not found"}

        # Step 1 — Semantic match
        match_result = run_jd_match(c, session, jd_text=jd_text)

        # Step 2 — Auto-decision
        score = float(getattr(c, "ats_score", 0) or 0)
        if score >= 80:
            action = "auto_scheduled"
            c.status = "Shortlisted"
            _set_if_exists(c, "auto_decision_taken", True)
        elif score >= 60:
            action = "hr_review_required"
            _set_if_exists(c, "status", "Pending Review")
        else:
            action = "auto_rejected"
            c.status = "Rejected"
            _set_if_exists(c, "final_status", "Rejected After Screening")
            _set_if_exists(c, "auto_decision_taken", True)

        session.commit()
        logger.info(f"Pipeline decision for {candidate_id}: {action}")

        return {
            "candidate_id": candidate_id,
            "match":        match_result,
            "decision":     action,
            "score":        score,
        }

    except Exception as e:
        session.rollback()
        logger.error(f"run_pipeline_decision error: {e}", exc_info=True)
        return {"error": str(e)}
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ──────────────────────────  WIRING INSTRUCTIONS  ────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════
#
# 1. ADD TO  app/routes/interview/__init__.py
#    ─────────────────────────────────────────
#    from .jd_matching import jd_matching_bp
#
#    __all__ = [
#        ...existing entries...,
#        "jd_matching_bp",
#    ]
#
#
# 2. REGISTER IN  app/__init__.py  (or wherever you register blueprints)
#    ──────────────────────────────────────────────────────────────────
#    from app.routes.interview import jd_matching_bp
#    app.register_blueprint(jd_matching_bp)
#
#
# 3. ADD TO YOUR SCREENING PIPELINE  (wherever you call Claude to score resumes)
#    ─────────────────────────────────────────────────────────────────────────
#    from app.routes.interview.jd_matching import run_pipeline_decision
#
#    # After saving ATS score to DB:
#    run_pipeline_decision(
#        candidate_id=candidate.id,
#        jd_text=job_description,   # pass the raw JD string
#    )
#
#
# 4. NEW DB COLUMNS  (add to your Candidate model in app/models/db.py)
#    ──────────────────────────────────────────────────────────────────
#    match_type          = Column(String(50),   nullable=True)
#    match_score         = Column(Float,        nullable=True)
#    recommendation      = Column(String(50),   nullable=True)
#    auto_decision_taken = Column(Boolean,      default=False)
#
#    Then run:  alembic revision --autogenerate -m "add jd match fields"
#               alembic upgrade head
#
#
# 5. NEW DB COLUMN on Job model  (only if you have a Job table)
#    ──────────────────────────────────────────────────────────
#    jd_breakdown = Column(Text, nullable=True)   # stores JSON from analyze_jd
#
#
# 6. FIX THE FRONTEND DUPLICATION BUG
#    ────────────────────────────────────────────────────────────────────────
#    In Candidate_Details.tsx, the "Notes & Feedback" section renders the
#    same rejection_breakdown as "Why Rejected". Fix:
#
#    Replace the AI block inside notes-card with:
#        <div className="notes-empty">No notes yet</div>
#
#    The AI reasoning already shows in "Why Rejected" — no need to repeat it.
#    Use GET /api/candidates/<id>/match-report as your single data source.
#
# ═══════════════════════════════════════════════════════════════════════════════