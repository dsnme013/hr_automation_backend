# interview_analysis_service_production_fixed.py
import json
import time
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
import os
from app.models.db import Candidate, SessionLocal
import openai
import re

logger = logging.getLogger(__name__)

class DynamicInterviewAnalyzer:
    """Production-ready dynamic interview analyzer"""
    
    def __init__(self):
        self.openai_key = os.getenv('OPENAI_API_KEY')
        if self.openai_key:
            openai.api_key = self.openai_key
        
        # Scoring weights
        self.weights = {
            'answer_quality': 0.35,
            'completeness': 0.25,
            'relevance': 0.20,
            'communication': 0.20
        }
        
        # Keywords for different aspects
        self.technical_keywords = [
            'implement', 'develop', 'design', 'architecture', 'algorithm',
            'database', 'api', 'framework', 'optimize', 'scale', 'debug',
            'testing', 'deployment', 'version control', 'git', 'agile'
        ]
        
        self.soft_skill_keywords = [
            'team', 'collaborate', 'communicate', 'lead', 'manage',
            'problem', 'solution', 'challenge', 'learn', 'adapt',
            'deadline', 'priority', 'stakeholder', 'conflict', 'feedback'
        ]
    
    def analyze_interview(self, candidate_id: int) -> Dict[str, Any]:
        """Main entry point for interview analysis"""
        
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(id=candidate_id).first()
            if not candidate:
                logger.error(f"Candidate {candidate_id} not found")
                return self._get_default_scores("Candidate not found")
            
            # Update status to processing
            candidate.interview_ai_analysis_status = 'processing'
            session.commit()
            
            # Extract Q&A data
            qa_pairs = self._extract_qa_data(candidate)
            
            if not qa_pairs or len(qa_pairs) == 0:
                logger.warning(f"No Q&A data for candidate {candidate_id}")
                return self._get_incomplete_interview_scores()
            
            # Check for invalid/test responses
            if self._has_invalid_responses(qa_pairs):
                logger.warning(f"Invalid responses detected for candidate {candidate_id}")
                return self._get_invalid_response_scores()
            
            # Perform dynamic analysis
            analysis_result = self._perform_dynamic_analysis(qa_pairs, candidate)
            
            # Save results
            self._save_analysis_results(candidate, analysis_result, session)
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"Error analyzing interview: {e}", exc_info=True)
            return self._get_default_scores(str(e))
        finally:
            session.close()
    
    def _extract_qa_data(self, candidate) -> List[Dict]:
        """Extract and validate Q&A data"""
        qa_pairs = []
        
        try:
            # Try different sources of Q&A data
            if candidate.interview_qa_pairs:
                qa_pairs = json.loads(candidate.interview_qa_pairs)
            elif candidate.interview_questions_asked and candidate.interview_answers_given:
                questions = json.loads(candidate.interview_questions_asked or '[]')
                answers = json.loads(candidate.interview_answers_given or '[]')
                
                for i, question in enumerate(questions):
                    qa_pair = {
                        'question': question.get('text', '') if isinstance(question, dict) else str(question),
                        'answer': '',
                        'timestamp': question.get('timestamp') if isinstance(question, dict) else None
                    }
                    
                    if i < len(answers):
                        answer = answers[i]
                        qa_pair['answer'] = answer.get('text', '') if isinstance(answer, dict) else str(answer)
                    
                    qa_pairs.append(qa_pair)
            
            # Filter out empty Q&A pairs
            qa_pairs = [qa for qa in qa_pairs if qa.get('question') and qa.get('answer')]
            
        except Exception as e:
            logger.error(f"Error extracting Q&A data: {e}")
        
        return qa_pairs
    
    def _has_invalid_responses(self, qa_pairs: List[Dict]) -> bool:
        """Check if responses are invalid/test data"""
        
        invalid_patterns = [
            'INIT_INTERVIEW',
            'TEST_RESPONSE',
            'undefined',
            'null',
            '[object Object]'
        ]
        
        for qa in qa_pairs:
            answer = qa.get('answer', '').strip()
            
            # Check for test patterns
            if any(pattern in answer for pattern in invalid_patterns):
                return True
            
            # Check if answer is too short (less than 5 characters)
            if len(answer) < 5:
                return True
            
            # Check if answer is just numbers or special characters
            if not any(c.isalpha() for c in answer):
                return True
        
        return False
    
    def _perform_dynamic_analysis(self, qa_pairs: List[Dict], candidate) -> Dict[str, Any]:
        """Perform actual dynamic analysis of responses"""
        
        # Try AI analysis first if available
        if self.openai_key:
            try:
                return self._analyze_with_ai(qa_pairs, candidate)
            except Exception as e:
                logger.warning(f"AI analysis failed, using rule-based: {e}")
        
        # Fallback to advanced rule-based analysis
        return self._analyze_with_advanced_rules(qa_pairs, candidate)
    
    def _analyze_with_ai(self, qa_pairs: List[Dict], candidate) -> Dict[str, Any]:
        """Use OpenAI for intelligent analysis"""
        
        # Prepare conversation for analysis
        conversation_text = self._format_qa_for_analysis(qa_pairs)
        
        prompt = f"""
        You are an expert interview evaluator. Analyze this interview for the {candidate.job_title} position.
        
        IMPORTANT: This is a REAL interview. Score based on ACTUAL content quality, not randomly.
        
        Interview Transcript:
        {conversation_text}
        
        Evaluate based on:
        1. Answer Quality: Are answers detailed, specific, and well-structured?
        2. Technical Knowledge: Does candidate demonstrate required skills?
        3. Communication: Are responses clear and articulate?
        4. Problem-Solving: Does candidate show analytical thinking?
        5. Cultural Fit: Does candidate align with professional values?
        
        SCORING RULES:
        - If answers are very brief or generic: 30-50%
        - If answers are moderate with some detail: 50-70%
        - If answers are detailed and thoughtful: 70-85%
        - If answers are exceptional with examples: 85-100%
        
        Return JSON with these exact fields:
        {{
            "technical_score": <0-100>,
            "communication_score": <0-100>,
            "problem_solving_score": <0-100>,
            "cultural_fit_score": <0-100>,
            "overall_score": <0-100>,
            "strengths": ["strength1", "strength2", "strength3"],
            "weaknesses": ["weakness1", "weakness2"],
            "feedback": "Detailed analysis paragraph",
            "recommendation": "Hire/Maybe/Reject"
        }}
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a professional interview evaluator. Be critical and fair."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1000
        )
        
        result = self._parse_ai_response(response.choices[0].message.content)
        result['method'] = 'ai-dynamic'
        result['confidence'] = 0.95
        
        return result
    
    def _analyze_with_advanced_rules(self, qa_pairs: List[Dict], candidate) -> Dict[str, Any]:
        """Advanced rule-based analysis when AI is not available"""
        
        # Initialize scores
        scores = {
            'technical': 0,
            'communication': 0,
            'problem_solving': 0,
            'cultural_fit': 0
        }
        
        # Analyze each Q&A pair
        total_score = 0
        for qa in qa_pairs:
            question = qa.get('question', '').lower()
            answer = qa.get('answer', '').lower()
            
            # Skip if answer is too short
            if len(answer) < 10:
                continue
            
            # Calculate answer quality score
            answer_score = self._calculate_answer_score(question, answer)
            total_score += answer_score
            
            # Categorize and score
            if any(kw in question for kw in ['technical', 'code', 'implement', 'design']):
                scores['technical'] += answer_score
            elif any(kw in question for kw in ['team', 'collaborate', 'conflict']):
                scores['cultural_fit'] += answer_score
            elif any(kw in question for kw in ['problem', 'challenge', 'solve']):
                scores['problem_solving'] += answer_score
            else:
                scores['communication'] += answer_score
        
        # Normalize scores
        num_questions = len(qa_pairs)
        if num_questions > 0:
            for key in scores:
                scores[key] = min(100, (scores[key] / num_questions) * 10)
        
        # Calculate overall score
        overall_score = sum(scores.values()) / len(scores)
        
        # Generate insights
        strengths, weaknesses = self._generate_insights(qa_pairs, scores)
        
        # Generate feedback
        feedback = self._generate_feedback(qa_pairs, scores, overall_score)
        
        return {
            'technical_score': scores['technical'],
            'communication_score': scores['communication'],
            'problem_solving_score': scores['problem_solving'],
            'cultural_fit_score': scores['cultural_fit'],
            'overall_score': overall_score,
            'strengths': strengths,
            'weaknesses': weaknesses,
            'feedback': feedback,
            'recommendation': 'Hire' if overall_score >= 70 else 'Maybe' if overall_score >= 50 else 'Reject',
            'method': 'rule-based-dynamic',
            'confidence': 0.75
        }
    
    def _calculate_answer_score(self, question: str, answer: str) -> float:
        """Calculate score for individual answer"""
        
        score = 0
        
        # Length scoring (0-30 points)
        word_count = len(answer.split())
        if word_count > 50:
            score += 30
        elif word_count > 25:
            score += 20
        elif word_count > 10:
            score += 10
        else:
            score += 5
        
        # Technical keyword presence (0-25 points)
        tech_keywords_found = sum(1 for kw in self.technical_keywords if kw in answer)
        score += min(25, tech_keywords_found * 5)
        
        # Soft skill keyword presence (0-20 points)
        soft_keywords_found = sum(1 for kw in self.soft_skill_keywords if kw in answer)
        score += min(20, soft_keywords_found * 4)
        
        # Structure indicators (0-15 points)
        if '.' in answer:  # Has sentences
            score += 5
        if any(word in answer for word in ['first', 'second', 'finally', 'then']):  # Structured response
            score += 5
        if any(char.isdigit() for char in answer):  # Contains specific details/numbers
            score += 5
        
        # Example/experience indicators (0-10 points)
        if any(word in answer for word in ['example', 'project', 'experience', 'worked']):
            score += 10
        
        return min(100, score)
    
    def _generate_insights(self, qa_pairs: List[Dict], scores: Dict) -> tuple:
        """Generate strengths and weaknesses"""
        
        strengths = []
        weaknesses = []
        
        # Analyze answer patterns
        total_answers = len(qa_pairs)
        answered_count = sum(1 for qa in qa_pairs if qa.get('answer'))
        avg_length = sum(len(qa.get('answer', '')) for qa in qa_pairs) / max(1, answered_count)
        
        # Completion rate
        completion_rate = (answered_count / total_answers * 100) if total_answers > 0 else 0
        
        if completion_rate >= 90:
            strengths.append("Excellent interview completion rate")
        elif completion_rate < 60:
            weaknesses.append("Low interview completion rate")
        
        # Answer detail
        if avg_length > 200:
            strengths.append("Provides detailed and comprehensive responses")
        elif avg_length < 50:
            weaknesses.append("Responses lack detail and depth")
        
        # Score-based insights
        if scores['technical'] >= 70:
            strengths.append("Strong technical knowledge")
        elif scores['technical'] < 50:
            weaknesses.append("Technical skills need improvement")
        
        if scores['communication'] >= 70:
            strengths.append("Excellent communication skills")
        elif scores['communication'] < 50:
            weaknesses.append("Communication skills need development")
        
        return strengths[:3], weaknesses[:3]
    
    def _generate_feedback(self, qa_pairs: List[Dict], scores: Dict, overall_score: float) -> str:
        """Generate comprehensive feedback"""
        
        total_questions = len(qa_pairs)
        answered = sum(1 for qa in qa_pairs if qa.get('answer'))
        
        feedback = f"""
INTERVIEW ANALYSIS REPORT
========================
Overall Performance: {overall_score:.1f}/100
Questions Answered: {answered}/{total_questions}

DETAILED ASSESSMENT:
- Technical Skills: {scores['technical']:.1f}/100
- Communication: {scores['communication']:.1f}/100
- Problem Solving: {scores['problem_solving']:.1f}/100
- Cultural Fit: {scores['cultural_fit']:.1f}/100

RECOMMENDATION: {'Strong candidate for the role' if overall_score >= 70 else 'Potential candidate with areas for improvement' if overall_score >= 50 else 'Not recommended for this position'}

The candidate's responses demonstrate {'strong' if overall_score >= 70 else 'moderate' if overall_score >= 50 else 'limited'} alignment with the role requirements.
"""
        return feedback.strip()
    
    def _save_analysis_results(self, candidate, results: Dict, session):
        """Save analysis results to database"""
        
        try:
            # Update scores
            candidate.interview_ai_score = results['overall_score']
            candidate.interview_ai_technical_score = results['technical_score']
            candidate.interview_ai_communication_score = results['communication_score']
            candidate.interview_ai_problem_solving_score = results['problem_solving_score']
            candidate.interview_ai_cultural_fit_score = results['cultural_fit_score']
            
            # Update feedback
            candidate.interview_ai_overall_feedback = results['feedback']
            candidate.interview_confidence_score = results.get('confidence', 0.75)
            candidate.interview_scoring_method = results.get('method', 'dynamic')
            
            # Store insights
            candidate.interview_strengths = json.dumps(results.get('strengths', []))
            candidate.interview_weaknesses = json.dumps(results.get('weaknesses', []))
            candidate.interview_recommendations = json.dumps([results.get('recommendation', 'Review needed')])
            
            # Update status
            candidate.interview_ai_analysis_status = 'completed'
            candidate.interview_analysis_completed_at = datetime.now()
            
            # Set final status
            if results['overall_score'] >= 70:
                candidate.interview_final_status = 'Passed'
                candidate.final_status = 'Interview Passed'
            elif results['overall_score'] >= 50:
                candidate.interview_final_status = 'Review'
                candidate.final_status = 'Needs Review'
            else:
                candidate.interview_final_status = 'Failed'
                candidate.final_status = 'Interview Failed'
            
            session.commit()
            logger.info(f"Analysis saved for candidate {candidate.id}: {results['overall_score']:.1f}%")
            
        except Exception as e:
            logger.error(f"Error saving results: {e}")
            session.rollback()
            raise
    
    def _format_qa_for_analysis(self, qa_pairs: List[Dict]) -> str:
        """Format Q&A pairs for analysis"""
        formatted = []
        for i, qa in enumerate(qa_pairs, 1):
            formatted.append(f"Q{i}: {qa.get('question', 'Unknown')}")
            formatted.append(f"A{i}: {qa.get('answer', 'No answer')}\n")
        return "\n".join(formatted)
    
    def _parse_ai_response(self, response_text: str) -> Dict:
        """Parse AI response safely"""
        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    'technical_score': float(data.get('technical_score', 0)),
                    'communication_score': float(data.get('communication_score', 0)),
                    'problem_solving_score': float(data.get('problem_solving_score', 0)),
                    'cultural_fit_score': float(data.get('cultural_fit_score', 0)),
                    'overall_score': float(data.get('overall_score', 0)),
                    'strengths': data.get('strengths', []),
                    'weaknesses': data.get('weaknesses', []),
                    'feedback': data.get('feedback', ''),
                    'recommendation': data.get('recommendation', 'Review')
                }
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
        
        return self._get_default_scores("Failed to parse AI response")
    
    def _get_incomplete_interview_scores(self) -> Dict:
        """Return scores for incomplete interview"""
        return {
            'technical_score': 0,
            'communication_score': 0,
            'problem_solving_score': 0,
            'cultural_fit_score': 0,
            'overall_score': 0,
            'strengths': [],
            'weaknesses': ['Interview not completed', 'No responses provided'],
            'feedback': 'Interview was not completed. No responses available for analysis.',
            'recommendation': 'Incomplete',
            'method': 'incomplete',
            'confidence': 0
        }
    
    def _get_invalid_response_scores(self) -> Dict:
        """Return scores for invalid/test responses"""
        return {
            'technical_score': 0,
            'communication_score': 0,
            'problem_solving_score': 0,
            'cultural_fit_score': 0,
            'overall_score': 0,
            'strengths': [],
            'weaknesses': ['Invalid or test responses detected', 'No meaningful content provided'],
            'feedback': 'The interview responses appear to be test data or invalid. Please schedule a new interview.',
            'recommendation': 'Invalid',
            'method': 'invalid',
            'confidence': 0
        }
    
    def _get_default_scores(self, error_msg: str) -> Dict:
        """Return default scores for errors"""
        return {
            'technical_score': 0,
            'communication_score': 0,
            'problem_solving_score': 0,
            'cultural_fit_score': 0,
            'overall_score': 0,
            'strengths': [],
            'weaknesses': ['Analysis could not be completed'],
            'feedback': f'Analysis error: {error_msg}',
            'recommendation': 'Error',
            'method': 'error',
            'confidence': 0
        }

# Global analyzer instance
dynamic_analyzer = DynamicInterviewAnalyzer()