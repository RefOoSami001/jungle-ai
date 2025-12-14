"""Main Flask application for Quiz Generator."""
import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from io import BytesIO
from urllib.parse import parse_qs, unquote
from typing import Dict, List, Optional, Tuple

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Try to import reportlab for PDF generation
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# Try to use gevent for non-blocking sleep
try:
    from gevent import sleep as gevent_sleep
    USE_GEVENT_SLEEP = True
except ImportError:
    USE_GEVENT_SLEEP = False
    gevent_sleep = None

import config
import text_extraction
import utils
from upload_file import upload_pdf_to_s3

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import telebot
try:
    import telebot
    from telebot import apihelper
    TELEBOT_AVAILABLE = True
except ImportError:
    TELEBOT_AVAILABLE = False
    logger.warning("pyTelegramBotAPI not installed. Telegram poll feature will be disabled.")

app = Flask(__name__)

# Flask configuration
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER

# Create uploads directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize Telegram bot if available
bot = None
if TELEBOT_AVAILABLE and config.TELEGRAM_BOT_TOKEN:
    try:
        bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
        # Set longer timeout for bot operations
        apihelper.SESSION_TIMEOUT = 30
        logger.info("Telegram bot initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Telegram bot: {e}")
        bot = None

# Create a requests session with connection pooling and retry strategy
# This improves performance and reduces connection overhead
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=0.3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST", "GET"]
)
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=10,
    pool_maxsize=20
)
session.mount("http://", adapter)
session.mount("https://", adapter)


def validate_page_range(start_page: Optional[int], end_page: Optional[int], 
                       total_pages: int) -> Tuple[bool, Optional[str]]:
    """Validate page range against total pages.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if start_page is not None and start_page < 1:
        return False, 'Start page must be at least 1'
    if end_page is not None and end_page < 1:
        return False, 'End page must be at least 1'
    if start_page is not None and end_page is not None and start_page > end_page:
        return False, 'Start page must be less than or equal to end page'
    if start_page is not None and start_page > total_pages:
        return False, f'Start page ({start_page}) exceeds total pages ({total_pages})'
    if end_page is not None and end_page > total_pages:
        return False, f'End page ({end_page}) exceeds total pages ({total_pages})'
    return True, None


@contextmanager
def _file_cleanup(file_path: Optional[str]):
    """Context manager to ensure file cleanup."""
    try:
        yield
    finally:
        if file_path:
            utils.safe_remove_file(file_path)


def _parse_page_range() -> Tuple[Optional[int], Optional[int]]:
    """Parse and validate page range from form data."""
    page_start = request.form.get('page_start', '').strip()
    page_end = request.form.get('page_end', '').strip()
    start_page = int(page_start) if page_start and page_start.isdigit() else None
    end_page = int(page_end) if page_end and page_end.isdigit() else None
    return start_page, end_page


def _extract_text_from_file(file_path: str, filename: str, 
                            start_page: Optional[int], 
                            end_page: Optional[int]) -> Tuple[str, int]:
    """Extract text from file based on file type."""
    filename_lower = filename.lower()
    if filename_lower.endswith('.pdf'):
        return text_extraction.extract_text_from_pdf(file_path, start_page, end_page)
    elif filename_lower.endswith(('.doc', '.docx')):
        return text_extraction.extract_text_from_word(file_path, start_page, end_page)
    else:
        raise ValueError('Unsupported file type')


def _create_pdf_from_text(text_content: str) -> Tuple[str, int]:
    """Create a PDF file from text content.
    
    Returns:
        Tuple of (file_path, estimated_pages)
    """
    if not REPORTLAB_AVAILABLE:
        # Fallback: Create a simple text-based PDF using reportlab's canvas
        try:
            from reportlab.pdfgen import canvas
        except ImportError:
            raise ImportError("reportlab is required for text-to-PDF conversion. Please install it: pip install reportlab")
        
        # Create temporary file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf', dir=app.config['UPLOAD_FOLDER'])
        os.close(temp_fd)
        
        # Estimate pages (assuming ~50 lines per page)
        lines = text_content.split('\n')
        estimated_pages = max(1, len(lines) // 50)
        
        # Create simple PDF
        c = canvas.Canvas(temp_path, pagesize=letter)
        width, height = letter
        y_position = height - 50
        line_height = 14
        margin = 50
        
        for line in lines:
            if y_position < margin:
                c.showPage()
                y_position = height - 50
            
            # Wrap long lines
            max_width = width - 2 * margin
            words = line.split(' ')
            current_line = ''
            
            for word in words:
                test_line = current_line + (' ' if current_line else '') + word
                if c.stringWidth(test_line, 'Helvetica', 10) > max_width and current_line:
                    c.drawString(margin, y_position, current_line)
                    y_position -= line_height
                    current_line = word
                    if y_position < margin:
                        c.showPage()
                        y_position = height - 50
                else:
                    current_line = test_line
            
            if current_line:
                c.drawString(margin, y_position, current_line)
                y_position -= line_height
        
        c.save()
        return temp_path, estimated_pages
    
    # Use reportlab for better PDF generation
    temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf', dir=app.config['UPLOAD_FOLDER'])
    os.close(temp_fd)
    
    # Create PDF
    doc = SimpleDocTemplate(temp_path, pagesize=letter,
                          rightMargin=72, leftMargin=72,
                          topMargin=72, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    story = []
    
    # Define styles
    styles = getSampleStyleSheet()
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=11,
        leading=14,
        spaceAfter=6,
    )
    
    # Split text into paragraphs and add to story
    paragraphs = text_content.split('\n\n')
    for para in paragraphs:
        if para.strip():
            # Replace single newlines with <br/> for reportlab
            para_text = para.replace('\n', '<br/>')
            story.append(Paragraph(para_text, normal_style))
            story.append(Spacer(1, 0.2 * inch))
    
    # Build PDF
    doc.build(story)
    
    # Estimate pages (rough calculation: ~50 lines per page)
    lines = text_content.split('\n')
    estimated_pages = max(1, len(lines) // 50)
    
    return temp_path, estimated_pages


def process_file_upload(file, user_id: str) -> Tuple[bool, Dict]:
    """Process uploaded file: extract text and upload to S3.
    
    Args:
        file: File object or file-like object with save() method and filename attribute
        user_id: User ID for the upload
    
    Returns:
        Tuple of (success, result_dict)
        result_dict contains: extracted_text, total_pages, s3_object_key, s3_url, 
                              filename, content_type, start_page, end_page
    """
    # Handle both regular file uploads and text-generated PDFs
    if hasattr(file, 'filename'):
        filename = file.filename
    else:
        filename = getattr(file, 'filename', 'text_input.pdf')
    
    if not filename or (hasattr(file, 'filename') and not utils.allowed_file(filename)):
        return False, {'error': 'Please select a valid PDF or Word file'}
    
    file_path = utils.get_secure_file_path(filename, app.config['UPLOAD_FOLDER'])
    
    with _file_cleanup(file_path):
        try:
            # Save uploaded file or copy from source
            if hasattr(file, 'save'):
                # Regular file upload
                file.save(file_path)
            elif hasattr(file, 'file_path'):
                # For text-generated PDFs
                import shutil
                shutil.copy2(file.file_path, file_path)
            else:
                return False, {'error': 'Invalid file object'}
            
            # Parse page range
            start_page, end_page = _parse_page_range()
            
            # Get total pages for validation
            filename_lower = file_path.lower()
            if filename_lower.endswith('.pdf'):
                total_pages = text_extraction.get_pdf_page_count(file_path)
                if total_pages == 0:
                    return False, {'error': 'Could not determine PDF page count'}
            else:
                # For Word docs, we'll estimate after extraction
                total_pages = None
            
            # Validate page range if provided
            if start_page is not None or end_page is not None:
                if total_pages is None:
                    # For Word docs, we need to estimate first
                    _, estimated_pages = text_extraction.extract_text_from_word(file_path)
                    total_pages = estimated_pages
                
                is_valid, error_msg = validate_page_range(start_page, end_page, total_pages)
                if not is_valid:
                    return False, {'error': error_msg}
            
            # Extract text based on file type
            extracted_text, total_pages = _extract_text_from_file(
                file_path, file_path, start_page, end_page
            )
            
            if not extracted_text or not extracted_text.strip():
                error_msg = 'No text could be extracted from the file. '
                if filename_lower.endswith('.pdf'):
                    error_msg += ('The PDF might be image-based (scanned), encrypted, '
                                'or the selected page range might be empty. '
                                'Please ensure the PDF contains selectable text or try a different page range.')
                else:
                    error_msg += 'Please check the file or page range.'
                return False, {'error': error_msg}
            
            # Upload file to S3
            # Get filename - handle both regular files and text-generated PDFs
            file_filename = getattr(file, 'filename', 'text_input.pdf')
            content_type = utils.get_content_type(file_filename)
            upload_result = upload_pdf_to_s3(file_path, user_id, content_type)
            
            if not upload_result.get('success'):
                error_msg = upload_result.get('error', 'Unknown error')
                return False, {'error': f'Failed to upload file to S3: {error_msg}'}
            
            return True, {
                'extracted_text': extracted_text,
                'total_pages': total_pages,
                's3_object_key': upload_result.get('s3_object_key'),
                's3_url': upload_result.get('s3_url'),
                'filename': file_filename,
                'content_type': content_type,
                'start_page': start_page,
                'end_page': end_page,
            }
            
        except ValueError as e:
            return False, {'error': str(e)}
        except Exception as e:
            logger.error(f"Error processing file: {e}", exc_info=True)
            error_message = str(e)
            if 'No text could be extracted' in error_message:
                return False, {'error': error_message}
            elif 'Failed to extract' in error_message:
                return False, {
                    'error': (f'Error extracting text: {error_message}. '
                             'The file might be corrupted or in an unsupported format.')
                }
            else:
                return False, {'error': f'Error processing file: {error_message}'}


def build_generation_payload(extracted_text: str, user_id: str, question_types: List[Dict],
                            s3_url: str, s3_object_key: str, content_type: str,
                            filename: str, total_pages: int, start_page: Optional[int],
                            end_page: Optional[int], amount: str) -> Dict:
    """Build JSON payload for generation API request."""
    return {
        'should_run_generations_with_new_architecture': True,
        'pdf_pages_text_array': [extracted_text],
        'page_text_sentences_array': [extracted_text],
        'page_url': s3_url or '',
        'page_title': '',
        'content_medium_type': content_type,
        'uploaded_file_s3_object_key': s3_object_key or '',
        'user_id': user_id,
        'question_types_user_selected_to_generate': question_types,
        'session_id': str(uuid.uuid4()),
        'platform': 'Web',
        'youtubeTranscriptStartMinute': 0,
        'youtubeTranscriptEndMinute': 0,
        'pdfStartingPage': start_page if start_page else 1,
        'pdfEndingPage': end_page if end_page else total_pages,
        'did_user_input_url_for_pdf': False,
        'level_for_amount_of_cards_to_generate': amount,
        'selected_images_for_occlusion': [],
        'pdf_file_name': filename,
        'video_or_audio_starting_minute': 0,
        'video_or_audio_ending_minute': None,
        'video_or_audio_num_minutes': None,
        'deck_id_to_save_cards_to': None,
        'pdf_images_object_list_doc_id': str(uuid.uuid4()),
        'pdf_num_pages': total_pages,
        'didGetGeneratedWithMultipleUploadedDocuments': False,
    }


def fetch_cards_from_api(deck_id: str, user_id: str, timeout: int = None) -> Tuple[bool, List]:
    """Fetch cards from API for given deck_id.
    
    Args:
        deck_id: Deck ID to fetch cards for
        user_id: User ID
        timeout: Request timeout in seconds (defaults to config.REQUEST_TIMEOUT)
    
    Returns:
        Tuple of (success, cards_list)
    """
    if timeout is None:
        timeout = config.REQUEST_TIMEOUT
    
    try:
        response = session.post(
            f'{config.CARDS_ENDPOINT}/{deck_id}',
            headers=config.HEADERS,
            json={'user_id': user_id},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        cards = (data.get('all_cards_for_deck') or 
                data.get('all_cards_for_deck_and_subdecks') or [])
        return True, cards
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching cards for deck {deck_id}")
        return False, []
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch cards for deck {deck_id}: {e}")
        return False, []
    except Exception as e:
        logger.error(f"Unexpected error fetching cards: {e}", exc_info=True)
        return False, []


@app.route('/')
def index():
    """Render index page or redirect to quiz if quiz_id provided."""
    quiz_id = request.args.get('quiz_id', '').strip()
    if quiz_id:
        return redirect(url_for('view_deck', deck_id=quiz_id))
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    """Handle quiz generation request."""
    amount = request.form.get('amount', 'low')
    difficulty = request.form.get('difficulty', 'Advanced')
    types = request.form.getlist('question_type')
    user_id = request.form.get('user_id', config.DEFAULT_USER_ID)
    input_method = request.form.get('input_method', 'file')
    
    # Process input based on method
    if input_method == 'text':
        # Handle text input
        text_content = request.form.get('text_content', '').strip()
        if not text_content:
            return render_template('index.html', error='Please enter some text content')
        
        if len(text_content) < 50:
            return render_template('index.html', error='Please enter at least 50 characters of text')
        
        # Create PDF from text
        pdf_path = None
        try:
            pdf_path, estimated_pages = _create_pdf_from_text(text_content)
            
            # Create a file-like object to simulate file upload
            class TextFileWrapper:
                def __init__(self, file_path, filename):
                    self.file_path = file_path
                    self.filename = filename
                
                def save(self, path):
                    import shutil
                    shutil.copy2(self.file_path, path)
            
            # Process the generated PDF
            fake_file = TextFileWrapper(pdf_path, 'text_input.pdf')
            success, result = process_file_upload(fake_file, user_id)
            
        except Exception as e:
            logger.error(f"Error creating PDF from text: {e}", exc_info=True)
            return render_template('index.html', error=f'Error processing text: {str(e)}')
        finally:
            # Clean up temporary PDF
            if pdf_path:
                utils.safe_remove_file(pdf_path)
    else:
        # Process file upload
        if 'file' not in request.files:
            return render_template('index.html', error='Please select a valid PDF or Word file')
        
        file = request.files['file']
        success, result = process_file_upload(file, user_id)
    
    if not success:
        return render_template('index.html', error=result.get('error', 'Unknown error'))
    
    extracted_text = result['extracted_text']
    if not extracted_text:
        return render_template('index.html', error='Please upload a file and ensure text can be extracted')
    
    # Validate at least one question type is selected
    if not types:
        return render_template('index.html', error='Please select at least one question type')
    
    # Build question types
    question_types = utils.build_question_types(types, difficulty=difficulty)
    
    if not question_types:
        return render_template('index.html', error='Invalid question type selected')
    
    # Build generation payload
    json_data = build_generation_payload(
        extracted_text=extracted_text,
        user_id=user_id,
        question_types=question_types,
        s3_url=result['s3_url'],
        s3_object_key=result['s3_object_key'],
        content_type=result['content_type'],
        filename=result['filename'],
        total_pages=result['total_pages'],
        start_page=result['start_page'],
        end_page=result['end_page'],
        amount=amount,
    )
    
    
    # Send generation request
    try:
        response = session.post(
            config.GENERATE_ENDPOINT,
            headers=config.HEADERS,
            json=json_data,
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        response_data = response.json()
        deck_data_id = response_data.get('deck_data_id')
        
        if not deck_data_id:
            logger.warning("No deck_id returned from generation API")
            return render_template('index.html', 
                                error='No deck id returned from generation API')
        
        return redirect(url_for('view_deck', deck_id=deck_data_id))
    except requests.exceptions.RequestException as e:
        logger.error(f"Generation request failed: {e}", exc_info=True)
        return render_template('index.html', 
                            error=f'Generation request failed: {str(e)}')
    except (ValueError, KeyError) as e:
        logger.error(f"Invalid response from generation API: {e}", exc_info=True)
        return render_template('index.html', 
                            error='Invalid response from generation API')


@app.route('/<deck_id>')
def view_deck(deck_id):
    """Render the quiz page for an existing deck id (direct link support)."""
    return render_template('quiz.html', cards=[], deck_id=deck_id)


@app.route('/poll_cards/<deck_id>', methods=['GET'])
def poll_cards(deck_id):
    """Poll cards endpoint for one-time card retrieval."""
    user_id = request.args.get('user_id', config.DEFAULT_USER_ID)
    success, cards = fetch_cards_from_api(deck_id, user_id)
    
    if not success:
        return jsonify({'error': 'Failed to fetch cards'}), 500
    
    normalized = utils.normalize_cards(cards)
    return jsonify({'cards': normalized})


@app.route('/stream_cards/<deck_id>')
def stream_cards(deck_id):
    """Server-Sent Events stream that pushes new cards as they're available.
    
    This creates a single long-lived connection to the browser. The server polls
    the backend for new cards and forwards only newly-seen cards to the client.
    When no new cards arrive for `max_idle` cycles the stream sends a `done`
    event and closes.
    
    Optimized to prevent worker timeouts and memory issues:
    - Uses shorter timeouts for API requests
    - Sends heartbeat messages to keep connection alive
    - Limits maximum stream duration
    - Cleans up resources properly
    - Uses gevent.sleep for non-blocking sleep if available
    """
    user_id = request.args.get('user_id', config.DEFAULT_USER_ID)
    
    # Maximum stream duration in seconds (5 minutes)
    MAX_STREAM_DURATION = 300
    start_time = time.time()
    
    # Shorter timeout for streaming requests to prevent blocking
    STREAM_REQUEST_TIMEOUT = 10

    def event_stream():
        seen = set()
        idle = 0
        iteration = 0
        last_heartbeat = time.time()
        HEARTBEAT_INTERVAL = 15  # Send heartbeat every 15 seconds

        try:
            while True:
                # Check if stream has exceeded maximum duration
                if time.time() - start_time > MAX_STREAM_DURATION:
                    logger.info(f"Stream for deck {deck_id} exceeded max duration, closing")
                    yield 'event: done\n'
                    yield 'data: {"reason": "max_duration"}\n\n'
                    break
                
                iteration += 1
                
                try:
                    # Use shorter timeout for streaming to prevent blocking
                    success, cards = fetch_cards_from_api(deck_id, user_id, timeout=STREAM_REQUEST_TIMEOUT)
                    
                    if not success:
                        idle += 1
                        if idle >= config.STREAM_MAX_IDLE:
                            yield 'event: done\n'
                            yield 'data: {"reason": "max_idle"}\n\n'
                            break
                        
                        # Send heartbeat if needed
                        current_time = time.time()
                        if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                            yield ': heartbeat\n\n'
                            last_heartbeat = current_time
                        
                        # Use non-blocking sleep
                        sleep_time = min(config.STREAM_POLL_INTERVAL, 2.0)
                        if USE_GEVENT_SLEEP:
                            gevent_sleep(sleep_time)
                        else:
                            # For sync workers, yield frequently to prevent timeout
                            yield ': keepalive\n\n'
                            time.sleep(min(sleep_time, 0.5))
                        continue
                    
                    normalized = []
                    for card_data in cards:
                        normalized_card = utils.normalize_card(card_data)
                        if normalized_card and normalized_card['card_id'] not in seen:
                            seen.add(normalized_card['card_id'])
                            # Remove 'raw' from stream response to save bandwidth and memory
                            normalized_card.pop('raw', None)
                            normalized.append(normalized_card)
                    
                    # Clear cards list to free memory after processing
                    del cards
                    
                    # Limit seen set size to prevent memory issues (keep last 1000)
                    if len(seen) > 1000:
                        # Convert to list, keep last 1000, convert back to set
                        seen_list = list(seen)
                        seen = set(seen_list[-1000:])

                    if normalized:
                        payload = json.dumps({'cards': normalized})
                        yield f'data: {payload}\n\n'
                        idle = 0
                        last_heartbeat = time.time()
                    else:
                        idle += 1
                        
                        # Send heartbeat if needed
                        current_time = time.time()
                        if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                            yield ': heartbeat\n\n'
                            last_heartbeat = current_time

                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout fetching cards for deck {deck_id} (iteration {iteration})")
                    idle += 1
                    # Send heartbeat
                    current_time = time.time()
                    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                        yield ': heartbeat\n\n'
                        last_heartbeat = current_time
                    
                    if idle >= config.STREAM_MAX_IDLE:
                        yield 'event: done\n'
                        yield 'data: {"reason": "max_idle"}\n\n'
                        break
                    
                    # Use non-blocking sleep
                    sleep_time = min(config.STREAM_POLL_INTERVAL, 2.0)
                    if USE_GEVENT_SLEEP:
                        gevent_sleep(sleep_time)
                    else:
                        yield ': keepalive\n\n'
                        time.sleep(min(sleep_time, 0.5))
                    continue
                    
                except Exception as e:
                    logger.error(f"Error in event stream (iteration {iteration}): {e}", exc_info=True)
                    try:
                        err = json.dumps({'error': str(e)[:100]})  # Limit error message length
                        yield f'data: {err}\n\n'
                    except Exception:
                        pass
                    idle += 1
                    
                    # Send heartbeat
                    current_time = time.time()
                    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                        yield ': heartbeat\n\n'
                        last_heartbeat = current_time

                if idle >= config.STREAM_MAX_IDLE:
                    yield 'event: done\n'
                    yield 'data: {"reason": "max_idle"}\n\n'
                    break

                # Use non-blocking sleep to prevent worker timeout
                sleep_time = min(config.STREAM_POLL_INTERVAL, 2.0)
                if USE_GEVENT_SLEEP:
                    gevent_sleep(sleep_time)
                else:
                    # Yield keepalive and use shorter sleep for sync workers
                    yield ': keepalive\n\n'
                    time.sleep(min(sleep_time, 0.5))
                
        except GeneratorExit:
            # Client disconnected, cleanup
            logger.info(f"Client disconnected from stream for deck {deck_id}")
        except Exception as e:
            logger.error(f"Fatal error in event stream for deck {deck_id}: {e}", exc_info=True)
        finally:
            # Cleanup
            seen.clear()

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',  # Disable nginx buffering
    }
    return Response(event_stream(), headers=headers)


def send_admin_notification(user_id: str, user_name: str, page: str = 'index') -> bool:
    """Send notification to admin when mini app is opened."""
    if not config.ADMIN_CHAT_ID:
        return False
    
    try:
        message = f"📱 Mini app opened\n\nUser: {user_id}\nName: {user_name or 'Unknown'}\n"
        
        response = session.post(
            f'{config.TELEGRAM_API_URL}/sendMessage',
            json={
                'chat_id': config.ADMIN_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            },
            timeout=5
        )
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Error sending admin notification: {e}")
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
        return jsonify({'success': success})
        
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
        user_param = params.get('user', [None])[0]
        
        if user_param:
            try:
                user_data = json.loads(unquote(user_param))
                user_id = user_data.get('id')
                if user_id:
                    return jsonify({
                        'success': True,
                        'user_id': str(user_id)
                    })
            except (json.JSONDecodeError, KeyError):
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
    """Send quiz questions as polls to Telegram chat.
    
    Receives quiz cards and sends them as Telegram polls or messages
    depending on the question type.
    """
    if not bot:
        return jsonify({
            'success': False,
            'error': 'Telegram bot not available'
        }), 503
    
    try:
        data = request.get_json()
        cards = data.get('cards', [])
        user_id = data.get('user_id')
        
        if not cards:
            return jsonify({
                'success': False,
                'error': 'No questions to send'
            }), 400
        
        if not user_id:
            return jsonify({
                'success': False,
                'error': 'User ID not provided'
            }), 400
        
        # Convert user_id to integer if it's a string
        try:
            chat_id = int(user_id)
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'error': 'Invalid user ID format'
            }), 400
        
        sent_count = 0
        skipped_count = 0
        errors = []
        
        for card in cards:
            try:
                # Validate card
                if not card.get('question'):
                    skipped_count += 1
                    continue
                
                question_text = card['question']
                
                # Add case details if present
                if card.get('case_details'):
                    question_text = f"📋 {card['case_details']}\n\n❓ {question_text}"
                else:
                    question_text = f"❓ {question_text}"
                
                # Skip if question text is too long (Telegram limit is 300 chars for poll question)
                if len(question_text) > 300:
                    # Truncate and add ellipsis
                    question_text = question_text[:297] + "..."
                
                options = card.get('options', [])
                card_type = str(card.get('card_type', '')).lower()
                answer = card.get('answer', '')
                explanation = card.get('explanation', '')
                
                # Check if it's an understanding/open-ended question
                is_understanding = 'understand' in card_type or len(options) == 0
                
                if is_understanding:
                    # Send as text message for understanding questions
                    answer_text = answer if answer else 'No answer provided'
                    if explanation and explanation != answer:
                        message = f"{question_text}\n\n✅ **Answer:** {answer_text}\n\n💡 **Explanation:** {explanation}"
                    else:
                        message = f"{question_text}\n\n✅ **Answer:** {answer_text}"
                    
                    # Telegram message limit is 4096 characters
                    if len(message) > 4096:
                        message = message[:4090] + "..."
                    
                    try:
                        bot.send_message(chat_id, message, parse_mode='Markdown')
                        sent_count += 1
                        time.sleep(0.5)  # Rate limiting
                    except Exception as e:
                        logger.error(f"Error sending message to {chat_id}: {e}")
                        errors.append(f"Question {sent_count + skipped_count + 1}: {str(e)[:50]}")
                        skipped_count += 1
                else:
                    # Multiple Choice or True/False: send as poll
                    if len(options) < 2:
                        skipped_count += 1
                        continue
                    
                    # Filter and validate options
                    valid_options = []
                    for option in options:
                        option_str = str(option).strip()
                        # Telegram poll option limit is 100 characters
                        if option_str and len(option_str) <= 100:
                            valid_options.append(option_str)
                    
                    if len(valid_options) < 2:
                        skipped_count += 1
                        continue
                    
                    # Find correct option index
                    correct_option_id = None
                    normalized_answer = str(answer).strip()
                    
                    # Try exact match first
                    for idx, option in enumerate(valid_options):
                        option_str = str(option).strip()
                        if option_str == normalized_answer:
                            correct_option_id = idx
                            break
                    
                    # Try case-insensitive match if exact match failed
                    if correct_option_id is None:
                        for idx, option in enumerate(valid_options):
                            option_str = str(option).strip()
                            if option_str.lower() == normalized_answer.lower():
                                correct_option_id = idx
                                break
                    
                    # If answer not found in options, try to match True/False variations
                    if correct_option_id is None:
                        answer_lower = normalized_answer.lower()
                        for idx, option in enumerate(valid_options):
                            option_str = str(option).strip().lower()
                            if (answer_lower in ['true', 'false'] and 
                                option_str in ['true', 'false'] and 
                                answer_lower == option_str):
                                correct_option_id = idx
                                break
                    
                    # If still not found, use first option as default
                    if correct_option_id is None:
                        logger.warning(f"Answer '{answer}' not found in options for question: {question_text[:50]}")
                        correct_option_id = 0
                    
                    # Prepare explanation (Telegram limit is 200 chars)
                    poll_explanation = ''
                    if explanation:
                        poll_explanation = str(explanation)[:200]
                    
                    try:
                        # Send poll
                        bot.send_poll(
                            chat_id,
                            question_text,
                            options=valid_options,
                            is_anonymous=True,
                            type='quiz',
                            correct_option_id=correct_option_id,
                            explanation=poll_explanation if poll_explanation else None
                        )
                        sent_count += 1
                        time.sleep(0.1)  # Rate limiting between polls
                    except Exception as e:
                        logger.error(f"Error sending poll to {chat_id}: {e}")
                        errors.append(f"Question {sent_count + skipped_count + 1}: {str(e)[:50]}")
                        skipped_count += 1
                
            except Exception as e:
                logger.error(f"Error processing card: {e}", exc_info=True)
                skipped_count += 1
                errors.append(f"Question {sent_count + skipped_count}: {str(e)[:50]}")
                continue
        
        response_data = {
            'success': True,
            'message': f'Sent {sent_count} questions to Telegram',
            'sent': sent_count,
            'skipped': skipped_count
        }
        
        if errors:
            response_data['errors'] = errors[:5]  # Limit error details
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in send_to_telegram endpoint: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
