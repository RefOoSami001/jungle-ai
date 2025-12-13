"""Text extraction utilities for PDF and Word documents."""
import PyPDF2
import pdfplumber
from docx import Document
from typing import Tuple, Optional


def extract_text_from_pdf(file_path: str, start_page: Optional[int] = None, 
                           end_page: Optional[int] = None) -> Tuple[str, int]:
    """Extract text from PDF file, optionally with page range.
    
    Args:
        file_path: Path to PDF file
        start_page: Starting page number (1-indexed)
        end_page: Ending page number (1-indexed)
    
    Returns:
        Tuple of (extracted_text, total_pages)
    
    Raises:
        Exception: If text extraction fails
    """
    text_parts = []
    total_pages = 0
    pages_with_text = 0
    pages_processed = 0
    
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
                pages_processed += 1
                try:
                    page = pdf.pages[i]
                    page_text = page.extract_text()
                    
                    # If no text, try extracting tables
                    if not page_text or not page_text.strip():
                        tables = page.extract_tables()
                        if tables:
                            table_texts = []
                            for table in tables:
                                table_text = '\n'.join([
                                    ' | '.join([str(cell) if cell else '' for cell in row])
                                    for row in table
                                ])
                                if table_text.strip():
                                    table_texts.append(table_text)
                            if table_texts:
                                page_text = '\n'.join(table_texts)
                    
                    # Try alternative extraction method
                    if not page_text or not page_text.strip():
                        page_text = page.extract_text(layout=True)
                    
                    if page_text and page_text.strip():
                        text_parts.append(page_text.strip())
                        pages_with_text += 1
                except Exception as page_error:
                    # Continue with next page if one page fails
                    print(f"Warning: Failed to extract text from page {i+1}: {page_error}")
                    continue
                    
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
                    pages_processed += 1
                    try:
                        page = pdf_reader.pages[i]
                        page_text = page.extract_text()
                        if page_text and page_text.strip():
                            text_parts.append(page_text.strip())
                            pages_with_text += 1
                    except Exception as page_error:
                        print(f"Warning: Failed to extract text from page {i+1}: {page_error}")
                        continue
        except Exception as e2:
            raise Exception(f"Failed to extract PDF text: {str(e2)}")
    
    # Check if we got any text
    if not text_parts:
        error_msg = "No text could be extracted from the PDF"
        if pages_processed > 0:
            error_msg += f" (processed {pages_processed} page{'s' if pages_processed > 1 else ''})"
        error_msg += ". The PDF might be image-based (scanned) or encrypted. Please ensure the PDF contains selectable text."
        raise Exception(error_msg)
    
    # Warn if some pages had no text
    if pages_with_text < pages_processed:
        print(f"Warning: Only {pages_with_text} out of {pages_processed} pages contained extractable text")
    
    return '\n\n'.join(text_parts), total_pages


def extract_text_from_word(file_path: str, start_page: Optional[int] = None,
                           end_page: Optional[int] = None) -> Tuple[str, int]:
    """Extract text from Word document.
    
    Note: Word doesn't have clear page boundaries, so we approximate by paragraphs.
    
    Args:
        file_path: Path to Word document
        start_page: Starting page number (1-indexed, approximate)
        end_page: Ending page number (1-indexed, approximate)
    
    Returns:
        Tuple of (extracted_text, estimated_pages)
    
    Raises:
        Exception: If text extraction fails
    """
    try:
        doc = Document(file_path)
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        
        # For Word docs, we approximate pages as ~50 paragraphs per page
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


def get_pdf_page_count(file_path: str) -> int:
    """Get total page count from PDF file."""
    try:
        with pdfplumber.open(file_path) as pdf:
            return len(pdf.pages)
    except Exception:
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                return len(pdf_reader.pages)
        except Exception:
            return 0
