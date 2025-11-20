
from functools import cache
from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import os, json, time, uuid, requests
from app.utils.email_util import send_interview_link_email
from app.services.interview_automation import start_interview_automation, stop_interview_automation
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_
from app.models.db import Candidate, SessionLocal
from app.routes.candidates import get_cached_candidates
from app.routes.interview.helpers import extract_resume_content
from app.routes.interview.helpers import extract_skills_from_resume
from app.extensions import logger
from app.services import assessment_automation_system
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


automation_bp = Blueprint('automation', __name__)

# @automation_bp.route('/api/interview-automation/status', methods=['GET', 'OPTIONS'])
# def get_automation_status():
#     """Get interview automation system status"""
#     if request.method == 'OPTIONS':
#         return '', 200
    
#     try:
#         from interview_automation import interview_automation
        
#         status = {
#             'is_running': interview_automation.is_running,
#             'check_interval_minutes': interview_automation.check_interval / 60,
#             'next_check': 'Running' if interview_automation.is_running else 'Stopped'
#         }
        
#         # Get statistics
#         session = SessionLocal()
#         try:
#             stats = {
#                 'candidates_pending_interview': session.query(Candidate).filter(
#                     and_(
#                         Candidate.exam_completed == True,
#                         Candidate.exam_percentage >= 70,
#                         Candidate.interview_scheduled == False
#                     )
#                 ).count(),
#                 'interviews_scheduled': session.query(Candidate).filter(
#                     Candidate.interview_scheduled == True
#                 ).count(),
#                 'interviews_completed': session.query(Candidate).filter(
#                     Candidate.interview_completed_at.isnot(None)
#                 ).count()
#             }
#             status['statistics'] = stats
#         finally:
#             session.close()
        
#         return jsonify(status), 200
        
#     except Exception as e:
#         logger.error(f"Error getting automation status: {e}")
#         return jsonify({"error": str(e)}), 500
@automation_bp.route('/api/assessment-automation/status', methods=['GET', 'OPTIONS'])
def get_assessment_automation_status():
    """Get assessment automation system status"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from app.services.assessment_automation_system import get_assessment_status
        status = get_assessment_status()
        
        return jsonify({
            'is_running': status['is_running'],
            'last_run': status['last_run'],
            'pass_threshold': status['pass_threshold'],
            'statistics': status['statistics'],
            'pending': status['pending'],
            'next_check': 'In 10 minutes' if status['is_running'] else 'Stopped'
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting assessment automation status: {e}")
        return jsonify({"error": str(e)}), 500

@automation_bp.route('/api/interview-automation/toggle', methods=['POST', 'OPTIONS'])
@rate_limit(max_calls=5, time_window=60)
def toggle_automation():
    """Start or stop the interview automation system"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        action = data.get('action', 'toggle')
        
        from interview_automation import interview_automation
        
        if action == 'start':
            start_interview_automation()
            message = "Interview automation started"
        elif action == 'stop':
            stop_interview_automation()
            message = "Interview automation stopped"
        else:
            # Toggle
            if interview_automation.is_running:
                stop_interview_automation()
                message = "Interview automation stopped"
            else:
                start_interview_automation()
                message = "Interview automation started"
        
        return jsonify({
            'success': True,
            'message': message,
            'is_running': interview_automation.is_running
        }), 200
        
    except Exception as e:
        logger.error(f"Error toggling automation: {e}")
        return jsonify({"error": str(e)}), 500

# 3. Fix the api_schedule_interview function to properly handle company_name
@automation_bp.route('/api/schedule-interview', methods=['POST', 'OPTIONS'])
@rate_limit(max_calls=10, time_window=60)
def api_schedule_interview():
    """Schedule interview with enhanced knowledge base creation for proactive questioning"""
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        data = request.json
        candidate_id = data.get('candidate_id')
        email = data.get('email')
        interview_date = data.get('date')
        time_slot = data.get('time_slot')
        job_description_override = data.get('job_description')
        
        logger.info(f"Schedule interview request: candidate_id={candidate_id}")
        
        if not candidate_id and not email:
            return jsonify({"success": False, "message": "candidate_id or email is required"}), 400
        
        session = SessionLocal()
        try:
            # Find candidate
            if candidate_id:
                candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            else:
                candidate = session.query(Candidate).filter_by(email=email).first()
            
            if not candidate:
                return jsonify({"success": False, "message": "Candidate not found"}), 404
            
            # Check if already scheduled
            if candidate.interview_scheduled and candidate.interview_token:
                existing_link = f"{request.host_url.rstrip('/')}/secure-interview/{candidate.interview_token}"
                return jsonify({
                    "success": True,
                    "message": "Interview already scheduled",
                    "interview_link": existing_link,
                    "knowledge_base_id": getattr(candidate, 'knowledge_base_id', None),
                    "already_scheduled": True
                }), 200
            
            # Extract resume content
            resume_content = ""
            resume_extracted = False
            
            if candidate.resume_path and os.path.exists(candidate.resume_path):
                logger.info(f"Extracting resume from: {candidate.resume_path}")
                resume_content = extract_resume_content(candidate.resume_path)
                if resume_content:
                    resume_extracted = True
                    logger.info(f"Resume extracted: {len(resume_content)} characters")
                else:
                    logger.error("Resume extraction returned empty content")
            
            # Fallback to candidate profile if no resume
            if not resume_content:
                logger.warning("Using candidate profile as fallback")
                resume_content = f"""
CANDIDATE: {candidate.name}
EMAIL: {candidate.email}
POSITION: {candidate.job_title}
ATS SCORE: {candidate.ats_score}
STATUS: {candidate.status}
{f"SCORING: {candidate.score_reasoning}" if candidate.score_reasoning else ""}
"""
            
            # Get company name
            company_name = os.getenv('COMPANY_NAME', 'Our Company')
            
            # Get job description
            job_description = job_description_override or getattr(candidate, 'job_description', f"Position: {candidate.job_title}")
            
            # CREATE HEYGEN KNOWLEDGE BASE WITH INTERVIEW QUESTIONS
            knowledge_base_id = None
            kb_creation_method = "none"
            
            if os.getenv('HEYGEN_API_KEY') and resume_content:
                try:
                    logger.info("Creating HeyGen knowledge base with interview questions...")
                    
                    # Generate structured interview questions
                    interview_questions = generate_interview_questions(
                        candidate_name=candidate.name,
                        position=candidate.job_title,
                        resume_content=resume_content,
                        job_description=job_description
                    )
                    
                    kb_name = f"Interview_{candidate.name.replace(' ', '_')}_{candidate.id}"
                    
                    # Create comprehensive knowledge base content
                    kb_content = f"""
INTERVIEW CONFIGURATION:
- Mode: Structured Technical Interview
- Candidate: {candidate.name}
- Position: {candidate.job_title}
- Company: {company_name}
- Interview Type: Technical and Behavioral
- Duration: 30-45 minutes

SPECIAL COMMANDS:
- When you receive "INIT_INTERVIEW": Start with the warm greeting and first question
- When you receive "NEXT_QUESTION": Move to the next question in the list
- If user is silent for 15+ seconds: Gently prompt or ask if they need more time


CANDIDATE BACKGROUND:
{resume_content[:8000]}

JOB REQUIREMENTS:
{job_description[:2000]}

{interview_questions}

INTERVIEW BEHAVIOR INSTRUCTIONS:
1. When stream starts, wait for "INIT_INTERVIEW" command
2. Upon receiving "INIT_INTERVIEW", immediately greet the candidate and ask the first question
3. Listen to complete answers before proceeding
4. Ask follow-up questions when appropriate
5. Keep track of which questions you've asked
6. Be encouraging if candidate seems nervous
7. End professionally after covering all questions

CONVERSATION STARTERS:
- If you receive any greeting like "Hello", "Hi", respond with: "Hello {candidate.name}! Welcome to your interview for {candidate.job_title} at {company_name}. I'm excited to learn about your experience. Let's start with you telling me about yourself and your journey to applying for this role."
- If candidate asks "Can you hear me?", respond: "Yes, I can hear you clearly! Let's begin with our interview. Please tell me about yourself."
- If candidate seems confused, say: "No worries! This is an AI-powered interview. I'll be asking you questions about your experience and the {candidate.job_title} role. Shall we start?"

IMPORTANT RULES:
- Start immediately when you receive "INIT_INTERVIEW"
- Always maintain a professional yet friendly tone
- Give candidates time to think (10-15 seconds)
- If no response after 20 seconds, ask: "Take your time, or would you like me to rephrase the question?"
- Track answered questions to avoid repetition
"""                    
                    # Prepare HeyGen payload with proper configuration
                    heygen_payload = {
                        'name': kb_name,
                        'description': f'Structured interview for {candidate.name} - {candidate.job_title}',
                        'content': kb_content,
                        'opening_line': f"Hello {candidate.name}, welcome to your interview for the {candidate.job_title} position at {company_name}. I'm your AI interviewer today. I've reviewed your resume and I'm excited to learn more about your experiences. Let's start with you telling me a bit about yourself and your journey to applying for this role.",
                        'custom_prompt': f"""You are conducting a professional technical interview for {candidate.name}. 
                        
Your personality: Professional, friendly, encouraging, and engaged.

Key behaviors:
1. Ask questions from the provided list ONE AT A TIME
2. Wait for complete answers before proceeding
3. Show active listening with phrases like "That's interesting", "I see", "Tell me more"
4. If they struggle, offer encouragement: "Take your time", "No worries"
5. Ask follow-up questions based on their responses
6. Keep track of which questions you've asked to avoid repetition

Interview style:
- Conversational, not robotic
- Professional but warm
- Encouraging when candidate seems nervous
- Patient with responses

Remember: This is a conversation, not an interrogation. Make {candidate.name} feel comfortable while thoroughly assessing their qualifications for the {candidate.job_title} role."""
                    }
                    
                    # Make API call to HeyGen
                    heygen_response = requests.post(
                        'https://api.heygen.com/v1/streaming/knowledge_base',
                        headers={
                            'X-Api-Key': os.getenv('HEYGEN_API_KEY'),
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        },
                        json=heygen_payload,
                        timeout=30
                    )
                    
                    if heygen_response.ok:
                        kb_data = heygen_response.json()
                        knowledge_base_id = kb_data.get('data', {}).get('knowledge_base_id')
                        kb_creation_method = "heygen_api"
                        logger.info(f"HeyGen KB created successfully: {knowledge_base_id}")
                    else:
                        error_text = heygen_response.text
                        logger.error(f"HeyGen API error: {heygen_response.status_code} - {error_text}")
                        
                except Exception as e:
                    logger.error(f"HeyGen KB creation failed: {e}", exc_info=True)
            
            # Fallback KB ID if HeyGen fails
            if not knowledge_base_id:
                knowledge_base_id = f"kb_{candidate.id}_{int(time.time())}"
                kb_creation_method = "fallback"
                logger.warning(f"Using fallback KB: {knowledge_base_id}")
            
            # Create interview session
            interview_token = str(uuid.uuid4())
            interview_session_id = f"session_{candidate.id}_{int(time.time())}"
            
            # Parse interview date
            if isinstance(interview_date, str):
                interview_datetime = datetime.fromisoformat(interview_date.replace('Z', '+00:00'))
            else:
                interview_datetime = datetime.now() + timedelta(days=3)
            
            # Update candidate record
            candidate.interview_scheduled = True
            candidate.interview_date = interview_datetime
            candidate.interview_token = interview_token
            candidate.interview_link = f"{request.host_url.rstrip('/')}/secure-interview/{interview_token}"
            candidate.final_status = 'Interview Scheduled'
            
            # Safe attribute setting for optional fields
            safe_attrs = {
                'interview_session_id': interview_session_id,
                'knowledge_base_id': knowledge_base_id,
                'interview_created_at': datetime.now(),
                'interview_expires_at': datetime.now() + timedelta(days=7),
                'company_name': company_name,
                'interview_time_slot': time_slot,
                'interview_questions_asked': '[]',
                'interview_answers_given': '[]',
                'interview_total_questions': 0,
                'interview_answered_questions': 0,
                'job_description': job_description if job_description_override else None
            }
            
            for attr, value in safe_attrs.items():
                if hasattr(candidate, attr):
                    setattr(candidate, attr, value)
            
            # Commit changes
            session.commit()
            
            # Send email
            email_sent = False
            try:
                send_interview_link_email(
                    candidate_email=candidate.email,
                    candidate_name=candidate.name,
                    interview_link=candidate.interview_link,
                    interview_date=interview_datetime,
                    time_slot=time_slot,
                    position=candidate.job_title
                )
                email_sent = True
                logger.info(f"Interview email sent to {candidate.email}")
            except Exception as e:
                logger.error(f"Email failed: {e}")
            
            # Clear caches
            cache.delete_memoized(get_cached_candidates)
            
            return jsonify({
                "success": True,
                "message": f"Interview scheduled for {candidate.name}",
                "interview_link": candidate.interview_link,
                "interview_date": interview_datetime.isoformat(),
                "knowledge_base_id": knowledge_base_id,
                "kb_creation_method": kb_creation_method,
                "resume_extracted": resume_extracted,
                "resume_content_length": len(resume_content),
                "email_sent": email_sent,
                "session_id": interview_session_id
            }), 200
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error in schedule_interview: {e}", exc_info=True)
            return jsonify({"success": False, "message": str(e)}), 500
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500

def generate_interview_questions(candidate_name, position, resume_content, job_description):
    """Generate structured interview questions based on resume and job"""
    
    # Extract key skills from resume
    skills = extract_skills_from_resume(resume_content)
    
    questions = f"""
INTERVIEW QUESTIONS:

1. INTRODUCTION (Ask first):
   - "Tell me about yourself and your journey to applying for this {position} role."
   - "What attracted you to our company and this position?"

2. TECHNICAL QUESTIONS (Based on resume):"""
    
    # Add technical questions based on skills found
    if 'python' in resume_content.lower():
        questions += """
   - "I see you have Python experience. Can you tell me about a complex Python project you've worked on?"
   - "How do you handle error handling and debugging in Python?"""
   
    if 'javascript' in resume_content.lower() or 'react' in resume_content.lower():
        questions += """
   - "Tell me about your experience with JavaScript/React. What was the most challenging frontend problem you've solved?"
   - "How do you manage state in React applications?"""
    
    if 'database' in resume_content.lower() or 'sql' in resume_content.lower():
        questions += """
   - "Describe your experience with databases. How do you optimize slow queries?"
   - "Tell me about a time you designed a database schema."""
    
    questions += f"""

3. BEHAVIORAL QUESTIONS:
   - "Describe a time when you had to work under pressure. How did you handle it?"
   - "Tell me about a project where you had to collaborate with a difficult team member."
   - "Give me an example of when you had to learn a new technology quickly."

4. ROLE-SPECIFIC QUESTIONS:
   - "How do you see yourself contributing to our team in the first 90 days?"
   - "What aspects of this {position} role excite you the most?"

5. CLOSING QUESTIONS:
   - "What questions do you have for me about the role or the company?"
   - "Is there anything else you'd like me to know about your qualifications?"

REMEMBER: Ask these questions one at a time, wait for complete responses, and ask relevant follow-up questions based on their answers.
"""
    
    return questions