"""S3 file upload utilities for Quiz Generator application."""
import logging
import os
from typing import Dict, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger(__name__)

# Create a requests session with connection pooling for uploads
upload_session = requests.Session()
upload_retry_strategy = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["POST"]
)
upload_adapter = HTTPAdapter(
    max_retries=upload_retry_strategy,
    pool_connections=5,
    pool_maxsize=10
)
upload_session.mount("http://", upload_adapter)
upload_session.mount("https://", upload_adapter)


def get_mime_type(filename: str) -> str:
    """Determine MIME type based on file extension."""
    filename_lower = filename.lower()
    if filename_lower.endswith('.pdf'):
        return 'application/pdf'
    elif filename_lower.endswith('.docx'):
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif filename_lower.endswith('.doc'):
        return 'application/msword'
    return 'application/octet-stream'


def get_upload_url(file_name: str, user_id: str, content_medium_type: str) -> Dict:
    """Get presigned upload URL from backend.
    
    Returns:
        Dictionary with 'success' key and either 'upload_data' or 'error'
    """
    try:
        json_data = {
            'file_name': file_name,
            'user_id': user_id,
            'content_medium_type': content_medium_type,
        }
        
        response = upload_session.post(
            config.UPLOAD_URL_ENDPOINT,
            headers=config.HEADERS,
            json=json_data,
            timeout=config.REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        upload_data = response.json()
        
        # Validate response structure
        if 'url' not in upload_data or 'fields' not in upload_data:
            logger.error("Invalid response format from upload URL API")
            return {
                'success': False,
                'error': 'Invalid response format from API'
            }
        
        return {
            'success': True,
            'upload_data': upload_data
        }
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout getting upload URL for file: {file_name}")
        return {
            'success': False,
            'error': 'Request timeout while getting upload URL'
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get upload URL: {e}")
        return {
            'success': False,
            'error': f'Failed to get upload URL: {str(e)}'
        }


def upload_to_s3(file_path: str, file_name: str, upload_data: Dict) -> Dict:
    """Upload file to S3 using presigned POST.
    
    Returns:
        Dictionary with 'success' key and either S3 details or 'error'
    """
    try:
        fields = upload_data.get('fields', {})
        s3_url_base = upload_data.get('url', '')
        s3_object_key = fields.get('key')
        
        if not fields:
            logger.error("No fields received in upload response")
            return {
                'success': False,
                'error': 'No fields received in upload response'
            }
        
        if not s3_url_base:
            logger.error("No URL received in upload response")
            return {
                'success': False,
                'error': 'No URL received in upload response'
            }
        
        mime_type = get_mime_type(file_name)
        
        # Prepare form data for S3 presigned POST
        form_data = {
            'key': fields.get('key'),
            'AWSAccessKeyId': fields.get('AWSAccessKeyId'),
            'policy': fields.get('policy'),
            'signature': fields.get('signature')
        }
        
        # Remove None values to avoid sending empty fields
        form_data = {k: v for k, v in form_data.items() if v is not None}
        
        # Upload to S3 using POST with multipart form data
        # Use context manager for efficient file handling
        with open(file_path, 'rb') as file_handle:
            files = {
                'file': (file_name, file_handle, mime_type)
            }
            
            upload_response = upload_session.post(
                s3_url_base,
                data=form_data,
                files=files,
                timeout=config.UPLOAD_TIMEOUT
            )
            upload_response.raise_for_status()
        
        # Construct full S3 URL
        s3_url: Optional[str] = None
        if s3_object_key:
            encoded_key = quote(s3_object_key, safe='')
            s3_url = f'{s3_url_base.rstrip("/")}/{encoded_key}'
        
        return {
            'success': True,
            's3_object_key': s3_object_key,
            's3_url': s3_url,
            'file_name': file_name
        }
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout uploading file to S3: {file_name}")
        return {
            'success': False,
            'error': 'Upload timeout. File may be too large.'
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to upload file to S3: {e}")
        return {
            'success': False,
            'error': f'Failed to upload file to S3: {str(e)}'
        }
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Unexpected error during upload: {str(e)}'
        }


def upload_pdf_to_s3(file_path: str, user_id: str, content_medium_type: str = 'PDF') -> Dict:
    """Upload a PDF or Word file to S3 via the JungleAI backend.
    
    Args:
        file_path: Path to the file to upload (PDF, DOC, or DOCX)
        user_id: User ID for the upload
        content_medium_type: Type of content, defaults to 'PDF' (can be 'PDF' or 'DOCX')
    
    Returns:
        Dictionary containing:
            - success (bool): Whether the upload was successful
            - s3_object_key (str): S3 object key if successful
            - s3_url (str): S3 URL if successful
            - error (str): Error message if failed
    """
    # Validate file exists
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return {
            'success': False,
            'error': f'File not found: {file_path}'
        }
    
    # Get file name
    file_name = os.path.basename(file_path)
    
    # Determine content type based on file extension if not provided
    if content_medium_type == 'PDF' and not file_name.lower().endswith('.pdf'):
        if file_name.lower().endswith(('.doc', '.docx')):
            content_medium_type = 'DOCX'
    
    # Step 1: Get upload URL from backend
    url_result = get_upload_url(file_name, user_id, content_medium_type)
    if not url_result['success']:
        return url_result
    
    # Step 2: Upload file to S3 using presigned POST
    upload_result = upload_to_s3(file_path, file_name, url_result['upload_data'])
    return upload_result
