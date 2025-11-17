from flask import Blueprint, request, jsonify, current_app
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
import secrets
import string
import jwt
import os
import json

# IMPORTANT: use the new model path
from app.models.db import SessionLocal, User  # your User model must exist in app/models/db.py

auth_bp = Blueprint("auth", __name__)

# JWT Configuration
JWT_SECRET = os.getenv("SECRET_KEY", "your-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DELTA = timedelta(days=7)

# In-memory storage for OTPs and reset tokens (single-process dev only)
otp_storage = {}
reset_token_storage = {}

def cleanup_expired_storage():
    """Clean up expired entries from storage"""
    current_time = datetime.utcnow()
    
    # Clean expired OTPs
    expired_otps = [email for email, data in otp_storage.items() 
                    if data['expires_at'] < current_time]
    for email in expired_otps:
        del otp_storage[email]
    
    # Clean expired reset tokens
    expired_tokens = [email for email, data in reset_token_storage.items() 
                      if data['expires_at'] < current_time]
    for email in expired_tokens:
        del reset_token_storage[email]

def store_otp(email, otp_data, expiry_seconds):
    """Store OTP in memory"""
    cleanup_expired_storage()  # Clean up old entries
    otp_storage[email] = {
        'data': otp_data,
        'expires_at': datetime.utcnow() + timedelta(seconds=expiry_seconds)
    }
    return True

def get_otp(email):
    """Get OTP from memory storage"""
    if email in otp_storage:
        stored = otp_storage[email]
        if datetime.utcnow() < stored['expires_at']:
            return stored['data']
        else:
            # Clean up expired OTP
            del otp_storage[email]
    return None

def delete_otp(email):
    """Delete OTP from memory storage"""
    if email in otp_storage:
        del otp_storage[email]
def store_reset_token(email, token, expiry_seconds):
    """Store reset token in memory"""
    cleanup_expired_storage()  # Clean up old entries
    reset_token_storage[email] = {
        'token': token,
        'expires_at': datetime.utcnow() + timedelta(seconds=expiry_seconds)
    }
    return True

def get_reset_token(email):
    """Get reset token from memory storage"""
    if email in reset_token_storage:
        stored = reset_token_storage[email]
        if datetime.utcnow() < stored['expires_at']:
            return stored['token']
        else:
            # Clean up expired token
            del reset_token_storage[email]
    return None

def delete_reset_token(email):
    """Delete reset token from memory storage"""
    if email in reset_token_storage:
        del reset_token_storage[email]
def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join(secrets.choice(string.digits) for _ in range(6))

def generate_token(user):
    payload = {
        "user_id": user.id,
        "email": user.email,
        "exp": datetime.utcnow() + JWT_EXPIRATION_DELTA,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(f):
    """Decorator to verify JWT token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'message': 'No token provided'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token.split(' ')[1]
            
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            request.user_id = payload['user_id']
            request.user_email = payload['email']
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    
    return decorated

def get_request_data():
    """
    Utility function to safely extract JSON data from request
    Handles multiple content types and parsing methods
    """
    data = {}
    
    # Try 1: Standard JSON parsing
    if request.is_json:
        try:
            data = request.get_json(force=True, silent=False)
            if data:
                return data
        except Exception as e:
            print(f"JSON parse attempt 1 failed: {e}")
    
    # Try 2: Force parse JSON regardless of content-type
    if request.data:
        try:
            data = json.loads(request.data.decode('utf-8'))
            if data:
                return data
        except Exception as e:
            print(f"JSON parse attempt 2 failed: {e}")
    
    # Try 3: Form data
    if request.form:
        data = request.form.to_dict()
        if data:
            return data
    
    # Try 4: Get JSON with silent=True
    try:
        data = request.get_json(silent=True) or {}
        if data:
            return data
    except Exception as e:
        print(f"JSON parse attempt 3 failed: {e}")
    
    return {}

@auth_bp.route('/api/register', methods=['POST'])
def register():
    """Register a new user"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['first_name', 'last_name', 'email', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'message': f'{field} is required'}), 400
        
        session = SessionLocal()
        try:
            # Check if user already exists
            existing_user = session.query(User).filter_by(email=data['email']).first()
            if existing_user:
                return jsonify({'message': 'An account with this email already exists.'}), 409
            
            # Create new user
            hashed_password = generate_password_hash(data['password'])
            new_user = User(
                first_name=data['first_name'],
                last_name=data['last_name'],
                email=data['email'],
                password_hash=hashed_password,
                created_at=datetime.utcnow(),
                is_active=True
            )
            
            session.add(new_user)
            session.commit()
            
            # Generate token
            token = generate_token(new_user)
            
            print(f"✅ New user registered: {new_user.email}")
            
            return jsonify({
                'token': token,
                'user': {
                    'id': new_user.id,
                    'firstName': new_user.first_name,
                    'lastName': new_user.last_name,
                    'email': new_user.email
                }
            }), 201
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ Registration error: {e}")
        return jsonify({'message': 'Registration failed. Please try again.'}), 500
    
@auth_bp.route('/api/login', methods=['POST'])
def login():
    """Login user"""
    try:
        data = request.json
        
        if not data.get('email') or not data.get('password'):
            return jsonify({'message': 'Email and password are required'}), 400
        
        session = SessionLocal()
        try:
            # Find user
            user = session.query(User).filter_by(email=data['email']).first()
            
            if not user:
                return jsonify({'message': 'Invalid email or password'}), 401
            
            # Check password
            if not check_password_hash(user.password_hash, data['password']):
                return jsonify({'message': 'Invalid email or password'}), 401
            
            # Check if user is active
            if not user.is_active:
                return jsonify({'message': 'Account is deactivated'}), 403
            
            # Generate token
            token = generate_token(user)
            
            # Update last login
            user.last_login = datetime.utcnow()
            session.commit()
            
            print(f"✅ User logged in: {user.email}")
            
            return jsonify({
                'token': token,
                'user': {
                    'id': user.id,
                    'firstName': user.first_name,
                    'lastName': user.last_name,
                    'email': user.email
                }
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ Login error: {e}")
        return jsonify({'message': 'Login failed. Please try again.'}), 500

@auth_bp.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    """Send OTP to user's email for password reset"""
    try:
        data = request.json
        email = data.get('email')
        resend = data.get('resend', False)  # Check if this is a resend request
        
        if not email:
            return jsonify({'message': 'Email is required'}), 400
        
        session = SessionLocal()
        try:
            # Check if user exists
            user = session.query(User).filter_by(email=email).first()
            
            if not user:
                # Don't reveal if email exists for security
                return jsonify({
                    'success': True,
                    'message': 'If an account exists with this email, you will receive an OTP'
                }), 200
            
            # Check if OTP already exists and is still valid (for resend)
            existing_otp = get_otp(email)
            if existing_otp and not resend:
                # OTP already sent and still valid
                return jsonify({
                    'success': True,
                    'message': 'OTP already sent. Please check your email or request a new one.'
                }), 200
            
            # Generate new OTP
            otp = generate_otp()
            
            # Store OTP in memory (10 minutes expiry)
            otp_data = {
                'otp': otp,
                'timestamp': datetime.utcnow().isoformat(),
                'attempts': 0,
                'resend_count': existing_otp['resend_count'] + 1 if existing_otp else 0
            }
            
            # Check resend limit
            if otp_data['resend_count'] > 5:
                return jsonify({
                    'message': 'Too many OTP requests. Please try again later.'
                }), 429
            
            expiry_minutes = int(os.getenv('OTP_EXPIRY_MINUTES', '10'))
            store_otp(email, otp_data, expiry_minutes * 60)
            
            # Try to send email with better error handling
            email_sent = False
            email_error_details = None
            
            try:
                send_otp_email(email, otp, user.first_name)
                email_sent = True
                print(f"✅ OTP email sent to {email}")
            except Exception as mail_error:
                email_error_details = str(mail_error)
                print(f"⚠️ Failed to send email to {email}: {mail_error}")
                print(f"📧 Email service error details: {email_error_details}")
            
            # ALWAYS show OTP in console for development/testing
            print(f"\n{'='*50}")
            print(f"🔑 OTP CODE FOR {email}: {otp}")
            print(f"📱 Use this code: {otp}")
            if not email_sent:
                print(f"⚠️ Email failed - Use the code above manually")
            print(f"{'='*50}\n")
            
            response_data = {
                'success': True,
                'message': 'OTP sent successfully! Check your email.' if email_sent else 'OTP generated. Check spam folder or use alternative method.'
            }
            
            # In development or if email fails, provide alternative
            if os.getenv('FLASK_ENV') == 'development' or not email_sent:
                response_data['fallback_enabled'] = True
                response_data['dev_message'] = 'Email service issue - Check console for OTP or contact support'
                # Optionally include OTP directly for testing
                if os.getenv('SHOW_OTP_IN_RESPONSE', 'false').lower() == 'true':
                    response_data['dev_otp'] = otp
            
            return jsonify(response_data), 200
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ Forgot password error: {e}")
        return jsonify({'message': 'An error occurred. Please try again.'}), 500

@auth_bp.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP for password reset"""
    try:
        data = request.json
        email = data.get('email')
        otp = data.get('otp')
        
        if not email or not otp:
            return jsonify({'message': 'Email and OTP are required'}), 400
        
        # Get OTP from memory storage
        stored_otp_data = get_otp(email)
        
        if not stored_otp_data:
            return jsonify({'message': 'OTP has expired. Please request a new one.'}), 400
        
        # Check attempts
        if stored_otp_data['attempts'] >= 3:
            delete_otp(email)
            return jsonify({'message': 'Too many failed attempts. Please request a new OTP.'}), 400
        
        # Verify OTP
        if stored_otp_data['otp'] != otp:
            # Increment attempts
            stored_otp_data['attempts'] += 1
            expiry_minutes = int(os.getenv('OTP_EXPIRY_MINUTES', '10'))
            store_otp(email, stored_otp_data, expiry_minutes * 60)
            
            remaining_attempts = 3 - stored_otp_data['attempts']
            print(f"⚠️ Invalid OTP attempt for {email}. {remaining_attempts} attempts remaining")
            
            return jsonify({
                'message': f'Invalid OTP. {remaining_attempts} attempts remaining.'
            }), 400
        
        # OTP is valid - generate reset token
        reset_token = secrets.token_urlsafe(32)
        
        # Store reset token (15 minutes expiry)
        store_reset_token(email, reset_token, 15 * 60)
        
        # Delete used OTP
        delete_otp(email)
        
        print(f"✅ OTP verified for {email}")
        
        return jsonify({
            'success': True,
            'reset_token': reset_token,
            'message': 'OTP verified successfully'
        }), 200
        
    except Exception as e:
        print(f"❌ Verify OTP error: {e}")
        return jsonify({'message': 'An error occurred. Please try again.'}), 500

@auth_bp.route('/api/reset-password', methods=['POST'])
def reset_password():
    """Reset user password"""
    try:
        data = request.json
        email = data.get('email')
        new_password = data.get('password')
        reset_token = data.get('reset_token')
        
        if not email or not new_password or not reset_token:
            return jsonify({'message': 'Email, password, and reset token are required'}), 400
        
        # Verify reset token
        stored_token = get_reset_token(email)
        
        if not stored_token or stored_token != reset_token:
            return jsonify({'message': 'Invalid or expired reset token'}), 400
        
        # Validate password
        if len(new_password) < 8:
            return jsonify({'message': 'Password must be at least 8 characters'}), 400
        
        session = SessionLocal()
        try:
            # Update user password
            user = session.query(User).filter_by(email=email).first()
            
            if not user:
                return jsonify({'message': 'User not found'}), 404
            
            user.password_hash = generate_password_hash(new_password)
            user.password_reset_at = datetime.utcnow()
            session.commit()
            
            # Delete used reset token
            delete_reset_token(email)
            
            print(f"✅ Password reset successfully for {email}")
            
            return jsonify({
                'success': True,
                'message': 'Password reset successfully'
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ Reset password error: {e}")
        return jsonify({'message': 'An error occurred. Please try again.'}), 500

@auth_bp.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "message": "Auth service is running",
        "storage": "in-memory",
        "active_otps": len(otp_storage),
        "active_reset_tokens": len(reset_token_storage),
    }), 200

@auth_bp.route("/api/test", methods=["GET", "POST"])
def test_endpoint():
    """Test endpoint to debug request handling"""
    return jsonify({
        "method": request.method,
        "content_type": request.content_type,
        "is_json": request.is_json,
        "has_data": bool(request.data),
        "has_form": bool(request.form),
        "headers": dict(request.headers),
        "data_preview": request.data.decode('utf-8')[:200] if request.data else None,
    }), 200

def send_otp_email(email, otp, first_name):
    """Use Flask-Mail config from current_app to send the OTP."""
    if not current_app.config.get("MAIL_SERVER"):
        raise Exception("Mail server not configured")

    mail = Mail(current_app)

    text_body = f"""Hello {first_name},

You requested to reset your password for TalentFlow AI.
Your OTP code is: {otp}
This code will expire in 10 minutes.

If you didn't request this, please ignore this email.

Best,
TalentFlow AI Team
"""

    html_body = f"""
<html>
  <body style="font-family: Arial, sans-serif;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
      <h2>Password Reset Request</h2>
      <p>Hello {first_name},</p>
      <p>You requested to reset your password for TalentFlow AI.</p>
      <div style="background:#f4f4f4;padding:20px;border-radius:5px;margin:20px 0;">
        <p style="margin:0;">Your OTP code is:</p>
        <h1 style="color:#007bff;letter-spacing:5px;margin:10px 0;">{otp}</h1>
      </div>
      <p>This code will expire in 10 minutes.</p>
      <p style="color:#666;font-size:14px;">
        If the OTP doesn't work or you didn't receive this email properly, 
        please check your spam folder or contact support.
      </p>
      <p>If you didn't request this, please ignore this email.</p>
      <hr style="border:none;border-top:1px solid #ddd;margin:30px 0;">
      <p style="color:#666;font-size:12px;">© 2024 TalentFlow AI. All rights reserved.</p>
    </div>
  </body>
</html>
"""

    msg = Message(
        subject="TalentFlow AI - Password Reset OTP",
        recipients=[email],
        body=text_body,
        html=html_body,
        sender=current_app.config.get("MAIL_DEFAULT_SENDER", current_app.config.get("MAIL_USERNAME")),
    )
    mail.send(msg)