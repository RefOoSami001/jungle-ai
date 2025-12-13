from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
import requests
import time
import uuid
import random
import json
import os
from urllib.parse import parse_qs, unquote
from werkzeug.utils import secure_filename
import PyPDF2
import pdfplumber
from docx import Document

app = Flask(__name__)

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = '6982141096:AAECOQeUg0dJ8DhVmRxEa-gUtd_SdHCKNQ0'
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'
ADMIN_CHAT_ID = "854578633"  # Set your admin chat ID here
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}

# Create uploads directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

HEADERS = {
    'accept': '*/*',
    'accept-language': 'ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7',
    'content-type': 'application/json',
    'origin': 'https://app.jungleai.com',
    'priority': 'u=1, i',
    'referer': 'https://app.jungleai.com/',
    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
}

# Replace this with a real user_id if you have one
DEFAULT_USER_ID = 'qnpzdCAWX7VOkFp61r9WR365kkd2'


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(file_path, start_page=None, end_page=None):
    """Extract text from PDF file, optionally with page range."""
    text_parts = []
    try:
        # Try pdfplumber first (better text extraction)
        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)
            start = (start_page - 1) if start_page else 0
            end = end_page if end_page else total_pages
            
            # Ensure valid range
            start = max(0, min(start, total_pages - 1))
            end = max(start + 1, min(end, total_pages))
            
            for i in range(start, end):
                page = pdf.pages[i]
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        # Fallback to PyPDF2
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                total_pages = len(pdf_reader.pages)
                start = (start_page - 1) if start_page else 0
                end = end_page if end_page else total_pages
                
                start = max(0, min(start, total_pages - 1))
                end = max(start + 1, min(end, total_pages))
                
                for i in range(start, end):
                    page = pdf_reader.pages[i]
                    text_parts.append(page.extract_text())
        except Exception as e2:
            raise Exception(f"Failed to extract PDF text: {str(e2)}")
    
    return '\n\n'.join(text_parts), total_pages


def extract_text_from_word(file_path, start_page=None, end_page=None):
    """Extract text from Word document. Note: Word doesn't have clear page boundaries,
    so we approximate by paragraphs."""
    try:
        doc = Document(file_path)
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        
        # For Word docs, we approximate pages as ~50 paragraphs per page
        # This is a rough estimate
        estimated_pages = max(1, len(paragraphs) // 50)
        
        if start_page or end_page:
            # Approximate page boundaries
            paras_per_page = max(1, len(paragraphs) // estimated_pages) if estimated_pages > 0 else len(paragraphs)
            start_idx = (start_page - 1) * paras_per_page if start_page else 0
            end_idx = end_page * paras_per_page if end_page else len(paragraphs)
            paragraphs = paragraphs[start_idx:end_idx]
        
        return '\n\n'.join(paragraphs), estimated_pages
    except Exception as e:
        raise Exception(f"Failed to extract Word text: {str(e)}")


def build_question_types(selected_types, difficulty='Advanced'):
    mapping = {
        'Multiple Choice Question': 'Multiple Choice Question',
        'Understanding Question': 'Understanding Question',
        'Case Scenario Multiple Choice Question': 'Case Scenario Multiple Choice Question',
        'True/False Question': 'True/False Question',
    }
    out = []
    for t in selected_types:
        if t in mapping:
            out.append({'cardType': mapping[t], 'difficultyGroup': difficulty})
    return out


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    input_method = request.form.get('input_method', 'text')
    topic_text = request.form.get('topic_text', '').strip()
    amount = request.form.get('amount', 'low')
    difficulty = request.form.get('difficulty', 'Advanced')
    types = request.form.getlist('question_type')
    user_id = request.form.get('user_id', DEFAULT_USER_ID)
    
    # Handle file upload only if input_method is 'file'
    uploaded_file = None
    file_path = None
    extracted_text = ''
    
    if input_method == 'file' and 'file' in request.files:
        file = request.files['file']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            uploaded_file = file
            
            # Get page range if provided
            page_start = request.form.get('page_start', '').strip()
            page_end = request.form.get('page_end', '').strip()
            start_page = None
            end_page = None
            
            # Validate and parse page range
            if page_start and page_start.isdigit():
                start_page = int(page_start)
                if start_page < 1:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    return render_template('index.html', error='Start page must be at least 1')
            
            if page_end and page_end.isdigit():
                end_page = int(page_end)
                if end_page < 1:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    return render_template('index.html', error='End page must be at least 1')
            
            # Validate start <= end if both are provided
            if start_page is not None and end_page is not None and start_page > end_page:
                if os.path.exists(file_path):
                    os.remove(file_path)
                return render_template('index.html', error='Start page must be less than or equal to end page')
            
            # Extract text based on file type
            try:
                if filename.lower().endswith('.pdf'):
                    # First, get total pages to validate range
                    try:
                        with pdfplumber.open(file_path) as pdf:
                            total_pages = len(pdf.pages)
                    except:
                        with open(file_path, 'rb') as f:
                            pdf_reader = PyPDF2.PdfReader(f)
                            total_pages = len(pdf_reader.pages)
                    
                    # Validate page range against total pages
                    if start_page is not None and start_page > total_pages:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        return render_template('index.html', error=f'Start page ({start_page}) exceeds total pages ({total_pages})')
                    if end_page is not None and end_page > total_pages:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                        return render_template('index.html', error=f'End page ({end_page}) exceeds total pages ({total_pages})')
                    
                    extracted_text, total_pages = extract_text_from_pdf(file_path, start_page, end_page)
                elif filename.lower().endswith(('.doc', '.docx')):
                    extracted_text, total_pages = extract_text_from_word(file_path, start_page, end_page)
                
                if not extracted_text or not extracted_text.strip():
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    return render_template('index.html', error='No text could be extracted from the file. Please check the file or page range.')
                
                # Clean up uploaded file after extraction
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                if os.path.exists(file_path):
                    os.remove(file_path)
                return render_template('index.html', error=f'Error extracting text from file: {str(e)}')
        else:
            return render_template('index.html', error='Please select a valid PDF or Word file')
    
    # Use extracted text from file if available, otherwise use topic_text
    if input_method == 'file':
        final_text = extracted_text
        if not final_text:
            return render_template('index.html', error='Please upload a file and ensure text can be extracted')
    else:
        final_text = topic_text
        if not final_text:
            return render_template('index.html', error='Please enter some text')

    question_types = build_question_types(types, difficulty=difficulty)

    json_data = {
        'should_run_generations_with_new_architecture': True,
        'pdf_pages_text_array': [final_text],
        'page_text_sentences_array': [],
        'page_url': 'https://wisdolia-download-bucket.s3.amazonaws.com/Respiratory-Failure_a844025e-afec-4a94-a3c1-06b0b32b9ccb.pdf',
        'page_title': '',
        'content_medium_type': 'PDF',
        'uploaded_file_s3_object_key': 'Respiratory-Failure_a844025e-afec-4a94-a3c1-06b0b32b9ccb.pdf',
        'user_id': 'qnpzdCAWX7VOkFp61r9WR365kkd2',
        'question_types_user_selected_to_generate': question_types,
        'session_id': '4da2bb95-4833-46c6-b2b2-1054e6e66532',
        'platform': 'Web',
        'youtubeTranscriptStartMinute': 0,
        'youtubeTranscriptEndMinute': 0,
        'pdfStartingPage': 1,
        'pdfEndingPage': 300,
        'did_user_input_url_for_pdf': False,
        'level_for_amount_of_cards_to_generate': amount,
        'selected_images_for_occlusion': [],
        'pdf_file_name': 'Respiratory Failure.pdf',
        'video_or_audio_starting_minute': 0,
        'video_or_audio_ending_minute': None,
        'video_or_audio_num_minutes': None,
        'deck_id_to_save_cards_to': None,
        'pdf_images_object_list_doc_id': 'dd80059c-7b40-4183-98d4-a24fe83472b9',
        'pdf_num_pages': 300,
        'didGetGeneratedWithMultipleUploadedDocuments': False,
    }

    try:
        resp = requests.post(
            'https://cbackend.jungleai.com/generate_content/run_all_generations_for_file_or_url',
            headers=HEADERS,
            json=json_data,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        return render_template('index.html', error=f'Generation request failed: {e}')

    deck_data_id = resp.json().get('deck_data_id')
    if not deck_data_id:
        return render_template('index.html', error='No deck id returned from generation API')

    # Redirect to the deck view so the client always uses the same flow
    return redirect(url_for('view_deck', deck_id=deck_data_id))



@app.route('/<deck_id>')
def view_deck(deck_id):
    """Render the quiz page for an existing deck id (direct link support).

    Example: GET /eK6fVwO4KTa7cGDLdGmW will render the quiz page and the client
    will open the SSE stream to `/stream_cards/<deck_id>` to receive cards.
    """
    return render_template('quiz.html', cards=[], deck_id=deck_id)



@app.route('/poll_cards/<deck_id>', methods=['GET'])
def poll_cards(deck_id):
    user_id = request.args.get('user_id', DEFAULT_USER_ID)
    try:
        cards_resp = requests.post(
            f'https://cbackend.jungleai.com/cards/get_all_cards_data_for_deck_and_subdecks/{deck_id}',
            headers=HEADERS,
            json={'user_id': user_id},
            timeout=30,
        )
        cards_resp.raise_for_status()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    data = cards_resp.json()
    cards = data.get('all_cards_for_deck') or data.get('all_cards_for_deck_and_subdecks') or []

    normalized = []
    for c in cards:
        options = []
        answer = c.get('answer')
        distractors = c.get('distractor_answers_for_multiple_choice_question') or []
        if distractors:
            options = distractors[:] + ([answer] if answer else [])
            random.shuffle(options)
        # handle True/False cards or cases where backend doesn't provide options
        card_type = (c.get('card_type') or '')
        ct_lower = str(card_type).lower()
        if (not options) and (('true' in ct_lower) or ('false' in ct_lower)):
            # standard True/False options
            options = ['True', 'False']
            # normalize answer to 'True'/'False' if possible
            if isinstance(answer, bool):
                answer = 'True' if answer else 'False'
            elif isinstance(answer, str) and answer.strip().lower() in ('true', 'false'):
                answer = 'True' if answer.strip().lower() == 'true' else 'False'
        # if answer is literally True/False but no options were provided, expose T/F options
        if (not options) and isinstance(answer, str) and answer.strip().lower() in ('true', 'false'):
            options = ['True', 'False']
        card_id = c.get('card_id') or c.get('id')
        # attempt to surface explanation text for Understanding-type cards
        explanation = c.get('explanation') or c.get('explanation_text') or c.get('detailed_answer') or c.get('solution') or answer
        normalized.append({
            'card_id': card_id,
            'question': c.get('question'),
            'case_details': c.get('case_scenario_details'),
            'card_type': c.get('card_type'),
            'answer': answer,
            'explanation': explanation,
            'options': options,
            'raw': c,
        })

    return jsonify({'cards': normalized})



@app.route('/stream_cards/<deck_id>')
def stream_cards(deck_id):
    """Server-Sent Events stream that pushes new cards as they're available.

    This creates a single long-lived connection to the browser. The server polls
    the backend for new cards and forwards only newly-seen cards to the client.
    When no new cards arrive for `max_idle` cycles the stream sends a `done`
    event and closes.
    """
    user_id = request.args.get('user_id', DEFAULT_USER_ID)

    def event_stream():
        seen = set()
        idle = 0
        poll_interval = 2.0
        max_idle = 30  # stop after ~max_idle * poll_interval seconds of inactivity

        while True:
            try:
                cards_resp = requests.post(
                    f'https://cbackend.jungleai.com/cards/get_all_cards_data_for_deck_and_subdecks/{deck_id}',
                    headers=HEADERS,
                    json={'user_id': user_id},
                    timeout=20,
                )
                cards_resp.raise_for_status()
                data = cards_resp.json()
                cards = data.get('all_cards_for_deck') or data.get('all_cards_for_deck_and_subdecks') or []

                normalized = []
                for c in cards:
                    card_id = c.get('card_id') or c.get('id')
                    if not card_id or card_id in seen:
                        continue
                    seen.add(card_id)
                    options = []
                    answer = c.get('answer')
                    distractors = c.get('distractor_answers_for_multiple_choice_question') or []
                    if distractors:
                        options = distractors[:] + ([answer] if answer else [])
                        random.shuffle(options)
                    # handle True/False cards or cases where backend doesn't provide options
                    card_type = (c.get('card_type') or '')
                    ct_lower = str(card_type).lower()
                    if (not options) and (('true' in ct_lower) or ('false' in ct_lower)):
                        options = ['True', 'False']
                        if isinstance(answer, bool):
                            answer = 'True' if answer else 'False'
                        elif isinstance(answer, str) and answer.strip().lower() in ('true', 'false'):
                            answer = 'True' if answer.strip().lower() == 'true' else 'False'
                    if (not options) and isinstance(answer, str) and answer.strip().lower() in ('true', 'false'):
                        options = ['True', 'False']

                    # attempt to surface explanation text for Understanding-type cards
                    explanation = c.get('explanation') or c.get('explanation_text') or c.get('detailed_answer') or c.get('solution') or answer
                    normalized.append({
                        'card_id': card_id,
                        'question': c.get('question'),
                        'case_details': c.get('case_scenario_details'),
                        'card_type': c.get('card_type'),
                        'answer': answer,
                        'explanation': explanation,
                        'options': options,
                    })

                if normalized:
                    payload = json.dumps({'cards': normalized})
                    yield f'data: {payload}\n\n'
                    idle = 0
                else:
                    idle += 1

            except Exception as e:
                # on error, send an error event and continue/pause
                try:
                    err = json.dumps({'error': str(e)})
                    yield f'data: {err}\n\n'
                except Exception:
                    pass
                idle += 1

            if idle >= max_idle:
                # send a custom event to let client know stream is finished
                yield 'event: done\n'
                yield 'data: {}\n\n'
                break

            time.sleep(poll_interval)

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
    }
    return Response(event_stream(), headers=headers)


def send_admin_notification(user_id, user_name, page='index'):
    """Send notification to admin when mini app is opened."""
    if not ADMIN_CHAT_ID:
        return  # Admin chat ID not configured
    
    try:
        message = f"📱 Mini app opened\n\n"
        message += f"User: #{user_id}\n"
        message += f"Name: {user_name or 'Unknown'}\n"
        message += f"Page: {page}"
        
        resp = requests.post(
            f'{TELEGRAM_API_URL}/sendMessage',
            json={
                'chat_id': ADMIN_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            },
            timeout=5
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"Error sending admin notification: {e}")
        return False


@app.route('/api/notify-admin', methods=['POST'])
def notify_admin():
    """Endpoint to notify admin when mini app is opened."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        user_name = data.get('user_name', 'Unknown')
        page = data.get('page', 'unknown')
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'User ID not provided'
            }), 400
        
        success = send_admin_notification(user_id, user_name, page)
        
        return jsonify({
            'success': success
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/get-telegram-user-id', methods=['POST'])
def get_telegram_user_id():
    """Extract user ID from Telegram WebApp initData."""
    try:
        data = request.get_json()
        init_data = data.get('initData', '')
        
        if not init_data:
            return jsonify({
                'success': False,
                'error': 'No initData provided'
            }), 400
        
        # Parse initData (format: key1=value1&key2=value2)
        params = parse_qs(init_data)
        
        # Get user parameter
        user_param = params.get('user', [None])[0]
        if user_param:
            try:
                import json
                user_data = json.loads(unquote(user_param))
                user_id = user_data.get('id')
                if user_id:
                    return jsonify({
                        'success': True,
                        'user_id': str(user_id)
                    })
            except (json.JSONDecodeError, KeyError) as e:
                pass
        
        return jsonify({
            'success': False,
            'error': 'Could not extract user ID from initData'
        }), 400
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/send-to-telegram', methods=['POST'])
def send_to_telegram():
    try:
        data = request.get_json()
        questions = data.get('questions', [])
        user_id = data.get('user_id')
        
        if not questions:
            return jsonify({
                'success': False,
                'error': 'No questions to send'
            }), 400
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'User ID not provided'
            }), 400
        
        # Send questions to the user
        sent_count = 0
        skipped_count = 0
        
        for question in questions:
            try:
                # Validate question
                if not question.get('question'):
                    skipped_count += 1
                    continue
                
                # Skip if question text is too long
                if len(question['question']) > 300:
                    skipped_count += 1
                    continue
                
                # Get question data
                question_text = question['question']
                answer = question.get('answer', 'No answer provided')
                options = question.get('options', [])
                card_type = question.get('card_type', '').lower()
                explanation = question.get('explanation', '')
                case_details = question.get('case_details', '')
                
                # Build question text with case details if available
                full_question_text = question_text
                if case_details:
                    full_question_text = f"📋 Case: {case_details}\n\n❓ {question_text}"
                else:
                    full_question_text = f"❓ {question_text}"
                
                # Check if it's an open-ended/understanding question (no options or Understanding type)
                is_open_ended = (
                    len(options) == 0 or 
                    'understand' in card_type or
                    question.get('correct') == -1
                )
                
                if is_open_ended:
                    # Send as text message for open-ended questions
                    message = f"{full_question_text}\n\n✅ Answer: {answer}"
                    if explanation and explanation != answer:
                        message += f"\n\n💡 Explanation: {explanation}"
                    
                    # Split long messages
                    if len(message) > 4096:
                        # Send question first
                        resp = requests.post(
                            f'{TELEGRAM_API_URL}/sendMessage',
                            json={'chat_id': user_id, 'text': full_question_text[:4096]}
                        )
                        if resp.status_code != 200:
                            raise Exception(f"Telegram API error: {resp.text}")
                        
                        # Send answer separately
                        answer_msg = f"✅ Answer: {answer}"
                        if explanation and explanation != answer:
                            answer_msg += f"\n\n💡 Explanation: {explanation}"
                        resp = requests.post(
                            f'{TELEGRAM_API_URL}/sendMessage',
                            json={'chat_id': user_id, 'text': answer_msg[:4096]}
                        )
                        if resp.status_code != 200:
                            raise Exception(f"Telegram API error: {resp.text}")
                    else:
                        resp = requests.post(
                            f'{TELEGRAM_API_URL}/sendMessage',
                            json={'chat_id': user_id, 'text': message}
                        )
                        if resp.status_code != 200:
                            raise Exception(f"Telegram API error: {resp.text}")
                    sent_count += 1
                else:
                    # Multiple Choice or True/False: send as poll
                    if len(options) < 2:
                        skipped_count += 1
                        continue
                    
                    # Find correct option index
                    correct_option_id = None
                    if answer:
                        try:
                            correct_option_id = options.index(answer)
                        except ValueError:
                            # Answer not in options, try case-insensitive match
                            for idx, opt in enumerate(options):
                                if opt.lower().strip() == answer.lower().strip():
                                    correct_option_id = idx
                                    break
                    
                    # If still not found, default to 0
                    if correct_option_id is None:
                        correct_option_id = 0
                    
                    # Filter out options that are too long (Telegram limit is 100 chars per option)
                    valid_options = []
                    valid_indices = []
                    for idx, option in enumerate(options):
                        if len(option) <= 100:
                            valid_options.append(option)
                            valid_indices.append(idx)
                    
                    if len(valid_options) < 2:
                        skipped_count += 1
                        continue
                    
                    # Adjust correct_option_id if we filtered options
                    if len(valid_options) != len(options):
                        if correct_option_id in valid_indices:
                            correct_option_id = valid_indices.index(correct_option_id)
                        else:
                            correct_option_id = 0
                    
                    # Add case details to question if available
                    poll_question = full_question_text
                    if len(poll_question) > 300:
                        poll_question = question_text[:300]
                    
                    # Send poll
                    try:
                        poll_data = {
                            'chat_id': user_id,
                            'question': poll_question,
                            'options': valid_options,
                            'is_anonymous': True,
                            'type': 'quiz',
                            'correct_option_id': correct_option_id
                        }
                        if explanation:
                            poll_data['explanation'] = explanation[:200]
                        
                        resp = requests.post(
                            f'{TELEGRAM_API_URL}/sendPoll',
                            json=poll_data
                        )
                        if resp.status_code != 200:
                            raise Exception(f"Telegram API error: {resp.text}")
                        sent_count += 1
                    except Exception as poll_err:
                        # If poll fails, send as text message
                        message = f"{full_question_text}\n\n✅ Answer: {answer}"
                        if explanation and explanation != answer:
                            message += f"\n\n💡 Explanation: {explanation}"
                        resp = requests.post(
                            f'{TELEGRAM_API_URL}/sendMessage',
                            json={'chat_id': user_id, 'text': message[:4096]}
                        )
                        if resp.status_code != 200:
                            raise Exception(f"Telegram API error: {resp.text}")
                        sent_count += 1
                
            except Exception as e:
                print(f"Error sending question: {e}")
                skipped_count += 1
                continue
        
        return jsonify({
            'success': True,
            'message': f'Sent {sent_count} questions to Telegram',
            'sent': sent_count,
            'skipped': skipped_count
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
