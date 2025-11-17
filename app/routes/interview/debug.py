
from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import os, json, time, uuid, requests
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_
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


debug_bp = Blueprint('debug', __name__)

@debug_bp.route('/api/debug/check-token/<token>', methods=['GET'])
def debug_check_token(token):
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_token=token).first()
        
        if candidate:
            return jsonify({
                "found": True,
                "candidate_id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "interview_scheduled": candidate.interview_scheduled,
                "interview_token": candidate.interview_token
            }), 200
        else:
            # Try to find similar tokens
            similar = session.query(Candidate).filter(
                Candidate.interview_token.like(f'%{token[:8]}%')
            ).all()
            
            return jsonify({
                "found": False,
                "token_searched": token,
                "similar_tokens": [
                    {"id": c.id, "name": c.name, "token": c.interview_token}
                    for c in similar
                ]
            }), 404
    finally:
        session.close()

@debug_bp.route('/api/debug/kb/<token>', methods=['GET'])
def debug_kb(token):
    s = SessionLocal()
    try:
        c = s.query(Candidate).filter_by(interview_token=token).first()
        if not c:
            return jsonify({"error": "not found", "token": token}), 404
        return jsonify({
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "interview_token": c.interview_token,
            "knowledge_base_id": getattr(c, "knowledge_base_id", None),
            "interview_kb_id": getattr(c, "interview_kb_id", None),
        }), 200
    except Exception as e:
        logger.exception("debug_kb error")
        return jsonify({"error": str(e)}), 500
    finally:
        s.close()

@debug_bp.route('/api/debug/find-candidate', methods=['POST'])
def debug_find_candidate():
    from sqlalchemy.exc import SQLAlchemyError
    data = request.get_json(silent=True) or {}
    email = data.get('candidateEmail')
    if not email:
        return jsonify({"error": "candidateEmail required"}), 400
    s = SessionLocal()
    try:
        c = s.query(Candidate).filter_by(email=email).first()
        if not c:
            return jsonify({"found": False, "email": email}), 404
        return jsonify({
            "found": True,
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "has_interview_token": hasattr(c, "interview_token"),
            "has_interview_expires_at": hasattr(c, "interview_expires_at"),
            "has_knowledge_base_id": hasattr(c, "knowledge_base_id"),
            "current_interview_token": getattr(c, "interview_token", None),
            "current_kb": getattr(c, "knowledge_base_id", None)
        }), 200
    except SQLAlchemyError as e:
        return jsonify({"error": "db", "details": str(e)}), 500
    finally:
        s.close()

@debug_bp.route('/api/debug/avatar', methods=['GET'])
def debug_avatar():
    """Debug avatar configuration"""
    return jsonify({
        "heygen_key_configured": bool(os.getenv('HEYGEN_API_KEY')),
        "heygen_key_length": len(os.getenv('HEYGEN_API_KEY', '')),
        "cors_enabled": True,
        "endpoints": [
            "/api/get-access-token",
            "/api/v1/streaming_new",
            "/secure-interview/<token>"
        ]
    }), 200

@debug_bp.route('/api/debug/heygen-test-fixed', methods=['GET'])
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

@debug_bp.route('/api/debug/heygen-test', methods=['GET'])
def debug_heygen_test():
    """Test HeyGen API connection and knowledge base creation"""
    heygen_key = os.getenv('HEYGEN_API_KEY')
    
    # Check if API key exists
    if not heygen_key:
        return jsonify({
            "error": "HEYGEN_API_KEY not found in environment variables",
            "fix": "Add HEYGEN_API_KEY to your .env file"
        }), 400
    
    # Test payload
    test_payload = {
        'name': f'Test_KB_{int(time.time())}',
        'description': 'Test knowledge base creation',
        'content': 'Test interview questions: 1. Tell me about yourself. 2. Why this role?',
        'opening_line': 'Hello, this is a test interview.'
    }
    
    # Try different endpoints
    endpoints = [
        "https://api.heygen.com/v1/streaming/knowledge_base/create",
        "https://api.heygen.com/v1/streaming/knowledge_base",
        "https://api.heygen.com/v1/streaming_avatar/knowledge_base",
        "https://api.heygen.com/v1/knowledge_base"
    ]
    
    results = []
    
    for endpoint in endpoints:
        try:
            response = requests.post(
                endpoint,
                headers={
                    'X-Api-Key': heygen_key,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                json=test_payload,
                timeout=30
            )
            
            result = {
                "endpoint": endpoint,
                "status_code": response.status_code,
                "success": response.ok,
                "response": response.text[:500] if not response.ok else response.json()
            }
            results.append(result)
            
            if response.ok:
                # Try to extract KB ID
                data = response.json()
                kb_id = (
                    data.get('data', {}).get('knowledge_base_id') or
                    data.get('knowledge_base_id') or
                    data.get('id') or
                    data.get('data', {}).get('id')
                )
                if kb_id:
                    result["knowledge_base_id"] = kb_id
                    
        except Exception as e:
            results.append({
                "endpoint": endpoint,
                "error": str(e)
            })
    
    return jsonify({
        "api_key_length": len(heygen_key),
        "api_key_preview": f"{heygen_key[:10]}...{heygen_key[-5:]}",
        "test_results": results
    }), 200

@debug_bp.route('/api/debug/candidate-fields/<int:candidate_id>', methods=['GET'])
def debug_candidate_fields(candidate_id):
    """Debug endpoint to see what fields a candidate has"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Get all attributes
        fields = {}
        for key in dir(candidate):
            if not key.startswith('_') and not callable(getattr(candidate, key)):
                try:
                    value = getattr(candidate, key)
                    fields[key] = str(type(value).__name__)
                except:
                    fields[key] = "error reading"
        
        return jsonify({
            "candidate_id": candidate_id,
            "available_fields": fields,
            "has_knowledge_base_id": hasattr(candidate, 'knowledge_base_id'),
            "has_interview_kb_id": hasattr(candidate, 'interview_kb_id')
        }), 200
        
    finally:
        session.close()
