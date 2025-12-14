"""Utility functions for Quiz Generator application."""
import os
import random
from typing import Dict, List, Optional, Any
from werkzeug.utils import secure_filename
import config


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS


def get_content_type(filename: str) -> str:
    """Determine content type based on file extension."""
    if filename.lower().endswith('.pdf'):
        return 'PDF'
    elif filename.lower().endswith(('.doc', '.docx')):
        return 'DOCX'
    return 'PDF'  # Default


def build_question_types(selected_types: List[str], difficulty: str = 'Advanced') -> List[Dict[str, str]]:
    """Build question types list for API request.
    
    Note: True/False Question always uses Basic difficulty regardless of the selected difficulty.
    """
    question_types = []
    for question_type in selected_types:
        if question_type not in config.QUESTION_TYPE_MAPPING:
            continue
        
        # True/False Question always uses Basic difficulty
        if question_type == 'True/False Question':
            question_types.append({
                'cardType': config.QUESTION_TYPE_MAPPING[question_type],
                'difficultyGroup': 'Basic'
            })
        else:
            question_types.append({
                'cardType': config.QUESTION_TYPE_MAPPING[question_type],
                'difficultyGroup': difficulty
            })
    
    return question_types


def normalize_answer(answer: Any) -> str:
    """Normalize answer to string format, handling boolean and string values."""
    if isinstance(answer, bool):
        return 'True' if answer else 'False'
    if isinstance(answer, str):
        answer_lower = answer.strip().lower()
        if answer_lower in ('true', 'false'):
            return 'True' if answer_lower == 'true' else 'False'
    return str(answer) if answer else ''


def build_options(answer: Any, distractors: List[str], card_type: Optional[str] = None) -> List[str]:
    """Build options list for multiple choice questions."""
    options = []
    
    if distractors:
        options = distractors[:]
        if answer:
            options.append(normalize_answer(answer))
        random.shuffle(options)
    
    # Handle True/False cards
    card_type_lower = str(card_type or '').lower()
    if not options and ('true' in card_type_lower or 'false' in card_type_lower):
        options = ['True', 'False']
    elif not options and isinstance(answer, str) and answer.strip().lower() in ('true', 'false'):
        options = ['True', 'False']
    
    return options


def get_explanation(card_data: Dict[str, Any], answer: Any) -> str:
    """Extract explanation text from card data."""
    return (
        card_data.get('explanation') or
        card_data.get('explanation_text') or
        card_data.get('detailed_answer') or
        card_data.get('solution') or
        normalize_answer(answer)
    )


def normalize_card(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize card data from API response to consistent format."""
    card_id = card_data.get('card_id') or card_data.get('id')
    if not card_id:
        return None
    
    answer = card_data.get('answer')
    card_type = card_data.get('card_type')
    distractors = card_data.get('distractor_answers_for_multiple_choice_question') or []
    
    normalized_answer = normalize_answer(answer)
    options = build_options(answer, distractors, card_type)
    explanation = get_explanation(card_data, answer)
    
    return {
        'card_id': card_id,
        'question': card_data.get('question'),
        'case_details': card_data.get('case_scenario_details'),
        'card_type': card_type,
        'answer': normalized_answer,
        'explanation': explanation,
        'options': options,
        'raw': card_data,
    }


def normalize_cards(cards_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize a list of cards from API response."""
    normalized = []
    for card_data in cards_data:
        normalized_card = normalize_card(card_data)
        if normalized_card:
            normalized.append(normalized_card)
    return normalized


def safe_remove_file(file_path: str) -> None:
    """Safely remove a file if it exists."""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        pass  # Ignore errors during cleanup


def get_secure_file_path(filename: str, upload_folder: str) -> str:
    """Get secure file path for uploaded file."""
    secure_name = secure_filename(filename)
    return os.path.join(upload_folder, secure_name)
