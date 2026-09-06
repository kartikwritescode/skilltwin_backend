import io
import re
from typing import Optional, List, Dict, Any
from app.core.logging import logger


class DocumentProcessor:
    """
    Extracts and cleans text from PDF and plain text files.
    """

    @staticmethod
    def extract_text(file_bytes: bytes, filename: str) -> str:
        name_lower = filename.lower()
        if name_lower.endswith('.pdf'):
            return DocumentProcessor._extract_pdf(file_bytes)
        else:
            return DocumentProcessor._extract_plain_text(file_bytes)

    @staticmethod
    def _extract_pdf(file_bytes: bytes) -> str:
        text_parts = []
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for idx, page in enumerate(reader.pages):
                p = page.extract_text() or ''
                if p.strip():
                    text_parts.append(p)
            logger.info(f'Extracted {len(text_parts)} pages from PDF')
        except Exception as e:
            logger.warning(f'PDF extraction fallback: {e}')
            text_parts.append(DocumentProcessor._extract_plain_text(file_bytes))
        return DocumentProcessor.clean_text('\n\n'.join(text_parts))

    @staticmethod
    def _extract_plain_text(file_bytes: bytes) -> str:
        for enc in ['utf-8', 'latin-1', 'cp1252']:
            try:
                return DocumentProcessor.clean_text(file_bytes.decode(enc))
            except Exception:
                continue
        return DocumentProcessor.clean_text(file_bytes.decode('utf-8', errors='replace'))

    @staticmethod
    def clean_text(raw_text: str) -> str:
        if not raw_text:
            return ''
        cleaned = raw_text.replace('\r\n', '\n').replace('\r', '\n')
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', cleaned)
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        return cleaned.strip()



document_processor = DocumentProcessor()
