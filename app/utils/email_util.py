import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

logger = logging.getLogger(__name__)

class EmailConfig:
    """Email configuration class"""
    def __init__(self):
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.sender_email = os.getenv("SENDER_EMAIL")
        self.sender_password = os.getenv("SENDER_PASSWORD")
        self.company_name = os.getenv("COMPANY_NAME", "TalentFlow AI")
        
    def validate(self) -> bool:
        """Validate email configuration"""
        return bool(self.sender_email and self.sender_password)

def send_email(to_email: str, subject: str, body_html: str, body_text: Optional[str] = None) -> bool:
    """Generic email sending function"""
    config = EmailConfig()
    
    if not config.validate():
        logger.error("Email credentials not set in environment variables")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = config.sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add text and HTML parts
        if body_text:
            text_part = MIMEText(body_text, 'plain')
            msg.attach(text_part)
        
        html_part = MIMEText(body_html, 'html')
        msg.attach(html_part)
        
        # Send email
        with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
            server.starttls()
            server.login(config.sender_email, config.sender_password)
            server.send_message(msg)
        
        logger.info(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending email to {to_email}: {str(e)}")
        return False

def send_assessment_email(candidate) -> bool:
    """Send assessment link email to candidate"""
    try:
        config = EmailConfig()
        subject = f"Assessment Invitation - {candidate.job_title} Position"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #2563eb;">Assessment Invitation</h2>
                    
                    <p>Dear {candidate.name},</p>
                    
                    <p>Thank you for your interest in the <strong>{candidate.job_title}</strong> position. 
                    We're excited to move forward with your application!</p>
                    
                    <p>As the next step in our recruitment process, we'd like you to complete an online assessment 
                    that will help us better understand your technical skills and experience.</p>
                    
                    <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #1f2937;">Assessment Details:</h3>
                        <ul>
                            <li><strong>Position:</strong> {candidate.job_title}</li>
                            <li><strong>Duration:</strong> Approximately 60-90 minutes</li>
                            <li><strong>Deadline:</strong> 48 hours from receipt</li>
                            <li><strong>Format:</strong> Online technical assessment</li>
                        </ul>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{candidate.assessment_invite_link}" 
                           style="background-color: #2563eb; color: white; padding: 12px 24px; 
                                  text-decoration: none; border-radius: 6px; font-weight: bold;
                                  display: inline-block;">
                            Start Assessment
                        </a>
                    </div>
                    
                    <p><strong>Important Notes:</strong></p>
                    <ul>
                        <li>Please complete the assessment in one sitting</li>
                        <li>Ensure you have a stable internet connection</li>
                        <li>You'll have 48 hours to complete the assessment</li>
                        <li>Make sure to submit your answers before the deadline</li>
                    </ul>
                    
                    <p>If you have any technical issues or questions, please don't hesitate to reach out to us.</p>
                    
                    <p>Best of luck with your assessment!</p>
                    
                    <p>Best regards,<br>
                    {config.company_name}<br>
                    <a href="mailto:{config.sender_email}">{config.sender_email}</a></p>
                    
                    <hr style="margin-top: 30px; border: none; border-top: 1px solid #e5e7eb;">
                    <p style="font-size: 12px; color: #6b7280;">
                        This is an automated message. Please do not reply to this email.
                    </p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Dear {candidate.name},
        
        Thank you for your interest in the {candidate.job_title} position. We're excited to move forward with your application!
        
        As the next step, please complete our online assessment within 48 hours.
        
        Assessment Details:
        - Position: {candidate.job_title}
        - Duration: 60-90 minutes
        - Deadline: 48 hours from receipt
        - Link: {candidate.assessment_invite_link}
        
        Important Notes:
        - Complete in one sitting
        - Ensure stable internet connection
        - Submit before deadline
        
        Best regards,
        {config.company_name}
        """
        
        return send_email(candidate.email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send assessment email to {candidate.email}: {e}")
        return False

def send_assessment_reminder(candidate, hours_remaining: int = 24) -> bool:
    """Send reminder email for pending assessment"""
    try:
        config = EmailConfig()
        subject = f"Reminder: Assessment Due Soon - {candidate.job_title} Position"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #dc2626;">⏰ Assessment Reminder</h2>
                    
                    <p>Dear {candidate.name},</p>
                    
                    <p>This is a friendly reminder that your assessment for the <strong>{candidate.job_title}</strong> 
                    position is due soon.</p>
                    
                    <div style="background-color: #fef2f2; border-left: 4px solid #dc2626; padding: 15px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #dc2626;">Time Remaining</h3>
                        <p style="font-size: 18px; font-weight: bold; margin: 0;">
                            {hours_remaining} hours left to complete
                        </p>
                    </div>
                    
                    <p>If you haven't started yet, please begin as soon as possible. The assessment takes 
                    approximately 60-90 minutes to complete.</p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{candidate.assessment_invite_link}" 
                           style="background-color: #dc2626; color: white; padding: 12px 24px; 
                                  text-decoration: none; border-radius: 6px; font-weight: bold;
                                  display: inline-block;">
                            Complete Assessment Now
                        </a>
                    </div>
                    
                    <p>Please ensure you:</p>
                    <ul>
                        <li>Have a stable internet connection</li>
                        <li>Can complete the assessment in one sitting</li>
                        <li>Submit your answers before the deadline</li>
                    </ul>
                    
                    <p>If you're experiencing any technical difficulties, please contact us immediately.</p>
                    
                    <p>Best regards,<br>
                    {config.company_name}</p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Dear {candidate.name},
        
        Reminder: Your assessment for the {candidate.job_title} position is due soon.
        
        Time Remaining: {hours_remaining} hours
        
        Please complete your assessment as soon as possible.
        Assessment Link: {candidate.assessment_invite_link}
        
        Contact us immediately if you experience technical difficulties.
        
        Best regards,
        {config.company_name}
        """
        
        return send_email(candidate.email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send reminder email to {candidate.email}: {e}")
        return False

def send_interview_link_email(candidate=None, candidate_email=None, candidate_name=None, 
                             interview_link=None, interview_date=None, time_slot=None, 
                             position=None) -> Optional[str]:
    """Send interview scheduling link to candidate"""
    try:
        config = EmailConfig()
        
        # Support both calling methods
        if candidate:
            # Called with candidate object (legacy support)
            candidate_email = candidate.email
            candidate_name = candidate.name
            interview_link = candidate.interview_link
            interview_date = candidate.interview_date or datetime.now()
            position = candidate.job_title
            time_slot = getattr(candidate, 'interview_time_slot', 'TBD')
        else:
            # Called with individual parameters (new method)
            if not all([candidate_email, candidate_name, interview_link, position]):
                raise ValueError("Missing required parameters")
        
        # Format the interview date nicely
        if isinstance(interview_date, str):
            interview_date = datetime.fromisoformat(interview_date.replace('Z', '+00:00'))
        formatted_date = interview_date.strftime("%A, %B %d, %Y")
        
        subject = f"Your AI Interview Invitation - {position}"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #2563eb;">AI Interview Invitation</h2>
                    
                    <p>Dear {candidate_name},</p>
                    
                    <p>Congratulations! You have been selected for an AI-powered interview for the position of <strong>{position}</strong>.</p>
                    
                    <div style="background-color: #f0f9ff; border-left: 4px solid #2563eb; padding: 15px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #1e40af;">Interview Details:</h3>
                        <p><strong>Date:</strong> {formatted_date}<br>
                        <strong>Time:</strong> {time_slot or 'Flexible - Access anytime'}<br>
                        <strong>Format:</strong> AI-Powered Video Interview</p>
                    </div>
                    
                    <div style="background-color: #e0f2fe; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0;">
                        <p style="margin-bottom: 15px;"><strong>Click the button below to access your interview:</strong></p>
                        <a href="{interview_link}" style="display: inline-block; background-color: #2563eb; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">Start AI Interview</a>
                        <p style="margin-top: 15px; font-size: 12px; color: #666;">Or copy this link: {interview_link}</p>
                    </div>
                    
                    <h3 style="color: #1e40af;">Before Your Interview:</h3>
                    <ul>
                        <li>Ensure you have a stable internet connection</li>
                        <li>Use a device with a working camera and microphone</li>
                        <li>Find a quiet, well-lit environment</li>
                        <li>Have your resume ready for reference</li>
                        <li>Test your equipment before the scheduled time</li>
                    </ul>
                    
                    <p style="background-color: #fef3c7; padding: 10px; border-radius: 5px;">
                        <strong>Important:</strong> This interview link is unique to you and will expire after your scheduled interview time. Please do not share it with others.
                    </p>
                    
                    <p>If you have any questions or need to reschedule, please contact our HR team immediately.</p>
                    
                    <p>We look forward to speaking with you!</p>
                    
                    <p>Best regards,<br>
                    {config.company_name}<br>
                    HR Department</p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Dear {candidate_name},
        
        Congratulations! You have been selected for an AI-powered interview for the position of {position}.
        
        Interview Details:
        - Date: {formatted_date}
        - Time: {time_slot or 'Flexible - Access anytime'}
        - Format: AI-Powered Video Interview
        - Link: {interview_link}
        
        Before Your Interview:
        - Ensure you have a stable internet connection
        - Use a device with a working camera and microphone
        - Find a quiet, well-lit environment
        - Have your resume ready for reference
        - Test your equipment before the scheduled time
        
        Important: This interview link is unique to you. Please do not share it with others.
        
        We look forward to speaking with you!
        
        Best regards,
        {config.company_name}
        HR Department
        """
        
        success = send_email(candidate_email, subject, html_body, text_body)
        
        # Return the link if called with candidate object (legacy compatibility)
        if candidate and success:
            return interview_link
        
        # For new method, just return success status
        return success
        
    except Exception as e:
        logger.error(f"Failed to send interview invitation email: {e}")
        if candidate:
            return None  # Legacy compatibility
        raise  # New method raises exception
    
def send_interview_confirmation_email(candidate, interview_datetime: datetime, meeting_link: str) -> bool:
    """Send interview confirmation email"""
    try:
        config = EmailConfig()
        subject = f"Interview Confirmed - {candidate.job_title} Position"
        
        # Format date and time nicely
        interview_date = interview_datetime.strftime("%A, %B %d, %Y")
        interview_time = interview_datetime.strftime("%I:%M %p")
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #059669;">✅ Interview Confirmed</h2>
                    
                    <p>Dear {candidate.name},</p>
                    
                    <p>Great news! We're excited to confirm your interview for the <strong>{candidate.job_title}</strong> position.</p>
                    
                    <div style="background-color: #f0fdf4; border: 1px solid #059669; border-radius: 8px; padding: 20px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #059669;">Interview Details</h3>
                        <p><strong>Date:</strong> {interview_date}</p>
                        <p><strong>Time:</strong> {interview_time}</p>
                        <p><strong>Duration:</strong> 60 minutes</p>
                        <p><strong>Format:</strong> Video Conference</p>
                        <p><strong>Meeting Link:</strong> <a href="{meeting_link}" style="color: #059669; font-weight: bold;">{meeting_link}</a></p>
                    </div>
                    
                    <h3>Before the Interview</h3>
                    <ul>
                        <li>Test your camera and microphone</li>
                        <li>Ensure stable internet connection</li>
                        <li>Find a quiet, professional environment</li>
                        <li>Have your resume and portfolio ready</li>
                        <li>Prepare thoughtful questions about the role</li>
                    </ul>
                    
                    <h3>What We'll Cover</h3>
                    <ul>
                        <li>Your background and experience</li>
                        <li>Technical skills relevant to the role</li>
                        <li>Team culture and work environment</li>
                        <li>Your questions and next steps</li>
                    </ul>
                    
                    <p>If you need to reschedule for any reason, please contact us at least 24 hours in advance.</p>
                    
                    <p>We're looking forward to meeting you!</p>
                    
                    <p>Best regards,<br>
                    {config.company_name} Recruitment Team</p>
                    
                    <hr style="margin: 30px 0; border: none; border-top: 1px solid #e5e7eb;">
                    <p style="font-size: 12px; color: #6b7280;">
                        Add this interview to your calendar to receive reminders.
                    </p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Dear {candidate.name},
        
        Great news! We're excited to confirm your interview for the {candidate.job_title} position.
        
        Interview Details:
        - Date: {interview_date}
        - Time: {interview_time}
        - Duration: 60 minutes
        - Format: Video Conference
        - Meeting Link: {meeting_link}
        
        Before the Interview:
        - Test your camera and microphone
        - Ensure stable internet connection
        - Find a quiet, professional environment
        - Have your resume and portfolio ready
        - Prepare thoughtful questions about the role
        
        We're looking forward to meeting you!
        
        Best regards,
        {config.company_name} Recruitment Team
        """
        
        return send_email(candidate.email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send interview confirmation to {candidate.email}: {e}")
        return False

def send_rejection_email(candidate) -> bool:
    """Send rejection email to candidate"""
    try:
        config = EmailConfig()
        subject = f"Update on Your Application - {candidate.job_title} at {config.company_name}"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <p>Dear {candidate.name},</p>
                    
                    <p>Thank you for your interest in the <strong>{candidate.job_title}</strong> position at {config.company_name} and for taking the time to complete our assessment.</p>
                    
                    <p>After careful consideration, we have decided to move forward with other candidates whose qualifications more closely match our current needs.</p>
                    
                    <p>We were impressed by many aspects of your background, and we encourage you to apply for future positions that match your skills and experience. We will keep your resume on file for future opportunities.</p>
                    
                    <p>We appreciate your interest in {config.company_name} and wish you the best in your job search.</p>
                    
                    <p>Best regards,<br>
                    {config.company_name} Recruitment Team</p>
                    
                    <hr style="margin: 30px 0; border: none; border-top: 1px solid #e5e7eb;">
                    <p style="font-size: 12px; color: #6b7280;">
                        This is an automated message from {config.company_name}. While we cannot provide individual feedback due to the volume of applications, we appreciate your understanding.
                    </p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Dear {candidate.name},
        
        Thank you for your interest in the {candidate.job_title} position at {config.company_name} and for taking the time to complete our assessment.
        
        After careful consideration, we have decided to move forward with other candidates whose qualifications more closely match our current needs.
        
        We were impressed by many aspects of your background, and we encourage you to apply for future positions that match your skills and experience. We will keep your resume on file for future opportunities.
        
        We appreciate your interest in {config.company_name} and wish you the best in your job search.
        
        Best regards,
        {config.company_name} Recruitment Team
        """
        
        return send_email(candidate.email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send rejection email to {candidate.email}: {e}")
        return False

def send_welcome_email(candidate) -> bool:
    """Send welcome email to successful candidate"""
    try:
        config = EmailConfig()
        subject = f"Welcome to {config.company_name}! - Next Steps"
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #059669;">🎉 Welcome to the Team!</h2>
                    
                    <p>Dear {candidate.name},</p>
                    
                    <p>Congratulations! We're thrilled to offer you the <strong>{candidate.job_title}</strong> position at {config.company_name}.</p>
                    
                    <p>Your skills, experience, and enthusiasm made you stand out throughout our recruitment process, and we're excited to have you join our team.</p>
                    
                    <div style="background-color: #f0fdf4; border: 1px solid #059669; border-radius: 8px; padding: 20px; margin: 20px 0;">
                        <h3 style="margin-top: 0; color: #059669;">Next Steps</h3>
                        <ol>
                            <li>Our HR team will contact you within 2 business days with your offer letter</li>
                            <li>Please review all terms and conditions carefully</li>
                            <li>Complete any required background checks or documentation</li>
                            <li>We'll schedule your onboarding session once everything is finalized</li>
                        </ol>
                    </div>
                    
                    <p>If you have any questions in the meantime, please don't hesitate to reach out to us.</p>
                    
                    <p>Welcome aboard!</p>
                    
                    <p>Best regards,<br>
                    {config.company_name} Team</p>
                </div>
            </body>
        </html>
        """
        
        text_body = f"""
        Dear {candidate.name},
        
        Congratulations! We're thrilled to offer you the {candidate.job_title} position at {config.company_name}.
        
        Your skills, experience, and enthusiasm made you stand out throughout our recruitment process.
        
        Next Steps:
        1. Our HR team will contact you within 2 business days with your offer letter
        2. Please review all terms and conditions carefully
        3. Complete any required background checks or documentation
        4. We'll schedule your onboarding session once everything is finalized
        
        Welcome aboard!
        
        Best regards,
        {config.company_name} Team
        """
        
        return send_email(candidate.email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send welcome email to {candidate.email}: {e}")
        return False