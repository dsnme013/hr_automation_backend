import os
import re
import json
# import openai
import docx2txt
import PyPDF2
import smtplib
import logging
from langchain_openai import ChatOpenAI
import shutil
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import time
from dotenv import load_dotenv
from typing import Dict, List, Optional
from langchain_openai import ChatOpenAI
# === DB Imports (make sure your db.py has Candidate, SessionLocal) ===
from app.models.db import Candidate, SessionLocal
# LangChain, LangGraph imports
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END 
# from langgraph.graph import END
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field
from app.config_paths import RESUME_DIR, PROCESSED_RESUME_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='clint_recruitment.log',
    filemode='a'
)
logger = logging.getLogger('ClintRecruitment')

# -------------------------
# Paths
# -------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
RESUME_FOLDER = os.path.join(PROJECT_DIR, "resumes")
PROCESSED_FOLDER = os.path.join(PROJECT_DIR, "processed_resumes")
for folder in [RESUME_FOLDER, PROCESSED_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# -------------------------
# Environment
# -------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY not found in environment variables")
    raise ValueError("OPENAI_API_KEY not found in environment variables")

# -------------------------
# Utilities
# -------------------------
def get_llm(temperature=0, model="gpt-4o"):
    return ChatOpenAI(
        temperature=temperature,
        model=model,
        api_key=OPENAI_API_KEY
    )

def get_env_int(key, default):
    value = os.getenv(key, "")
    if value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default

# === DB utils ===
def get_all_candidates_from_db() -> list:
    session = SessionLocal()
    try:
        candidates = session.query(Candidate).all()
        data = [c.__dict__ for c in candidates]
        for d in data:
            d.pop('_sa_instance_state', None)
        return data
    finally:
        session.close()

def save_candidate_to_db(candidate_info: dict):
    """
    Upsert by email (if you also want to make it by (email,job_id) you can adjust this here).
    """
    session = SessionLocal()
    try:
        cand = session.query(Candidate).filter_by(email=candidate_info.get("email", "")).first()
        if 'id' in candidate_info:
            candidate_info.pop('id', None)
        if 'created_at' in candidate_info and not candidate_info['created_at']:
            candidate_info.pop('created_at', None)

        if not cand:
            cand = Candidate(**candidate_info)
            session.add(cand)
        else:
            for k, v in candidate_info.items():
                if k != 'id':
                    setattr(cand, k, v)
        logger.info("Committing candidate to DB")
        session.commit()
    except Exception as e:
        print(f"❌ DB error for {candidate_info.get('email')}: {str(e)}")
        logger.exception("DB error")
        session.rollback()
    finally:
        session.close()

def extract_text_from_resume(resume_path: str) -> str:
    try:
        if resume_path.lower().endswith('.pdf'):
            with open(resume_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    page_text = page.extract_text() or ""
                    text += page_text
                return text
        elif resume_path.lower().endswith('.docx'):
            return docx2txt.process(resume_path)
        elif resume_path.lower().endswith('.txt'):
            with open(resume_path, 'r', encoding='utf-8') as file:
                return file.read()
        else:
            logger.warning(f"Unsupported file format for {resume_path}")
            return ""
    except Exception as e:
        logger.error(f"Error extracting text from {resume_path}: {str(e)}")
        return ""

def send_email_notification(
    candidate_info: Dict,
    is_shortlisted: bool,
    resume_score: Optional[float] = None,
    feedback: Optional[str] = None
) -> bool:
    """
    Sends the email. Chooses the invite link from:
      testlify_link -> assessment_invite_link -> DEFAULT
    """
    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        sender_email = os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SENDER_PASSWORD")
        company_name = os.getenv("COMPANY_NAME", "Our Company")
        job_title = candidate_info.get("job_title", os.getenv("JOB_TITLE", "Open Position"))

        # the invite link may be Testlify or Criteria; both are just URLs here
        invite_link = (
            (candidate_info.get("testlify_link") or "").strip()
            or (candidate_info.get("assessment_invite_link") or "").strip()
            or "https://candidate.testlify.com/invite/DEFAULT"
        )

        if not sender_email or not sender_password:
            print("⚠️ Email credentials not set in environment variables")
            return False

        candidate_name = candidate_info.get("name", "Unknown Candidate")
        candidate_email = (candidate_info.get("email") or "").replace(" ", "")
        if not candidate_email or "@" not in candidate_email or "." not in candidate_email:
            print(f"⚠️ Invalid email format: {candidate_email}")
            return False

        print(f"✉️ Sending email to: {candidate_email}")
        greeting = f"Dear {candidate_name}" if candidate_name != "Unknown Candidate" else "Dear Candidate"
        score_str = f"{(resume_score or 0):.1f}"

        if is_shortlisted:
            subject = f"🎉 You've Been Shortlisted for {job_title} at {company_name}!"
            body = f"""{greeting},

We are thrilled to let you know that, after reviewing your application, you've been **shortlisted** for the {job_title} position at {company_name}!

**Next Steps:**
1) Please complete our assessment using this link:
   {invite_link}

**Your ATS Score:** {score_str}/100

{feedback or ""}

We're excited to move forward together!
Recruitment Team | {company_name}
"""
        else:
            subject = f"Your Application for {job_title} at {company_name}"
            body = f"""{greeting},

Thank you for applying for the {job_title} role at {company_name}.
After careful review, we've decided to move forward with other candidates at this time.

**Your ATS Score:** {score_str}/100

Here is some feedback to help with your future applications:
{feedback or ""}

Best regards,
Recruitment Team | {company_name}
"""

        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = sender_email
        msg['To'] = candidate_email
        msg['Subject'] = subject

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, candidate_email, msg.as_string())
        server.quit()
        print(f"✅ Email sent to {candidate_email}")
        return True

    except Exception as e:
        print(f"⚠️ Error sending email: {str(e)}")
        logger.exception("Email error")
        return False

# -------------------------
# Pydantic Models
# -------------------------
class CandidateInfo(BaseModel):
    name: str = Field(default="Unknown Candidate")
    email: str = Field(default="")
    linkedin: str = Field(default="")
    github: str = Field(default="")
    resume_path: str = Field(default="")
    processed_date: str = Field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    notification_sent: bool = Field(default=False)
    ats_score: float = Field(default=0.0)
    status: str = Field(default="")
    score_reasoning: str = Field(default="")
    decision_reason: str = Field(default="")
    job_title: str = Field(default="")
    testlify_link: str = Field(default="")          # storage for whichever provider link we use
    assessment_invite_link: str = Field(default="") # duplicate for DB/UI convenience

class JobRequirements(BaseModel):
    job_id: str = Field(default="")
    title: str = Field(default="")
    description: str = Field(default="")
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience_years: int = Field(default=0)

class RecruitmentState(BaseModel):
    candidate: CandidateInfo = Field(default_factory=CandidateInfo)
    job_requirements: JobRequirements = Field(default_factory=JobRequirements)
    resume_text: str = Field(default="")
    ats_threshold: float = Field(default=70.0)
    feedback: str = Field(default="")
    # IMPORTANT: must always be a string to avoid ValidationError
    testlify_link: str = Field(default="")

# -------------------------
# Agents
# -------------------------
def resume_parser(state: RecruitmentState) -> RecruitmentState:
    logger.info("Resume Parser Agent: Extracting candidate information...")
    print("📄 Resume Parser Agent: Extracting candidate information...")
    if not state.resume_text:
        raise ValueError("Resume text not provided in state")

    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert resume parser AI. Extract name, email, linkedin, github."),
        ("human", "Resume text: {resume_text}\n\nExtract info as JSON: name, email, linkedin, github.")
    ])
    parser = JsonOutputParser()
    parsing_chain = prompt | get_llm() | parser

    try:
        result = parsing_chain.invoke({"resume_text": state.resume_text[:4000]})
        extracted_email = (result.get("email") or "").replace(" ", "").strip().lower()
        state.candidate.name = result.get("name", "Unknown Candidate")
        state.candidate.email = extracted_email
        state.candidate.linkedin = result.get("linkedin", "")
        state.candidate.github = result.get("github", "")
        state.candidate.job_title = state.job_requirements.title
        # propagate the invite link to the candidate fields (works for either provider)
        state.candidate.testlify_link = state.testlify_link or ""
        state.candidate.assessment_invite_link = state.testlify_link or ""
        return state
    except Exception as e:
        logger.error(f"Error in resume parser agent: {str(e)}")
        print(f"❌ Error in resume parser: {str(e)}")
        return state

def ats_scorer(state: RecruitmentState) -> RecruitmentState:
    """Dynamic ATS scorer with automatic job requirements handling"""
    logger.info("ATS Scorer Agent: Calculating ATS score...")
    print("🔍 ATS Scorer Agent: Calculating ATS score...")

    print(f"ATS Scorer DEBUG - Job ID: {state.job_requirements.job_id}")
    print(f"ATS Scorer DEBUG - Job Title: {state.job_requirements.title}")
    print(f"ATS Scorer DEBUG - Job Desc: {state.job_requirements.description}")
    print(f"ATS Scorer DEBUG - Required Skills: {state.job_requirements.required_skills}")

    if not state.job_requirements.required_skills:
        print("⚠️ No job requirements found, creating them automatically...")
        if state.job_requirements.description and state.job_requirements.title:
            try:
                prompt = ChatPromptTemplate.from_messages([
                    ("system", """You are an expert job requirements analyzer. Extract required and preferred skills from the job description.
Return JSON with 'required_skills' (4-6 items) and 'preferred_skills' (3-5 items)."""),
                    ("human", "Job Title: {title}\nJob Description: {desc}")
                ])
                parser = JsonOutputParser()
                skill_chain = prompt | get_llm() | parser
                skills_result = skill_chain.invoke({
                    "title": state.job_requirements.title,
                    "desc": state.job_requirements.description
                })
                state.job_requirements.required_skills = skills_result.get("required_skills", [])[:6]
                state.job_requirements.preferred_skills = skills_result.get("preferred_skills", [])[:5]
                print(f"✅ Extracted {len(state.job_requirements.required_skills)} required skills from job description")
            except Exception as e:
                print(f"⚠️ Could not extract skills from description: {e}")

        if not state.job_requirements.required_skills:
            print("📋 Using default skills based on job title...")
            job_title_lower = (state.job_requirements.title or "").lower()
            if any(k in job_title_lower for k in ["ai", "machine learning", "ml"]):
                state.job_requirements.required_skills = ['Python', 'Machine Learning', 'Data Science', 'TensorFlow/PyTorch', 'Statistics']
                state.job_requirements.preferred_skills = ['Deep Learning', 'NLP', 'Computer Vision', 'MLOps', 'Cloud Platforms']
            elif "data scientist" in job_title_lower:
                state.job_requirements.required_skills = ['Python', 'Statistics', 'Machine Learning', 'SQL', 'Data Analysis']
                state.job_requirements.preferred_skills = ['R', 'Tableau', 'Big Data', 'Spark', 'Deep Learning']
            elif "backend" in job_title_lower:
                state.job_requirements.required_skills = ['Python/Java/Node.js', 'REST APIs', 'Databases', 'Cloud Services', 'Git']
                state.job_requirements.preferred_skills = ['Docker', 'Kubernetes', 'Microservices', 'CI/CD', 'GraphQL']
            elif "frontend" in job_title_lower:
                state.job_requirements.required_skills = ['JavaScript', 'React/Vue/Angular', 'HTML/CSS', 'Responsive Design', 'Git']
                state.job_requirements.preferred_skills = ['TypeScript', 'Testing', 'Performance Optimization', 'State Management', 'Build Tools']
            elif "full stack" in job_title_lower:
                state.job_requirements.required_skills = ['JavaScript', 'Python/Node.js', 'Databases', 'React/Vue', 'APIs']
                state.job_requirements.preferred_skills = ['Cloud Platforms', 'Docker', 'TypeScript', 'DevOps', 'Testing']
            else:
                state.job_requirements.required_skills = ['Programming', 'Problem Solving', 'Software Development', 'Version Control', 'Team Collaboration']
                state.job_requirements.preferred_skills = ['Agile/Scrum', 'Cloud Technologies', 'Testing', 'Documentation', 'Communication']

            if not state.job_requirements.experience_years:
                state.job_requirements.experience_years = 2 if "junior" in job_title_lower else 3
            print(f"✅ Set default requirements for '{state.job_requirements.title or 'Technical Position'}'")

    if not state.job_requirements.required_skills:
        print("⚠️ Fallback: Setting generic required skills to avoid ValueError.")
        state.job_requirements.required_skills = ['Programming', 'Problem Solving', 'Software Development']
        state.job_requirements.preferred_skills = ['Communication']
        if not state.job_requirements.experience_years:
            state.job_requirements.experience_years = 2

    required_skills = ", ".join(state.job_requirements.required_skills)
    preferred_skills = ", ".join(state.job_requirements.preferred_skills)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert ATS (Applicant Tracking System) AI. Score the resume 0-100 based on match to job requirements.
Return JSON: score, reasoning, matched_skills, missing_skills"""),
        ("human", """Resume text: {resume_text}

Job requirements:
Title: {title}
Description: {description}
Required skills: {required_skills}
Preferred skills: {preferred_skills}
Experience years: {experience_years}

Analyze and score this resume.""")
    ])
    parser = JsonOutputParser()
    scoring_chain = prompt | get_llm() | parser

    try:
        result = scoring_chain.invoke({
            "resume_text": state.resume_text[:4000],
            "title": state.job_requirements.title or "Technical Position",
            "description": state.job_requirements.description or f"Position for {state.job_requirements.title}",
            "required_skills": required_skills,
            "preferred_skills": preferred_skills,
            "experience_years": state.job_requirements.experience_years or 0
        })

        score = result.get("score", 50)
        try:
            score = float(score)
        except (ValueError, TypeError):
            score = 50

        score = max(0, min(100, score))
        state.candidate.ats_score = score
        state.candidate.score_reasoning = result.get("reasoning", "No reasoning provided")

        if "matched_skills" in result:
            state.candidate.score_reasoning += f"\n\nMatched skills: {', '.join(result['matched_skills'])}"
        if "missing_skills" in result:
            state.candidate.score_reasoning += f"\nMissing skills: {', '.join(result['missing_skills'])}"

        print(f"✅ Calculated ATS score: {score}")
        return state

    except Exception as e:
        logger.error(f"Error in ATS scorer agent: {str(e)}")
        print(f"❌ Error in ATS scorer: {str(e)}")
        state.candidate.ats_score = 50
        state.candidate.score_reasoning = f"Error occurred during scoring: {str(e)}"
        return state

def decision_maker(state: RecruitmentState) -> RecruitmentState:
    logger.info(f"Decision Maker Agent: Determining status for score {state.candidate.ats_score}")
    print("⚖️ Decision Maker Agent: Determining candidate status...")
    if state.candidate.ats_score >= state.ats_threshold:
        state.candidate.status = "Shortlisted"
        state.candidate.decision_reason = f"Score {state.candidate.ats_score} >= threshold {state.ats_threshold}."
    else:
        state.candidate.status = "Rejected"
        state.candidate.decision_reason = f"Score {state.candidate.ats_score} < threshold {state.ats_threshold}."
    print(f"✅ Decision for {state.candidate.name}: {state.candidate.status}")
    return state

def feedback_generator(state: RecruitmentState) -> RecruitmentState:
    logger.info("Feedback Generator Agent: Creating personalized feedback...")
    print("💬 Feedback Generator Agent: Creating personalized feedback...")

    if state.candidate.status == "Shortlisted":
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Give positive feedback (3-5 sentences) for a shortlisted candidate. Include 1-2 minor improvement tips."),
            ("human", "ATS score: {ats_score}/100.\nResume content: {resume_text}\nScore reasoning: {score_reasoning}")
        ])
    else:
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Give actionable feedback for a rejected candidate (3-5 sentences). Include 2-3 concrete improvements."),
            ("human", "ATS score: {ats_score}/100.\nResume content: {resume_text}\nScore reasoning: {score_reasoning}")
        ])

    feedback_chain = prompt | get_llm()
    try:
        raw = feedback_chain.invoke({
            "ats_score": state.candidate.ats_score,
            "resume_text": state.resume_text[:3000],
            "score_reasoning": state.candidate.score_reasoning
        })
        state.feedback = raw.content if isinstance(raw, AIMessage) else str(raw)
        return state
    except Exception as e:
        logger.error(f"Error in feedback generator agent: {str(e)}")
        print(f"❌ Error in feedback generator: {str(e)}")
        state.feedback = "Feedback could not be generated due to an error."
        return state

def email_notifier(state: RecruitmentState) -> RecruitmentState:
    logger.info("Email Notification Agent: Sending email to candidate...")
    print("✉️ Email Notification Agent: Sending email to candidate...")

    if not state.candidate.email:
        logger.warning("No email available for notification")
        print("⚠️ No email available for notification")
        return state

    # Build info for the emailer. testlify_link field holds whichever provider's link we passed in.
    candidate_info = {
        "name": state.candidate.name,
        "email": state.candidate.email,
        "job_title": state.job_requirements.title,
        "testlify_link": state.testlify_link or "",
        "assessment_invite_link": state.testlify_link or ""
    }

    success = send_email_notification(
        candidate_info=candidate_info,
        is_shortlisted=(state.candidate.status == "Shortlisted"),
        resume_score=state.candidate.ats_score,
        feedback=state.feedback
    )

    if success:
        state.candidate.notification_sent = True
        logger.info(f"Email sent to {state.candidate.email}")
        print(f"✅ Email sent to {state.candidate.email}")
    else:
        logger.warning(f"Failed to send email to {state.candidate.email}")
        print(f"⚠️ Failed to send email to {state.candidate.email}")
    return state

# -------------------------
# Orchestrator
# -------------------------
class ClintRecruitmentSystem:
    def __init__(self, testlify_link: Optional[str] = None):
        self.candidates = []
        self.ats_threshold = float(os.getenv("ATS_THRESHOLD", "70"))
        self.max_workers = get_env_int("MAX_WORKERS", 4)
        # make sure it's always a string
        self.testlify_link = (testlify_link or "")
        self.job_requirements = JobRequirements()
        self._build_workflow()
        logger.info("ClintRecruitmentSystem initialized")
        print("🤖 Clint Recruitment System initialized with LangGraph (DB Mode)")

    def _build_workflow(self):
        self.workflow = StateGraph(RecruitmentState)
        self.workflow.add_node("resume_parser", resume_parser)
        self.workflow.add_node("ats_scorer", ats_scorer)
        self.workflow.add_node("decision_maker", decision_maker)
        self.workflow.add_node("feedback_generator", feedback_generator)
        self.workflow.add_node("email_notifier", email_notifier)
        self.workflow.add_edge("resume_parser", "ats_scorer")
        self.workflow.add_edge("ats_scorer", "decision_maker")
        self.workflow.add_edge("decision_maker", "feedback_generator")
        self.workflow.add_edge("feedback_generator", "email_notifier")
        self.workflow.add_edge("email_notifier", END)
        self.workflow.set_entry_point("resume_parser")
        self.graph = self.workflow.compile(checkpointer=None)

    def set_job_requirements(
        self,
        job_id: Optional[str] = "",
        job_title: Optional[str] = "",
        job_description: Optional[str] = "",
        required_skills: Optional[List[str]] = None,
        preferred_skills: Optional[List[str]] = None,
        experience_years: int = 0,
        **kwargs
    ):
        """
        Backward-compatible: supports both
        - set_job_requirements(job_id, job_title, job_description, required_skills, preferred_skills, experience_years)
        - set_job_requirements(job_description=..., required_skills=..., preferred_skills=..., experience_years=...)
        """
        required_skills = required_skills or []
        preferred_skills = preferred_skills or []
        self.job_requirements = JobRequirements(
            job_id=str(job_id or ""),
            title=job_title or (kwargs.get("title") or ""),
            description=job_description or "",
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            experience_years=experience_years
        )
        print(f"📋 Job requirements set with {len(required_skills)} required skills")

    def set_ats_threshold(self, threshold):
        if 0 <= threshold <= 100:
            self.ats_threshold = threshold
            print(f"🎯 ATS threshold set to {threshold}")
        else:
            print(f"⚠️ Invalid threshold value: {threshold}")

    def process_resume(self, resume_path):
        try:
            if not os.path.exists(resume_path):
                print(f"⚠️ Resume file not found: {resume_path}")
                return False

            resume_filename = os.path.basename(resume_path)
            for candidate in self.candidates:
                if os.path.basename(candidate.get('resume_path', '')) == resume_filename:
                    print(f"⚠️ Resume {resume_filename} already processed, skipping...")
                    return False

            print(f"📄 Processing resume: {resume_path}")
            resume_text = extract_text_from_resume(resume_path)
            if not resume_text:
                print(f"⚠️ Could not extract text from {resume_path}")
                return False

            initial_state = RecruitmentState(
                resume_text=resume_text,
                job_requirements=self.job_requirements,
                ats_threshold=self.ats_threshold,
                testlify_link=self.testlify_link or ""  # ensure string
            )

            raw_state = self.graph.invoke(initial_state)
            result_state = raw_state if isinstance(raw_state, RecruitmentState) else RecruitmentState(**raw_state)

            candidate_info = result_state.candidate.model_dump()
            candidate_info["resume_path"] = resume_path

            # extra assessment meta
            attendance_deadline = datetime.now() + timedelta(hours=24)
            candidate_info["attendance_deadline"] = attendance_deadline.isoformat()
            candidate_info["attended_assessment"] = False
            candidate_info["attended_at"] = None
            candidate_info["exam_expired"] = False

            # coerce any dict fields
            for field in ["score_reasoning", "decision_reason"]:
                if isinstance(candidate_info.get(field), dict):
                    candidate_info[field] = json.dumps(candidate_info[field])

            save_candidate_to_db(candidate_info)
            self.candidates = get_all_candidates_from_db()

            # move resume
            try:
                filename = os.path.basename(resume_path)
                destination = os.path.join(PROCESSED_FOLDER, filename)
                if os.path.exists(destination):
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    name, ext = os.path.splitext(filename)
                    destination = os.path.join(PROCESSED_FOLDER, f"{name}_{timestamp}{ext}")
                shutil.copy2(resume_path, destination)
                os.remove(resume_path)
                for candidate in self.candidates:
                    if candidate.get('resume_path') == resume_path:
                        candidate['resume_path'] = destination
                        save_candidate_to_db(candidate)
                print(f"📁 Moved resume to: {destination}")
            except Exception as e:
                print(f"⚠️ Could not move resume file: {str(e)}")

            print(f"✅ Resume processing complete: {resume_path}")
            return True

        except Exception as e:
            logger.exception("process_resume error")
            print(f"❌ Error processing resume: {str(e)}")
            return False

    def process_all_resumes(self, resume_folder=RESUME_FOLDER, use_threads=True):
        if not os.path.exists(resume_folder):
            print(f"⚠️ Folder not found: {resume_folder}")
            return 0

        resume_files = [
            os.path.join(resume_folder, f)
            for f in os.listdir(resume_folder)
            if f.lower().endswith(('.pdf', '.docx', '.txt'))
        ]
        if not resume_files:
            print(f"⚠️ No resume files found in {resume_folder}")
            return 0

        num_files = len(resume_files)
        print(f"🔍 Found {num_files} resume files to process")
        start_time = time.time()
        processed_count = 0

        if use_threads and num_files > 1:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, num_files)) as executor:
                results = list(executor.map(self.process_resume, resume_files))
                processed_count = sum(1 for result in results if result)
        else:
            for resume_file in resume_files:
                if self.process_resume(resume_file):
                    processed_count += 1

        elapsed_time = time.time() - start_time
        print(f"🎉 Processed {processed_count} out of {num_files} resumes in {elapsed_time:.2f} seconds")
        return processed_count

    def get_candidates(self, status=None):
        if status:
            return [c for c in self.candidates if c.get("status") == status]
        return self.candidates

    def display_results(self):
        shortlisted = self.get_candidates(status="Shortlisted")
        rejected = self.get_candidates(status="Rejected")
        print("\n📊 RECRUITMENT RESULTS 📊")
        print("=" * 50)
        print(f"\n✅ Shortlisted candidates ({len(shortlisted)}):")
        for candidate in shortlisted:
            print(f"  • {candidate.get('name', 'Unknown')} (Score: {candidate.get('ats_score', 0)})")
            print(f"    Email: {candidate.get('email', 'N/A')}")
            if candidate.get('linkedin'):
                print(f"    LinkedIn: {candidate.get('linkedin')}")
            if candidate.get('github'):
                print(f"    GitHub: {candidate.get('github')}")
            print()
        print(f"\n❌ Rejected candidates ({len(rejected)}):")
        for candidate in rejected:
            print(f"  • {candidate.get('name', 'Unknown')} (Score: {candidate.get('ats_score', 0)})")
        print("\n" + "=" * 50)

    def retry_failed_notifications(self):
        retry_count = 0
        for candidate in self.candidates:
            if candidate.get('email') and not candidate.get('notification_sent', False):
                is_shortlisted = (candidate.get('status') == "Shortlisted")
                ats_score = candidate.get('ats_score')

                state = RecruitmentState(
                    resume_text=extract_text_from_resume(candidate.get('resume_path', '')),
                    ats_threshold=self.ats_threshold,
                    job_requirements=self.job_requirements,
                    testlify_link=self.testlify_link or ""
                )
                state.candidate.name = candidate.get('name', 'Unknown Candidate')
                state.candidate.email = candidate.get('email', '')
                state.candidate.ats_score = ats_score
                state.candidate.status = candidate.get('status', '')
                state.candidate.score_reasoning = candidate.get('score_reasoning', '')

                updated_state = feedback_generator(state)

                info = {
                    "name": candidate.get("name", ""),
                    "email": candidate.get("email", ""),
                    "job_title": self.job_requirements.title,
                    "testlify_link": (candidate.get("assessment_invite_link") or self.testlify_link or "")
                }
                success = send_email_notification(
                    info,
                    is_shortlisted,
                    ats_score,
                    updated_state.feedback
                )
                if success:
                    candidate['notification_sent'] = True
                    save_candidate_to_db(candidate)
                    retry_count += 1

        if retry_count > 0:
            print(f"✅ Successfully resent {retry_count} notifications")
        return retry_count

# -------------------------
# CLI main (optional)
# -------------------------
def main():
    try:
        print("🚀 [MAIN] clint_recruitment_system.main() has started")
        recruitment_system = ClintRecruitmentSystem()

        job_description = os.getenv("JOB_DESCRIPTION", "Python developer with experience in machine learning and data analysis.")
        required_skills = os.getenv("REQUIRED_SKILLS", "Python,Machine Learning,Data Analysis").split(',')
        preferred_skills = os.getenv("PREFERRED_SKILLS", "TensorFlow,PyTorch,scikit-learn,pandas").split(',')
        experience_years = int(os.getenv("EXPERIENCE_YEARS", "2"))

        # Backward-compatible setter
        recruitment_system.set_job_requirements(
            job_description=job_description,
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            experience_years=experience_years
        )

        ats_threshold = float(os.getenv("ATS_THRESHOLD", "75"))
        recruitment_system.set_ats_threshold(ats_threshold)

        use_threads = os.getenv("USE_THREADS", "True").lower() == "true"
        processed_count = recruitment_system.process_all_resumes(use_threads=use_threads)

        recruitment_system.retry_failed_notifications()

        if processed_count > 0:
            recruitment_system.display_results()
        else:
            print("\n⚠️ No new resumes were processed. Please add resume files to the 'resumes' folder.")

        print("\n✅ Recruitment processing complete")
    except Exception as e:
        logger.exception("❌ Error in main function")
        print(f"❌ Error: {str(e)}")

# -------------------------
# Entry point helpers
# -------------------------
def run_recruitment_with_invite_link(job_id, job_title, job_desc, invite_link):
    """
    Process all resumes for a given job and email candidates.
    `invite_link` may be a Testlify link or a Criteria link.
    """
    print(f"🤖 Starting AI-powered recruitment screening for job_id={job_id}, title={job_title}")
    print(f"📧 Using invite link: {invite_link}")

    if not invite_link or "MANUAL_UPDATE_REQUIRED" in invite_link or "DEFAULT" in invite_link:
        print("⚠️ WARNING: No valid invite link provided. Emails will contain a placeholder link.")

    recruitment_system = ClintRecruitmentSystem(testlify_link=(invite_link or ""))

    # Try to extract skills from description; keep simple defaults otherwise
    required_skills = ["Python", "Machine Learning", "AI"]
    preferred_skills = ["TensorFlow", "PyTorch", "NLP"]

    if job_desc:
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", "Extract required and preferred skills from job description. Return JSON with 'required_skills' and 'preferred_skills'."),
                ("human", "Job Title: {title}\nJob Description: {desc}")
            ])
            parser = JsonOutputParser()
            skill_chain = prompt | get_llm() | parser
            skills_result = skill_chain.invoke({"title": job_title, "desc": job_desc})
            required_skills = (skills_result.get("required_skills") or required_skills)[:5]
            preferred_skills = (skills_result.get("preferred_skills") or preferred_skills)[:5]
            print(f"📋 Extracted skills - Required: {required_skills}, Preferred: {preferred_skills}")
        except Exception as e:
            print(f"⚠️ Could not extract skills from job description: {e}")
            print(f"📋 Using default skills for {job_title}")

    recruitment_system.job_requirements = JobRequirements(
        job_id=str(job_id),
        title=job_title or "",
        description=job_desc or f"Looking for a talented {job_title}",
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        experience_years=2
    )

    ats_threshold = float(os.getenv("ATS_THRESHOLD", "70"))
    recruitment_system.set_ats_threshold(ats_threshold)

    # detect resume folder
    resume_folder = None
    possible_paths = [
        os.path.join(PROJECT_DIR, "resumes"),
        r"D:\hr-frontend\backend\resumes",
        os.path.join(os.path.dirname(__file__), "resumes")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            resume_folder = path
            break
    if not resume_folder:
        print(f"❌ Resume folder not found in any of these locations: {possible_paths}")
        return 0

    # collect resumes
    resume_files = [
        os.path.join(resume_folder, f)
        for f in os.listdir(resume_folder)
        if f.lower().endswith(('.pdf', '.docx', '.txt'))
    ]
    if not resume_files:
        print(f"⚠️ No resume files found in {resume_folder}")
        return 0

    print(f"📁 Found {len(resume_files)} resume files to process in {resume_folder}")

    session = SessionLocal()
    processed_count = 0
    shortlisted_count = 0

    try:
        for resume_path in resume_files:
            filename = os.path.basename(resume_path)
            try:
                print(f"\n📄 Processing resume: {filename}")

                existing = session.query(Candidate).filter_by(
                    resume_path=resume_path,
                    job_id=job_id
                ).first()
                if existing and existing.status:
                    print(f"⚠️ Resume already processed for this job: {filename}")
                    continue

                resume_text = extract_text_from_resume(resume_path)
                if not resume_text:
                    print(f"⚠️ Could not extract text from {filename}")
                    continue

                # ensure link is a string
                initial_state = RecruitmentState(
                    resume_text=resume_text,
                    job_requirements=recruitment_system.job_requirements,
                    ats_threshold=ats_threshold,
                    testlify_link=(invite_link or "")
                )

                print("🔄 Running AI analysis...")
                result = recruitment_system.graph.invoke(initial_state.model_dump())
                final_state = result if isinstance(result, RecruitmentState) else RecruitmentState(**result)

                candidate_data = {
                    "name": final_state.candidate.name,
                    "email": final_state.candidate.email,
                    "resume_path": resume_path,
                    "job_id": job_id,
                    "job_title": job_title,
                    "ats_score": final_state.candidate.ats_score,
                    "status": final_state.candidate.status,
                    "score_reasoning": str(final_state.candidate.score_reasoning)[:500],
                    # persist whichever provider link we used
                    "assessment_invite_link": (invite_link or ""),
                    "notification_sent": final_state.candidate.notification_sent,
                    "processed_date": datetime.now()
                }

                if final_state.candidate.status == "Shortlisted":
                    candidate_data.update({
                        "exam_link_sent": True,
                        "exam_link_sent_date": datetime.now()
                    })
                    shortlisted_count += 1

                if existing:
                    for key, value in candidate_data.items():
                        if key != 'id':
                            setattr(existing, key, value)
                else:
                    existing_by_email = session.query(Candidate).filter_by(
                        email=candidate_data["email"],
                        job_id=job_id
                    ).first()
                    if existing_by_email:
                        for key, value in candidate_data.items():
                            if key != 'id':
                                setattr(existing_by_email, key, value)
                    else:
                        session.add(Candidate(**candidate_data))

                session.commit()
                processed_count += 1

                if final_state.candidate.status == "Shortlisted":
                    print(f"✅ {candidate_data['name']} - SHORTLISTED (Score: {candidate_data['ats_score']:.1f})")
                    print(f"   Email sent: {final_state.candidate.notification_sent}")
                else:
                    print(f"❌ {candidate_data['name']} - REJECTED (Score: {candidate_data['ats_score']:.1f})")

            except Exception as e:
                logger.exception("Error processing single resume")
                print(f"❌ Error processing resume {filename}: {str(e)}")
                session.rollback()
                continue

        print("\n" + "="*50)
        print("📊 RECRUITMENT SUMMARY")
        print("="*50)
        print(f"Total resumes processed: {processed_count}")
        print(f"Shortlisted candidates: {shortlisted_count}")
        print(f"Rejected candidates: {processed_count - shortlisted_count}")
        if invite_link and "MANUAL_UPDATE_REQUIRED" not in (invite_link or ""):
            print(f"Assessment link sent: {invite_link}")
        else:
            print("⚠️ No valid assessment link - please update manually in database")
        print("="*50)

    except Exception as e:
        logger.exception("Critical error in recruitment pipeline")
        print(f"❌ Critical error in recruitment pipeline: {str(e)}")
        session.rollback()
    finally:
        session.close()

    return processed_count

if __name__ == "__main__":
    print("🤖 Welcome to Clint Agentic AI Recruitment System with LangGraph (DB Mode)")
    print("=" * 50)
    main()
