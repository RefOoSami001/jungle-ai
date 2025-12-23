"""Configuration module for Quiz Generator application."""
import os
from typing import Dict

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '6982141096:AAECOQeUg0dJ8DhVmRxEa-gUtd_SdHCKNQ0')
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '854578633')

# Flask Configuration
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}

# API Configuration
API_BASE_URL = 'https://cbackend.jungleai.com'
GENERATE_ENDPOINT = f'{API_BASE_URL}/generate_content/run_all_generations_for_file_or_url'
CARDS_ENDPOINT = f'{API_BASE_URL}/cards/get_all_cards_data_for_deck_and_subdecks'
UPLOAD_URL_ENDPOINT = f'{API_BASE_URL}/file_or_url/generate_url_for_file_upload_to_s3'

# Default User ID
DEFAULT_USER_ID = os.environ.get('DEFAULT_USER_ID', 'MM0eYlGpZJTYMCLaKAvi5ztgVfx2')

# HTTP Headers
HEADERS: Dict[str, str] = {
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

# Question Type Mapping
QUESTION_TYPE_MAPPING = {
    'Multiple Choice Question': 'Multiple Choice Question',
    'Understanding Question': 'Understanding Question',
    'Case Scenario Multiple Choice Question': 'Case Scenario Multiple Choice Question',
    'True/False Question': 'True/False Question',
}

# Streaming Configuration
STREAM_POLL_INTERVAL = 2.0
STREAM_MAX_IDLE = 30

# Request Timeouts
REQUEST_TIMEOUT = 30
UPLOAD_TIMEOUT = 60
STREAM_TIMEOUT = 20
