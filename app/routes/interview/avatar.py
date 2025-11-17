
from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import os, json, time, uuid, requests
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError
from app.models.db import Candidate, SessionLocal
from app.extensions import logger
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


avatar_bp = Blueprint('avatar', __name__)

@avatar_bp.route('/api/avatar/get-access-token', methods=['POST', 'OPTIONS'])
def get_avatar_access_token():
    """Generate HeyGen access token for avatar session"""
    if request.method == 'OPTIONS':
        return '', 200
    try:
        heygen_key = os.getenv('HEYGEN_API_KEY', 'your_heygen_api_key_here')
        return heygen_key, 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        logger.error(f"Error getting access token: {e}")
        return jsonify({"error": "Failed to get access token"}), 500

@avatar_bp.route('/api/avatar/interviews', methods=['POST','OPTIONS'], endpoint='save_interview_v2')
def save_interview_v2():
    """Create/refresh an interview token for a candidate and persist expiry."""
    if request.method == 'OPTIONS':
        resp = jsonify({})
        resp.status_code = 200
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return resp

    from sqlalchemy.exc import SQLAlchemyError # pyright: ignore[reportMissingImports]
    try:
        data = request.get_json(silent=True) or {}
        candidate_email = data.get('candidateEmail')
        incoming_kb_id = data.get('knowledgeBaseId')

        if not candidate_email:
            return jsonify({"error": "candidateEmail is required"}), 400

        interview_token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(email=candidate_email).first()
            if not candidate:
                return jsonify({"error": "Candidate not found"}), 404

            candidate.interview_token = interview_token
            candidate.interview_expires_at = expires_at
            if incoming_kb_id:
                # only overwrite if caller explicitly sends
                candidate.knowledge_base_id = incoming_kb_id

            session.commit()

            return jsonify({
                "token": interview_token,
                "expiresAt": expires_at.isoformat(),
                "knowledgeBaseId": getattr(candidate, "knowledge_base_id", None)
            }), 200

        except SQLAlchemyError:
            session.rollback()
            logger.exception("DB error saving interview")
            return jsonify({"error": "Database error saving interview"}), 500
        finally:
            session.close()

    except Exception:
        logger.exception("Error saving interview")
        return jsonify({"error": "Failed to save interview"}), 500

@avatar_bp.route('/api/avatar/interviews', methods=['POST','OPTIONS'])
def save_interview():
    if request.method == 'OPTIONS':
        return ('', 200)

    data = request.get_json(silent=True) or {}
    email = data.get('candidateEmail')
    if not email:
        return jsonify({"error":"candidateEmail is required"}), 400

    interview_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    s = SessionLocal()
    try:
        c = s.query(Candidate).filter_by(email=email).first()
        if not c:
            return jsonify({"error":"Candidate not found","email":email}), 404

        # Write fields (these must exist in your model/DB)
        c.interview_token = interview_token
        c.interview_expires_at = expires_at

        incoming_kb = data.get('knowledgeBaseId')
        if incoming_kb:
            c.knowledge_base_id = incoming_kb

        s.commit()
        return jsonify({
            "token": interview_token,
            "expiresAt": expires_at.isoformat(),
            "knowledgeBaseId": getattr(c,"knowledge_base_id",None),
            "candidateEmail": email
        }), 200

    except SQLAlchemyError as e:
        s.rollback()
        # TEMP: return the DB error so we can see it quickly
        return jsonify({"error":"db","details":str(e)}), 500
    except Exception as e:
        s.rollback()
        return jsonify({"error":"server","details":str(e)}), 500
    finally:
        s.close()

@avatar_bp.route('/api/avatar/interview/<token>', methods=['POST'])
def api_avatar_interview(token):
    """Handle avatar interview updates"""
    try:
        data = request.json
        action = data.get('action')
        
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(interview_token=token).first()
            
            if not candidate:
                return jsonify({"error": "Interview not found"}), 404
            
            if action == 'start':
                candidate.interview_started_at = datetime.now()
                message = "Interview started"
            elif action == 'complete':
                candidate.interview_completed_at = datetime.now()
                if data.get('transcript'):
                    candidate.interview_transcript = json.dumps(data['transcript'])
                message = "Interview completed"
            else:
                message = "Interview updated"
            
            session.commit()
            
            return jsonify({
                "success": True,
                "message": message
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error in avatar interview {token}: {e}")
        return jsonify({"error": str(e)}), 500

@avatar_bp.route('/api/v1/streaming_new', methods=['POST', 'OPTIONS'])
def streaming_new():
    """Proxy requests to HeyGen streaming API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        
        # Get HeyGen API key
        heygen_key = os.getenv('HEYGEN_API_KEY')
        if not heygen_key:
            return jsonify({"error": "HeyGen API key not configured"}), 500
        
        # Use correct HeyGen streaming endpoint
        heygen_streaming_url = "https://api.heygen.com/v1/streaming.new"
        
        headers = {
            'Content-Type': 'application/json',
            'X-Api-Key': heygen_key,
            'Accept': 'application/json'
        }
        
        print(f"Forwarding request to HeyGen: {heygen_streaming_url}")
        print(f"Request data: {data}")
        
        response = requests.post(
            heygen_streaming_url, 
            json=data, 
            headers=headers,
            timeout=30
        )
        
        print(f"HeyGen response status: {response.status_code}")
        
        if response.ok:
            response_data = response.json()
            return jsonify(response_data), response.status_code
        else:
            error_text = response.text
            print(f"HeyGen API error: {error_text}")
            return jsonify({
                "error": "HeyGen API error", 
                "details": error_text,
                "status": response.status_code
            }), response.status_code
            
    except requests.exceptions.Timeout:
        print("HeyGen API timeout")
        return jsonify({"error": "Request timeout"}), 504
    except requests.exceptions.ConnectionError:
        print("HeyGen API connection error")
        return jsonify({"error": "Connection error"}), 503
    except Exception as e:
        print(f"Streaming proxy error: {e}")
        return jsonify({"error": "Avatar service unavailable", "details": str(e)}), 500

@avatar_bp.route('/api/get-access-token', methods=['POST', 'OPTIONS'])
def get_access_token():
    """Get HeyGen streaming access token"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        heygen_key = os.getenv('HEYGEN_API_KEY')
        if not heygen_key:
            return jsonify({"error": "HeyGen API key not configured"}), 500
        
        # Call HeyGen token creation API
        response = requests.post(
            'https://api.heygen.com/v1/streaming.create_token',
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Api-Key': heygen_key,
            },
            timeout=10
        )
        
        if not response.ok:
            error_text = response.text
            print(f"HeyGen token error: {error_text}")
            return jsonify({"error": "Failed to get token", "details": error_text}), response.status_code
        
        data = response.json()
        if not data.get('data', {}).get('token'):
            return jsonify({"error": "No token in response"}), 500
        
        token = data['data']['token']
        print(f"Token obtained successfully")
        
        # Return as plain text
        return Response(token, mimetype='text/plain', status=200)
        
    except Exception as e:
        print(f"Token error: {e}")
        return jsonify({"error": str(e)}), 500

def create_heygen_knowledge_base(candidate_name, position, resume_content, company):
    """Create HeyGen knowledge base with correct field names"""
    
    heygen_key = os.getenv('HEYGEN_API_KEY')
    if not heygen_key:
        logger.error("HEYGEN_API_KEY not set!")
        return None
    
    # Extract skills for better questions
    skills = extract_skills_from_resume(resume_content) if resume_content else []
    
    # Create a more HeyGen-friendly prompt format
    heygen_prompt = f"""You are an AI interviewer conducting a professional technical interview.

IMPORTANT: You must ask these exact questions in order when conducting the interview.

Candidate: {candidate_name}
Position: {position}
Company: {company}

When the interview starts or when you hear "INIT_INTERVIEW", immediately greet the candidate and ask Question 1.

INTERVIEW QUESTIONS TO ASK IN ORDER:

Question 1: "Hello {candidate_name}, welcome to your interview for the {position} position at {company}. Let's begin. Could you please introduce yourself and tell me about your professional background?"

Question 2: {"I see from your resume that you have experience with " + skills[0] + ". Can you tell me about a specific project where you used this technology?" if skills else "Can you tell me about your most significant technical project and the technologies you used?"}

Question 3: "Can you describe a time when you encountered a complex technical problem and walk me through how you approached and solved it?"

Question 4: "Tell me about a time when you had to collaborate with team members on a challenging project. How did you handle any conflicts?"

Question 5: "What would you say is your strongest technical skill, and can you give me a detailed example of how you've applied it?"

Question 6: "Technology evolves rapidly. Can you tell me about a time when you had to quickly learn a new technology for a project?"

Question 7: "Based on your understanding of this {position} role, how do you see your skills contributing to our team?"

Question 8: "What do you think would be the biggest challenge for you in this role?"

Question 9: "Where do you see your career heading in the next 3-5 years?"

Question 10: "Do you have any questions for me about the role or {company}?"

INSTRUCTIONS:
- Ask ONE question at a time
- Wait for complete answers before proceeding
- Be professional and encouraging
- If the candidate seems stuck, offer to rephrase the question
- After the last question, thank them for their time"""
    
    # HeyGen payload with CORRECT field names
    payload = {
        "name": f"Interview_{candidate_name.replace(' ', '_')}_{int(time.time())}",
        "opening": f"Hello {candidate_name}, welcome to your interview for the {position} position at {company}. Let's begin. Could you please introduce yourself and tell me about your professional background?",
        "prompt": heygen_prompt
    }
    
    try:
        logger.info(f"Creating KB for {candidate_name} with payload keys: {payload.keys()}")
        
        response = requests.post(
            "https://api.heygen.com/v1/streaming/knowledge_base/create",
            headers={
                "X-Api-Key": heygen_key,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=45
        )
        
        logger.info(f"HeyGen response: {response.status_code}")
        
        if response.ok:
            data = response.json()
            logger.info(f"HeyGen success response: {json.dumps(data, indent=2)}")
            
            # Extract KB ID from response
            kb_id = None
            if isinstance(data, dict):
                kb_id = (
                    data.get('data', {}).get('knowledge_base_id') or
                    data.get('data', {}).get('id') or
                    data.get('knowledge_base_id') or
                    data.get('id')
                )
            
            if kb_id:
                logger.info(f"Successfully created HeyGen KB: {kb_id}")
                return kb_id
            else:
                logger.error(f"KB ID not found in response: {data}")
                
        else:
            error_text = response.text
            logger.error(f"HeyGen API error {response.status_code}: {error_text}")
            
    except Exception as e:
        logger.error(f"HeyGen API exception: {type(e).__name__}: {str(e)}")
    
    return None