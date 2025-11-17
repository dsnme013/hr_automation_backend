
from flask import Blueprint, jsonify, request, Response
from datetime import datetime, timezone, timedelta
import os, json, time, uuid, requests
from flask_cors import cross_origin
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_
from app.models.db import Candidate, SessionLocal
from app.extensions import logger
from app.routes.interview.helpers import calculate_time_difference
from app.routes.interview.helpers import trigger_auto_scoring
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


conversation_bp = Blueprint('conversation', __name__)

@conversation_bp.route('/api/interview/conversation/update', methods=['POST', 'OPTIONS'])
@cross_origin()
def update_conversation_snapshot():
    """Update conversation snapshot with complete data"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        session_id = data.get('session_id')
        conversation_data = data.get('conversation_data', [])
        
        if not session_id:
            return jsonify({"error": "session_id required"}), 400
        
        session = SessionLocal()
        try:
            # Find candidate by session_id
            candidate = session.query(Candidate).filter_by(
                interview_session_id=session_id
            ).first()
            
            if not candidate:
                # Try alternate lookup
                parts = session_id.split('_')
                if len(parts) >= 2 and parts[1].isdigit():
                    candidate = session.query(Candidate).filter_by(id=int(parts[1])).first()
            
            if not candidate:
                return jsonify({"error": "Session not found"}), 404
            
            # Store structured conversation data
            candidate.interview_conversation_structured = json.dumps(conversation_data)
            
            # Create formatted transcript
            formatted_transcript = format_conversation_transcript(conversation_data, candidate.name)
            candidate.interview_transcript = formatted_transcript
            
            # Update statistics
            questions = [entry for entry in conversation_data if entry.get('type') == 'question']
            answers = [entry for entry in conversation_data if entry.get('type') == 'answer']
            
            candidate.interview_total_questions = len(questions)
            candidate.interview_answered_questions = len(answers)
            
            # Update progress
            if len(questions) > 0:
                progress = (len(answers) / len(questions)) * 100
                candidate.interview_progress_percentage = min(progress, 100)
            
            # Update last activity
            candidate.interview_last_activity = datetime.now()
            
            # Check for auto-completion
            if len(answers) >= 10 or (len(questions) > 0 and len(answers) >= len(questions)):
                if not candidate.interview_completed_at:
                    candidate.interview_completed_at = datetime.now()
                    candidate.interview_ai_analysis_status = 'pending'
                    
                    # Calculate duration
                    if candidate.interview_started_at:
                        duration = (candidate.interview_completed_at - candidate.interview_started_at).total_seconds()
                        candidate.interview_duration = int(duration)
                    
                    logger.info(f"Auto-completed interview for {candidate.name} with {len(answers)} answers")
                    
                    # Trigger scoring
                    executor.submit(trigger_auto_scoring, candidate.id)
            
            session.commit()
            
            return jsonify({
                "success": True,
                "questions": len(questions),
                "answers": len(answers),
                "progress": candidate.interview_progress_percentage,
                "auto_completed": candidate.interview_completed_at is not None
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Conversation update error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@conversation_bp.route('/api/interview/conversation/get/<session_id>', methods=['GET'])
def get_conversation_data(session_id):
    """Get complete conversation data for a session"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(
            interview_session_id=session_id
        ).first()
        
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        # Get structured conversation data
        conversation_data = json.loads(candidate.interview_conversation_structured or '[]')
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "position": candidate.job_title
            },
            "conversation": conversation_data,
            "statistics": {
                "total_exchanges": len(conversation_data),
                "questions": len([e for e in conversation_data if e.get('type') == 'question']),
                "answers": len([e for e in conversation_data if e.get('type') == 'answer']),
                "progress": candidate.interview_progress_percentage or 0,
                "completed": candidate.interview_completed_at is not None
            },
            "formatted_transcript": candidate.interview_transcript
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()
def format_conversation_transcript(conversation_data, candidate_name):
    """Format conversation data into readable transcript"""
    transcript = f"Interview Transcript - {candidate_name}\n"
    transcript += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    transcript += "=" * 70 + "\n\n"
    
    for entry in conversation_data:
        try:
            timestamp = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
            time_str = timestamp.strftime('%H:%M:%S')
            speaker = 'AI Interviewer' if entry['speaker'] == 'avatar' else 'Candidate'
            content = entry['content'].strip()
            
            transcript += f"[{time_str}] {speaker}:\n{content}\n\n"
            
        except (KeyError, ValueError) as e:
            logger.warning(f"Error formatting entry: {e}")
            continue
    
    return transcript

@conversation_bp.route('/api/interview/qa/track-enhanced', methods=['POST', 'OPTIONS'])
@cross_origin()
def track_qa_enhanced():
    """Enhanced Q&A tracking with proper conversation structure"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        session_id = data.get('session_id')
        entry_type = data.get('type')  # 'question' or 'answer'
        content = data.get('content', '').strip()
        metadata = data.get('metadata', {})
        
        if not session_id or not content or not entry_type:
            return jsonify({"error": "Missing required fields"}), 400
        
        session = SessionLocal()
        try:
            candidate = session.query(Candidate).filter_by(
                interview_session_id=session_id
            ).first()
            
            if not candidate:
                return jsonify({"error": "Session not found"}), 404
            
            # Get existing conversation data
            conversation_data = json.loads(candidate.interview_conversation_structured or '[]')
            
            # Create new entry
            entry = {
                'id': metadata.get('entry_id', f"{entry_type}_{int(time.time())}"),
                'type': entry_type,
                'speaker': 'avatar' if entry_type == 'question' else 'candidate',
                'content': content,
                'timestamp': metadata.get('timestamp', datetime.now().isoformat()),
                'sequence': metadata.get('sequence', len(conversation_data) + 1),
                'linked_question_id': metadata.get('linked_question_id'),
                'word_count': metadata.get('word_count', len(content.split())),
                'confidence': metadata.get('confidence', 1.0),
                'is_complete': metadata.get('is_complete', True)
            }
            
            # Add to conversation data
            conversation_data.append(entry)
            
            # Update candidate record
            candidate.interview_conversation_structured = json.dumps(conversation_data)
            candidate.interview_last_activity = datetime.now()
            
            # Update counters
            questions = [e for e in conversation_data if e.get('type') == 'question']
            answers = [e for e in conversation_data if e.get('type') == 'answer']
            
            candidate.interview_total_questions = len(questions)
            candidate.interview_answered_questions = len(answers)
            
            # Update progress
            if len(questions) > 0:
                progress = (len(answers) / len(questions)) * 100
                candidate.interview_progress_percentage = min(progress, 100)
            
            # Update formatted transcript
            candidate.interview_transcript = format_conversation_transcript(
                conversation_data, candidate.name
            )
            
            session.commit()
            
            logger.info(f"Enhanced Q&A tracking: {entry_type} for {candidate.name}")
            
            return jsonify({
                "success": True,
                "entry_id": entry['id'],
                "total_questions": len(questions),
                "answered_questions": len(answers),
                "progress": candidate.interview_progress_percentage
            }), 200
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Enhanced Q&A tracking error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@conversation_bp.route('/api/interview/conversation/export/<session_id>', methods=['GET'])
def export_conversation_enhanced(session_id):
    """Export conversation with multiple format options"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(
            interview_session_id=session_id
        ).first()
        
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        # Get format from query parameter
        format_type = request.args.get('format', 'json')
        
        conversation_data = json.loads(candidate.interview_conversation_structured or '[]')
        
        if format_type == 'json':
            export_data = {
                "session_id": session_id,
                "candidate": {
                    "id": candidate.id,
                    "name": candidate.name,
                    "email": candidate.email,
                    "position": candidate.job_title
                },
                "conversation": conversation_data,
                "statistics": {
                    "total_exchanges": len(conversation_data),
                    "questions": len([e for e in conversation_data if e.get('type') == 'question']),
                    "answers": len([e for e in conversation_data if e.get('type') == 'answer']),
                    "duration": candidate.interview_duration,
                    "progress": candidate.interview_progress_percentage
                },
                "exported_at": datetime.now().isoformat()
            }
            
            return jsonify(export_data), 200
        
        elif format_type == 'text':
            transcript = format_conversation_transcript(conversation_data, candidate.name)
            
            response = Response(
                transcript,
                mimetype='text/plain',
                headers={
                    'Content-Disposition': f'attachment; filename=interview_{candidate.name}_{session_id}.txt'
                }
            )
            return response
        
        else:
            return jsonify({"error": "Invalid format"}), 400
            
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@conversation_bp.route('/api/interview/conversation/validate/<session_id>', methods=['GET'])
def validate_conversation_data(session_id):
    """Validate conversation data integrity"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(
            interview_session_id=session_id
        ).first()
        
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        conversation_data = json.loads(candidate.interview_conversation_structured or '[]')
        
        # Validate data integrity
        issues = []
        questions = []
        answers = []
        
        for entry in conversation_data:
            if not entry.get('content') or len(entry['content'].strip()) < 5:
                issues.append(f"Entry {entry.get('id', 'unknown')} has invalid content")
            
            if entry.get('type') == 'question':
                questions.append(entry)
            elif entry.get('type') == 'answer':
                answers.append(entry)
        
        # Check for orphaned answers
        orphaned_answers = [a for a in answers if not a.get('linked_question_id')]
        if orphaned_answers:
            issues.append(f"{len(orphaned_answers)} answers without linked questions")
        
        # Check sequence integrity
        sequences = [entry.get('sequence', 0) for entry in conversation_data]
        if len(set(sequences)) != len(sequences):
            issues.append("Duplicate sequence numbers detected")
        
        validation_result = {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "statistics": {
                "total_entries": len(conversation_data),
                "questions": len(questions),
                "answers": len(answers),
                "orphaned_answers": len(orphaned_answers),
                "expected_questions": candidate.interview_total_questions or 0,
                "expected_answers": candidate.interview_answered_questions or 0
            },
            "data_integrity": {
                "has_structured_data": len(conversation_data) > 0,
                "has_transcript": bool(candidate.interview_transcript),
                "counters_match": (
                    len(questions) == (candidate.interview_total_questions or 0) and
                    len(answers) == (candidate.interview_answered_questions or 0)
                )
            }
        }
        
        return jsonify(validation_result), 200
        
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# Database migration function (run once to add new columns)

@conversation_bp.route('/api/interview/qa/track', methods=['POST', 'OPTIONS'])
def track_interview_qa_unified():
    """Unified Q&A tracking with real-time conversation capture and fallback mechanisms"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Get data from the incoming request
        data = request.json
        session_id = data.get('session_id')
        content_type = data.get('type')  # 'question' or 'answer'
        content = data.get('content', '').strip()
        metadata = data.get('metadata', {})
        
        # Validation: session_id and content are required
        if not session_id or not content:
            return jsonify({"error": "Missing required fields"}), 400
        
        session = SessionLocal()
        try:
            # Try to find the candidate using the session_id
            candidate = session.query(Candidate).filter_by(interview_session_id=session_id).first()

            if not candidate:
                # Fallback 1: Try parsing session_id (split by '_')
                if '_' in session_id:
                    parts = session_id.split('_')
                    if len(parts) >= 2 and parts[1].isdigit():
                        candidate = session.query(Candidate).filter_by(id=int(parts[1])).first()
                        if candidate:
                            # Update the session_id for the candidate
                            candidate.interview_session_id = session_id

                # Fallback 2: Try by interview token if session_id contains it
                if not candidate and 'token' in session_id:
                    token = session_id.split('token_')[-1]  # Assuming token is part of the session_id
                    candidate = session.query(Candidate).filter_by(interview_token=token).first()
            
            # If no candidate is found, return error
            if not candidate:
                logger.error(f"No candidate found for session_id={session_id}")
                return jsonify({"error": "Session not found"}), 404
            
            # Proceed to track the Q&A data for the candidate
            # Initialize or retrieve current interview data
            qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
            conversation = json.loads(candidate.interview_conversation or '[]')
            transcript = candidate.interview_transcript or ""
            timestamp = datetime.now()

            if content_type == 'question':
                # This is a question from the knowledge base (KB)
                question_id = f"q_{len(qa_pairs) + 1}_{int(time.time())}"

                # Store the question data
                qa_entry = {
                    'id': question_id,
                    'question': content,
                    'answer': None,
                    'timestamp': timestamp.isoformat(),
                    'source': 'knowledge_base',
                    'is_transcribed': False,
                    'metadata': metadata
                }
                qa_pairs.append(qa_entry)

                # Add the question to the conversation
                conversation.append({
                    'type': 'question',
                    'speaker': 'Avatar',
                    'content': content,
                    'timestamp': timestamp.isoformat(),
                    'source': 'knowledge_base'
                })

                # Update transcript
                transcript += f"\n[{timestamp.strftime('%H:%M:%S')}] Avatar (KB): {content}\n"

                # Update the candidate's total question count
                candidate.interview_total_questions = len(qa_pairs)
                logger.info(f"Stored KB question #{len(qa_pairs)}: {content[:50]}...")

            elif content_type == 'answer':
                # This is a transcribed answer from the candidate
                # Find the most recent unanswered question
                for qa in reversed(qa_pairs):
                    if qa.get('question') and not qa.get('answer'):
                        qa['answer'] = content
                        qa['answer_timestamp'] = timestamp.isoformat()
                        qa['answer_source'] = 'voice_transcription'
                        qa['is_answer_transcribed'] = True
                        qa['answer_metadata'] = metadata
                        break

                # Add the answer to the conversation
                conversation.append({
                    'type': 'answer',
                    'speaker': 'Candidate',
                    'content': content,
                    'timestamp': timestamp.isoformat(),
                    'source': 'voice_transcription'
                })

                # Update transcript
                transcript += f"[{timestamp.strftime('%H:%M:%S')}] Candidate (Voice): {content}\n"

                # Update the answered question count
                answered = sum(1 for qa in qa_pairs if qa.get('answer'))
                candidate.interview_answered_questions = answered
                logger.info(f"Stored transcribed answer: {content[:50]}...")

            # Calculate interview progress
            if candidate.interview_total_questions > 0:
                progress = (candidate.interview_answered_questions / candidate.interview_total_questions) * 100
                candidate.interview_progress_percentage = progress

            # Save all updated data to the candidate record
            candidate.interview_qa_pairs = json.dumps(qa_pairs)
            candidate.interview_conversation = json.dumps(conversation)
            candidate.interview_transcript = transcript
            candidate.interview_last_activity = timestamp

            # Check for automatic interview completion if all questions are answered
            if (candidate.interview_total_questions >= 10 and 
                candidate.interview_answered_questions >= candidate.interview_total_questions):
                if not candidate.interview_completed_at:
                    candidate.interview_completed_at = datetime.now()
                    candidate.interview_ai_analysis_status = 'pending'
                    logger.info(f"Auto-completed interview for {candidate.name}")

            # Commit the changes to the database
            session.commit()

            return jsonify({
                "success": True,
                "stats": {
                    "total_questions": candidate.interview_total_questions,
                    "answered_questions": candidate.interview_answered_questions,
                    "progress": candidate.interview_progress_percentage
                }
            }), 200
            
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Q&A tracking error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@conversation_bp.route('/api/interview/qa/debug/<session_id>', methods=['GET'])
def debug_qa_tracking(session_id):
    """Debug endpoint to check Q&A tracking status"""
    
    session = SessionLocal()
    try:
        # Find candidate
        candidate = session.query(Candidate).filter_by(interview_session_id=session_id).first()
        
        if not candidate:
            # Try alternate lookups
            if '_' in session_id:
                parts = session_id.split('_')
                if len(parts) >= 2 and parts[1].isdigit():
                    candidate = session.query(Candidate).filter_by(id=int(parts[1])).first()
        
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Parse Q&A data
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        qa_sequence = json.loads(candidate.interview_qa_sequence or '[]')
        conversation = json.loads(candidate.interview_conversation or '[]')
        
        # Analyze the data
        questions = [q for q in qa_pairs if q.get('question')]
        answered = [q for q in qa_pairs if q.get('answer')]
        unanswered = [q for q in qa_pairs if q.get('question') and not q.get('answer')]
        
        return jsonify({
            "candidate_id": candidate.id,
            "session_id": session_id,
            "status": candidate.interview_status,
            "qa_analysis": {
                "total_qa_pairs": len(qa_pairs),
                "questions_asked": len(questions),
                "questions_answered": len(answered),
                "unanswered_questions": len(unanswered),
                "conversation_length": len(conversation),
                "qa_sequence_length": len(qa_sequence)
            },
            "unanswered_questions": [
                {
                    "id": q.get('id'),
                    "question": q.get('question'),
                    "order": q.get('order')
                } for q in unanswered
            ],
            "completion_status": {
                "completed_at": candidate.interview_completed_at.isoformat() if candidate.interview_completed_at else None,
                "should_be_complete": len(questions) >= 10 and len(questions) == len(answered)
            }
        })
        
    finally:
        session.close()

@conversation_bp.route('/api/interview/qa/get-conversation/<session_id>', methods=['GET'])
def get_qa_conversation_unified(session_id):
    """Get the complete Q&A conversation from all tracking systems"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_session_id=session_id).first()
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        # Get data from all systems
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        qa_sequence = json.loads(getattr(candidate, 'interview_qa_sequence', '[]'))
        conversation = json.loads(getattr(candidate, 'interview_conversation', '[]'))
        
        # Format conversation from real-time conversation tracking (primary)
        formatted_conversation = []
        for entry in conversation:
            formatted_conversation.append({
                'index': entry.get('sequence', len(formatted_conversation) + 1),
                'speaker': entry['speaker'],
                'type': entry['type'],
                'content': entry['content'],
                'timestamp': entry['timestamp'],
                'metadata': entry.get('metadata', {})
            })
        
        # If conversation is empty, fallback to qa_sequence
        if not formatted_conversation and qa_sequence:
            for entry in qa_sequence:
                if entry.get('type') == 'question':
                    formatted_conversation.append({
                        'index': entry.get('sequence_number', len(formatted_conversation) + 1),
                        'speaker': 'Avatar',
                        'type': 'question',
                        'content': entry['content'],
                        'timestamp': entry.get('timestamp')
                    })
                    if entry.get('answered') and entry.get('answer'):
                        formatted_conversation.append({
                            'index': len(formatted_conversation) + 1,
                            'speaker': 'Candidate',
                            'type': 'answer',
                            'content': entry['answer'],
                            'timestamp': entry.get('answer_timestamp')
                        })
        
        # Create formatted text exactly as requested
        formatted_text = f"Interview Conversation - {candidate.name}\n"
        formatted_text += f"Position: {candidate.job_title}\n"
        formatted_text += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        formatted_text += "="*70 + "\n\n"
        
        for entry in formatted_conversation:
            formatted_text += f"{entry['speaker']}: {entry['content']}\n\n"
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title
            },
            "formatted_transcript": formatted_text,
            "structured_conversation": formatted_conversation,
            "raw_transcript": candidate.interview_transcript,
            "conversation": formatted_conversation,
            "stats": {
                "total_exchanges": len(formatted_conversation),
                "questions_asked": len([e for e in formatted_conversation if e['type'] == 'question']),
                "answers_given": len([e for e in formatted_conversation if e['type'] == 'answer']),
                "progress": candidate.interview_progress_percentage,
                "total_questions": candidate.interview_total_questions,
                "answered_questions": candidate.interview_answered_questions,
                "unanswered_questions": candidate.interview_total_questions - candidate.interview_answered_questions,
                "currently_waiting_for_answer": getattr(candidate, 'interview_waiting_for_answer', False)
            },
            "tracking_systems": {
                "qa_pairs_count": len(qa_pairs),
                "qa_sequence_count": len(qa_sequence),
                "conversation_count": len(conversation)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@conversation_bp.route('/api/interview/qa/test/<session_id>', methods=['GET'])
def test_qa_tracking_unified(session_id):
    """Test endpoint to verify Q&A tracking is working correctly"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(interview_session_id=session_id).first()
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        # Get raw data from all systems
        qa_pairs = json.loads(candidate.interview_qa_pairs or '[]')
        qa_sequence = json.loads(getattr(candidate, 'interview_qa_sequence', '[]'))
        conversation = json.loads(getattr(candidate, 'interview_conversation', '[]'))
        
        # Analyze tracking health
        tracking_health = {
            "qa_pairs_healthy": all(qa.get('question') for qa in qa_pairs),
            "qa_sequence_healthy": all(entry.get('content') for entry in qa_sequence if entry.get('type') == 'question'),
            "conversation_healthy": all(entry.get('content') and entry.get('speaker') for entry in conversation),
            "answers_matched": sum(1 for qa in qa_pairs if qa.get('answer') is not None),
            "orphaned_answers": sum(1 for entry in qa_sequence if entry.get('type') == 'orphaned_answer'),
            "sync_status": {
                "qa_pairs_questions": len([q for q in qa_pairs if q.get('question')]),
                "qa_sequence_questions": len([e for e in qa_sequence if e.get('type') == 'question']),
                "conversation_questions": len([e for e in conversation if e.get('type') == 'question']),
                "all_synced": len(qa_pairs) == len([e for e in qa_sequence if e.get('type') == 'question']) == len([e for e in conversation if e.get('type') == 'question'])
            }
        }
        
        # Get last few entries for preview
        last_conversation = conversation[-5:] if conversation else []
        
        return jsonify({
            "session_id": session_id,
            "candidate": {
                "name": candidate.name,
                "position": candidate.job_title
            },
            "tracking_health": tracking_health,
            "last_conversation": last_conversation,
            "raw_data": {
                "qa_pairs": qa_pairs,
                "qa_sequence": qa_sequence,
                "conversation": conversation
            },
            "transcript_preview": candidate.interview_transcript[-500:] if candidate.interview_transcript else "No transcript",
            "stats": {
                "total_questions": candidate.interview_total_questions,
                "answered_questions": candidate.interview_answered_questions,
                "progress": candidate.interview_progress_percentage
            }
        }), 200
        
    finally:
        session.close()

@conversation_bp.route('/api/interview/qa/verify/<session_id>', methods=['GET'])
def verify_qa_tracking_enhanced(session_id):
    """Enhanced verification of Q&A tracking with detailed analysis"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(
            interview_session_id=session_id
        ).first()
        
        if not candidate:
            # Try to find by token if session_id looks like it contains a token
            if 'token_' in session_id:
                token = session_id.split('token_')[-1]
                candidate = session.query(Candidate).filter_by(
                    interview_token=token
                ).first()
        
        if not candidate:
            return jsonify({"error": "Session not found"}), 404
        
        # Parse Q&A data
        try:
            questions = json.loads(candidate.interview_questions_asked or '[]')
        except:
            questions = []
            
        try:
            answers = json.loads(candidate.interview_answers_given or '[]')
        except:
            answers = []
        
        # Create detailed Q&A pairs analysis
        qa_pairs = []
        for i, question in enumerate(questions):
            # Find matching answer
            matching_answer = None
            for answer in answers:
                if answer.get('question_order') == i + 1:
                    matching_answer = answer
                    break
            
            # If no exact match, try to match by timing
            if not matching_answer and i < len(answers):
                matching_answer = answers[i]
            
            qa_pairs.append({
                'question_number': i + 1,
                'question': {
                    'text': question.get('text', ''),
                    'timestamp': question.get('timestamp', ''),
                    'id': question.get('id', '')
                },
                'answer': {
                    'text': matching_answer.get('text', '') if matching_answer else None,
                    'timestamp': matching_answer.get('timestamp', '') if matching_answer else None,
                    'id': matching_answer.get('id', '') if matching_answer else None
                } if matching_answer else None,
                'has_answer': matching_answer is not None,
                'time_to_answer': calculate_time_difference(
                    question.get('timestamp'),
                    matching_answer.get('timestamp')
                ) if matching_answer else None
            })
        
        # Calculate statistics
        total_questions = len(questions)
        total_answers = len(answers)
        answer_rate = (total_answers / total_questions * 100) if total_questions > 0 else 0
        
        # Get transcript preview
        transcript = candidate.interview_transcript or ''
        transcript_lines = transcript.strip().split('\n')[-10:]  # Last 10 lines
        
        return jsonify({
            "session_id": session_id,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title
            },
            "statistics": {
                "total_questions": total_questions,
                "total_answers": total_answers,
                "unanswered_questions": total_questions - total_answers,
                "answer_rate": f"{answer_rate:.1f}%",
                "transcript_length": len(transcript),
                "transcript_lines": len(transcript.strip().split('\n')) if transcript else 0
            },
            "qa_pairs": qa_pairs,
            "recent_transcript": transcript_lines,
            "session_info": {
                "interview_token": candidate.interview_token,
                "knowledge_base_id": candidate.knowledge_base_id,
                "started_at": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None,
                "last_accessed": candidate.last_accessed.isoformat() if hasattr(candidate, 'last_accessed') and candidate.last_accessed else None
            },
            "recording_status": getattr(candidate, 'interview_recording_status', 'unknown')
        }), 200
        
    except Exception as e:
        logger.error(f"Error in verify Q&A: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@conversation_bp.route('/api/interview/conversation/<int:candidate_id>', methods=['GET'])
def get_interview_conversation(candidate_id):
    """Get the formatted conversation for a candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Get formatted conversation
        conversation = candidate.interview_conversation or "No conversation recorded"
        
        return jsonify({
            "success": True,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "position": candidate.job_title
            },
            "conversation": conversation,
            "timestamp": candidate.interview_started_at.isoformat() if candidate.interview_started_at else None
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@conversation_bp.route('/api/interview/qa/get/<int:candidate_id>', methods=['GET'])
def get_interview_qa_data(candidate_id):
    """Get complete Q&A data for a candidate"""
    session = SessionLocal()
    try:
        candidate = session.query(Candidate).filter_by(id=candidate_id).first()
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404
        
        # Parse all Q&A data
        questions = json.loads(candidate.interview_questions_asked or '[]')
        answers = json.loads(candidate.interview_answers_given or '[]')
        qa_pairs = json.loads(getattr(candidate, 'interview_qa_pairs', '[]'))
        
        return jsonify({
            "success": True,
            "candidate": {
                "id": candidate.id,
                "name": candidate.name,
                "email": candidate.email,
                "position": candidate.job_title
            },
            "qa_data": {
                "questions": questions,
                "answers": answers,
                "qa_pairs": qa_pairs,
                "total_questions": len(questions),
                "total_answers": len(answers),
                "completion_rate": f"{(len(answers) / len(questions) * 100) if questions else 0:.1f}%"
            },
            "transcript": candidate.interview_transcript,
            "analysis": {
                "status": candidate.interview_ai_analysis_status,
                "overall_score": candidate.interview_ai_score,
                "technical_score": candidate.interview_ai_technical_score,
                "communication_score": candidate.interview_ai_communication_score,
                "problem_solving_score": candidate.interview_ai_problem_solving_score,
                "cultural_fit_score": candidate.interview_ai_cultural_fit_score,
                "feedback": candidate.interview_ai_overall_feedback,
                "recommendation": candidate.interview_final_status
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting Q&A data: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()