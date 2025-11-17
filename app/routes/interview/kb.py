
from functools import cache
from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import os, json, time, uuid, requests
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_
from app.models.db import Candidate, SessionLocal
from app.extensions import logger
from app.routes.interview.avatar import create_heygen_knowledge_base
from app.routes.interview.helpers import extract_resume_content
from app.routes.interview.automation import generate_interview_questions
from app.routes.interview.helpers import create_structured_interview_kb
from app.routes.interview.helpers import generate_custom_interview_prompt
from app.routes.candidates import get_cached_candidates
try:
    from app.extensions import executor
except Exception:
    executor = None
try:
    from app.routes.shared import rate_limit
except Exception:
    def rate_limit(*args, **kwargs):
        def _d(f):
            return f
        return _d


kb_bp = Blueprint('kb', __name__)

@kb_bp.route('/api/verify-knowledge-base/<candidate_id>', methods=['GET'])
def verify_knowledge_base(candidate_id):
    """Verify knowledge base content for debugging"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Extract resume content
        resume_content = ""
        if candidate.resume_path and os.path.exists(candidate.resume_path):
            resume_content = extract_resume_content(candidate.resume_path)
        
        # Build preview WITHOUT backslashes in f-string expressions
        questions = generate_interview_questions(
            candidate_name=candidate.name,
            position=candidate.job_title,
            resume_content=resume_content,
            job_description=getattr(candidate, 'job_description', f"Position: {candidate.job_title}")
        )
        questions_preview = (questions[:1000] + "...") if len(questions) > 1000 else questions
        
        return jsonify({
            "candidate_id": candidate.id,
            "name": candidate.name,
            "position": candidate.job_title,
            "knowledge_base_id": getattr(candidate, "knowledge_base_id", None),
            "resume_exists": bool(candidate.resume_path and os.path.exists(candidate.resume_path)),
            "resume_content_length": len(resume_content),
            "interview_scheduled": candidate.interview_scheduled,
            "generated_questions_preview": questions_preview,
            "total_questions_length": len(questions)
        }), 200
    finally:
        session.close()

@kb_bp.route('/api/create-knowledge-base', methods=['POST', 'OPTIONS'])
def create_knowledge_base_enhanced():
    """Create a structured interview knowledge base"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        candidate_name = data.get('candidateName')
        position = data.get('position')
        company = data.get('company', 'Our Company')
        token = data.get('token')
        
        if not candidate_name or not position:
            return jsonify({"error": "candidateName and position are required"}), 400
        
        logger.info(f" Creating structured KB for: {candidate_name} - {position}")
        
        # Get resume content
        resume_content = ""
        candidate_id = None
        job_description = data.get('jobDescription', '')
        
        if token:
            session = SessionLocal()
            try:
                cand = session.query(Candidate).filter_by(interview_token=token).first()
                if cand:
                    candidate_id = cand.id
                    if cand.resume_path and os.path.exists(cand.resume_path):
                        resume_content = extract_resume_content(cand.resume_path)
                    job_description = job_description or getattr(cand, 'job_description', '')
            finally:
                session.close()
        
        # Create structured interview content
        kb_content = create_structured_interview_kb(
            candidate_name=candidate_name,
            position=position,
            company=company,
            resume_content=resume_content,
            job_description=job_description
        )
        
        # Create opening line that immediately asks first question
        opening_line = f"Hello {candidate_name}, welcome to your interview for the {position} position at {company}. Let's begin. Could you please introduce yourself and tell me about your professional background and what led you to apply for this role?"
        
        heygen_key = os.getenv('HEYGEN_API_KEY')
        if not heygen_key:
            # Fallback
            fallback_kb_id = f"kb_structured_{candidate_name.replace(' ', '_')}_{int(time.time())}"
            logger.warning(f"No HeyGen API key, using fallback: {fallback_kb_id}")
            
            if candidate_id:
                session = SessionLocal()
                try:
                    cand = session.query(Candidate).filter_by(id=candidate_id).first()
                    if cand:
                        cand.knowledge_base_id = fallback_kb_id
                        cand.interview_kb_content = kb_content
                        session.commit()
                finally:
                    session.close()
            
            return jsonify({
                "success": True,
                "knowledgeBaseId": fallback_kb_id,
                "fallback": True
            }), 200
        
        # Create HeyGen knowledge base with strict instructions
        heygen_payload = {
            "name": f"Structured_Interview_{candidate_name.replace(' ', '_')}_{int(time.time())}",
            "description": f"Structured technical interview for {candidate_name} - {position}",
            "content": kb_content,
            "opening_line": opening_line,
            "custom_prompt": "You are a professional interviewer. Follow the structured questions EXACTLY as provided. No casual chat. When you receive INIT_INTERVIEW, immediately ask the first question about self-introduction.",
            "prompt": kb_content,  # Some endpoints use 'prompt' instead of 'content'
            "voice_settings": {
                "rate": 1.0,
                "emotion": "professional"
            }
        }
        
        # Try multiple endpoints
        endpoints = [
            "https://api.heygen.com/v1/streaming/knowledge_base/create",
            "https://api.heygen.com/v1/streaming/knowledge_base",
            "https://api.heygen.com/v1/streaming_avatar/knowledge_base"
        ]
        
        kb_id = None
        successful_endpoint = None
        
        for endpoint in endpoints:
            try:
                logger.info(f"Trying endpoint: {endpoint}")
                resp = requests.post(
                    endpoint,
                    headers={
                        "X-Api-Key": heygen_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    },
                    json=heygen_payload,
                    timeout=30
                )
                
                if resp.ok:
                    data = resp.json()
                    kb_id = (
                        data.get('data', {}).get('knowledge_base_id') or
                        data.get('knowledge_base_id') or
                        data.get('id')
                    )
                    if kb_id:
                        successful_endpoint = endpoint
                        logger.info(f"KB created successfully: {kb_id}")
                        break
                else:
                    logger.error(f"Endpoint {endpoint} failed: {resp.status_code} - {resp.text[:200]}")
                    
            except Exception as e:
                logger.error(f"Error with endpoint {endpoint}: {e}")
        
        if not kb_id:
            kb_id = f"kb_structured_{candidate_name.replace(' ', '_')}_{int(time.time())}"
            logger.warning(f"All endpoints failed, using fallback: {kb_id}")
        
        # Save to database
        if candidate_id:
            session = SessionLocal()
            try:
                cand = session.query(Candidate).filter_by(id=candidate_id).first()
                if cand:
                    cand.knowledge_base_id = kb_id
                    cand.interview_kb_content = kb_content
                    session.commit()
            finally:
                session.close()
        
        return jsonify({
            "success": True,
            "knowledgeBaseId": kb_id,
            "endpoint_used": successful_endpoint,
            "structured": True,
            "question_count": 10
        }), 200
        
    except Exception as e:
        logger.error(f"KB creation error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@kb_bp.route('/api/verify-knowledge-base', methods=['GET'])
def verify_kb_by_query():
    kb_id = request.args.get('id')
    if not kb_id:
        return jsonify({"error": "id is required"}), 400
    # If you want: actually check existence in your DB or HeyGen here
    return jsonify({"ok": True, "knowledge_base_id": kb_id}), 200

@kb_bp.route('/api/store-knowledge-base', methods=['POST', 'OPTIONS'])
def store_knowledge_base_enhanced():
    """Store knowledge base data with enhanced tracking"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        candidate_id = data.get('candidate_id')
        kb_id = data.get('knowledge_base_id')
        content = data.get('content', '')
        
        if not candidate_id or not kb_id:
            return jsonify({"error": "candidate_id and knowledge_base_id are required"}), 400
        
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            
            if not candidate:
                return jsonify({"error": "Candidate not found"}), 404
            
            # Update candidate with knowledge base information
            candidate.knowledge_base_id = kb_id
            candidate.interview_kb_id = kb_id  # Also store in interview-specific field
            
            # Store knowledge base content if we have the field
            if hasattr(candidate, 'interview_kb_content'):
                candidate.interview_kb_content = content
            
            # Store metadata
            if hasattr(candidate, 'interview_kb_metadata'):
                metadata = {
                    'created_at': data.get('created_at', datetime.now().isoformat()),
                    'content_length': len(content),
                    'kb_type': 'heygen' if not kb_id.startswith('kb_') else 'fallback',
                    'version': '1.0'
                }
                candidate.interview_kb_metadata = json.dumps(metadata)
            
            # Update timestamps
            candidate.interview_created_at = datetime.now()
            if not candidate.interview_expires_at:
                candidate.interview_expires_at = datetime.now() + timedelta(days=7)
            
            session.commit()
            
            logger.info(f"Knowledge base {kb_id} stored for candidate {candidate.name}")
            
            return jsonify({
                "success": True,
                "message": "Knowledge base stored successfully",
                "candidate_id": candidate_id,
                "knowledge_base_id": kb_id
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error storing knowledge base: {e}")
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/api/create-interview-knowledge-base', methods=['POST', 'OPTIONS'])
def create_interview_knowledge_base():
    """Create HeyGen knowledge base from candidate's resume and job description"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        candidate_id = data.get('candidate_id')
        
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            if not candidate:
                return jsonify({"error": "Candidate not found"}), 404
            
            # Extract resume content
            resume_content = ""
            if candidate.resume_path and os.path.exists(candidate.resume_path):
                resume_content = extract_resume_content(candidate.resume_path)
            
            # Get job description
            job_description = candidate.job_description or f"Position: {candidate.job_title}"
            
            # Create knowledge base content
            kb_content = f"""
            CANDIDATE INFORMATION:
            Name: {candidate.name}
            Email: {candidate.email}
            Position Applied: {candidate.job_title}
            
            RESUME CONTENT:
            {resume_content}
            
            JOB DESCRIPTION:
            {job_description}
            
            INTERVIEW INSTRUCTIONS:
            - Ask questions based on the candidate's experience mentioned in resume
            - Focus on skills required for {candidate.job_title}
            - Assess technical competence based on job requirements
            - Ask behavioral questions related to their past experiences
            """
            
            # Call HeyGen API to create knowledge base
            heygen_key = os.getenv('HEYGEN_API_KEY')
            if heygen_key:
                response = requests.post(
                    'https://api.heygen.com/v1/streaming/knowledge_base',
                    headers={
                        'X-Api-Key': heygen_key,
                        'Content-Type': 'application/json'
                    },
                    json={
                        'name': f"Interview_{candidate.name}_{candidate.job_title}",
                        'content': kb_content,
                        'custom_prompt': generate_custom_interview_prompt(candidate, resume_content, job_description)
                    }
                )
                
                if response.ok:
                    kb_data = response.json()
                    kb_id = kb_data['data']['knowledge_base_id']
                    
                    # Update candidate record
                    candidate.knowledge_base_id = kb_id
                    candidate.interview_kb_id = kb_id
                    session.commit()
                    
                    return jsonify({
                        "success": True,
                        "knowledge_base_id": kb_id
                    }), 200
            
            # Fallback if HeyGen unavailable
            fallback_kb_id = f"kb_{candidate_id}_{int(time.time())}"
            candidate.knowledge_base_id = fallback_kb_id
            session.commit()
            
            return jsonify({
                "success": True,
                "knowledge_base_id": fallback_kb_id,
                "fallback": True
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error creating knowledge base: {e}")
        return jsonify({"error": str(e)}), 500

@kb_bp.route('/api/fix-missing-knowledge-bases', methods=['POST'])
def fix_missing_knowledge_bases():
    """Fix all scheduled interviews that are missing knowledge bases"""
    session = SessionLocal()
    fixed_count = 0
    heygen_count = 0
    fallback_count = 0
    errors = []
    
    try:
        # Find all candidates with scheduled interviews but no KB
        candidates = session.query(Candidate).filter(
            Candidate.interview_scheduled == True,
            Candidate.interview_kb_id.is_(None)
        ).all()
        
        logger.info(f"Found {len(candidates)} candidates with missing knowledge bases")
        
        for candidate in candidates:
            try:
                # Extract resume content
                resume_content = ""
                if candidate.resume_path and os.path.exists(candidate.resume_path):
                    resume_content = extract_resume_content(candidate.resume_path)
                    logger.info(f"Extracted {len(resume_content)} chars from resume for {candidate.name}")
                
                # Try to create HeyGen KB
                kb_id = create_heygen_knowledge_base(
                    candidate_name=candidate.name,
                    position=candidate.job_title,
                    resume_content=resume_content,
                    company=os.getenv('COMPANY_NAME', 'Our Company')
                )
                
                if kb_id and not kb_id.startswith('kb_fallback'):
                    heygen_count += 1
                    logger.info(f"Created HeyGen KB for {candidate.name}: {kb_id}")
                else:
                    # Use fallback if HeyGen failed
                    kb_id = f"kb_fallback_{candidate.id}_{int(time.time())}"
                    fallback_count += 1
                    logger.warning(f"Using fallback KB for {candidate.name}")
                
                # Update candidate
                candidate.interview_kb_id = kb_id
                fixed_count += 1
                
            except Exception as e:
                error_msg = f"Failed to fix {candidate.name} (ID: {candidate.id}): {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
        
        # Commit all changes
        session.commit()
        
        # Clear cache
        cache.delete_memoized(get_cached_candidates)
        
        return jsonify({
            "success": True,
            "fixed_count": fixed_count,
            "heygen_created": heygen_count,
            "fallback_used": fallback_count,
            "total_found": len(candidates),
            "errors": errors,
            "message": f"Fixed {fixed_count} candidates ({heygen_count} HeyGen, {fallback_count} fallback)"
        }), 200
        
    except Exception as e:
        session.rollback()
        logger.error(f"Batch KB fix failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        session.close()

@kb_bp.route('/api/debug/heygen-test-fixed', methods=['GET'])
def debug_heygen_test_fixed():
    """Test HeyGen API with corrected field names"""
    heygen_key = os.getenv('HEYGEN_API_KEY')
    
    if not heygen_key:
        return jsonify({"error": "HEYGEN_API_KEY not found"}), 400
    
    # Test payload with CORRECT field names
    test_payload = {
        'name': f'Test_KB_{int(time.time())}',
        'opening': 'Hello, this is a test interview. Please tell me about yourself.',  # FIXED
        'prompt': 'Test interview questions: 1. Tell me about yourself. 2. Why this role? 3. What are your strengths?'
    }
    
    try:
        response = requests.post(
            "https://api.heygen.com/v1/streaming/knowledge_base/create",
            headers={
                'X-Api-Key': heygen_key,
                'Content-Type': 'application/json'
            },
            json=test_payload,
            timeout=30
        )
        
        if response.ok:
            data = response.json()
            kb_id = (
                data.get('data', {}).get('knowledge_base_id') or
                data.get('data', {}).get('id') or
                data.get('knowledge_base_id') or
                data.get('id')
            )
            
            return jsonify({
                "success": True,
                "status_code": response.status_code,
                "response": data,
                "knowledge_base_id": kb_id,
                "message": "HeyGen KB created successfully!"
            }), 200
        else:
            return jsonify({
                "success": False,
                "status_code": response.status_code,
                "error": response.text
            }), 400
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500