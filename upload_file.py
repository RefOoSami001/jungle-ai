import requests
import os
from urllib.parse import quote


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

API_BASE_URL = 'https://cbackend.jungleai.com'


def upload_pdf_to_s3(file_path, user_id, content_medium_type='PDF'):
    """
    Upload a PDF or Word file to S3 via the JungleAI backend.
    
    Args:
        file_path (str): Path to the file to upload (PDF, DOC, or DOCX)
        user_id (str): User ID for the upload
        content_medium_type (str): Type of content, defaults to 'PDF' (can be 'PDF' or 'DOCX')
    
    Returns:
        dict: Dictionary containing:
            - success (bool): Whether the upload was successful
            - s3_object_key (str): S3 object key if successful
            - s3_url (str): S3 URL if successful
            - error (str): Error message if failed
    """
    # Validate file exists
    if not os.path.exists(file_path):
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
    try:
        json_data = {
            'file_name': file_name,
            'user_id': user_id,
            'content_medium_type': content_medium_type,
        }
        
        response = requests.post(
            f'{API_BASE_URL}/file_or_url/generate_url_for_file_upload_to_s3',
            headers=HEADERS,
            json=json_data,
            timeout=30
        )
        response.raise_for_status()
        
        upload_data = response.json()
        
        # Validate response structure
        if 'url' not in upload_data or 'fields' not in upload_data:
            return {
                'success': False,
                'error': 'Invalid response format from API'
            }
        
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': f'Failed to get upload URL: {str(e)}'
        }
    
    # Step 2: Upload file to S3 using presigned POST
    try:
        # Extract fields from response
        fields = upload_data.get('fields', {})
        s3_url_base = upload_data.get('url', '')
        s3_object_key = fields.get('key')
        
        if not fields:
            return {
                'success': False,
                'error': 'No fields received in upload response'
            }
        
        if not s3_url_base:
            return {
                'success': False,
                'error': 'No URL received in upload response'
            }
        
        # Prepare form data for S3 presigned POST
        # S3 presigned POST requires all fields to be sent as form data
        # Determine MIME type based on file extension
        if file_name.lower().endswith('.pdf'):
            mime_type = 'application/pdf'
        elif file_name.lower().endswith('.docx'):
            mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        elif file_name.lower().endswith('.doc'):
            mime_type = 'application/msword'
        else:
            mime_type = 'application/octet-stream'
        
        with open(file_path, 'rb') as f:
            # Prepare form fields (all fields from the response)
            form_data = {
                'key': fields.get('key'),
                'AWSAccessKeyId': fields.get('AWSAccessKeyId'),
                'policy': fields.get('policy'),
                'signature': fields.get('signature')
            }
            
            # Remove None values
            form_data = {k: v for k, v in form_data.items() if v is not None}
            
            # For S3 presigned POST, the file must be the last field
            # The file field name should match what's in the policy (usually 'file')
            files = {
                'file': (file_name, f, mime_type)
            }
            
            # Upload to S3 using POST with multipart form data
            # Note: Don't set Content-Type header, let requests set it for multipart
            upload_response = requests.post(
                s3_url_base,
                data=form_data,
                files=files,
                timeout=60  # Longer timeout for file upload
            )
            upload_response.raise_for_status()
        
        # Construct full S3 URL
        s3_url = None
        if s3_object_key:
            # URL encode the object key
            encoded_key = quote(s3_object_key, safe='')
            s3_url = f'{s3_url_base.rstrip("/")}/{encoded_key}'
        
        return {
            'success': True,
            's3_object_key': s3_object_key,
            's3_url': s3_url,
            'file_name': file_name
        }
        
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': f'Failed to upload file to S3: {str(e)}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Unexpected error during upload: {str(e)}'
        }


# Example usage
if __name__ == '__main__':
    # Example: Upload a PDF file
    result = upload_pdf_to_s3(
        file_path=r"C:\Users\raafa\Desktop\أبحاث الكومينتي .pdf",
        user_id='2ih2TpB168QyRBl8mfxBeiGjqD83'
    )
    
    if result['success']:
        print(f"Upload successful!")
        print(f"S3 Object Key: {result['s3_object_key']}")
        print(f"S3 URL: {result['s3_url']}")
    else:
        print(f"Upload failed: {result['error']}")
