import io

import pdfplumber

MAX_PDF_PAGES = 10


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be processed safely."""


class PDFExtractor:
    """Extract text content from PDF receipt files."""

    def extract_text(self, pdf_path: str) -> str:
        """Extract all text from a PDF file."""
        return self._extract_from_source(pdf_path)

    def extract_text_from_bytes(self, pdf_bytes: bytes) -> str:
        """Extract all text from PDF bytes (e.g., downloaded from Discord)."""
        return self._extract_from_source(io.BytesIO(pdf_bytes))

    def _extract_from_source(self, source: str | io.BytesIO) -> str:
        """Extract text from a PDF source (file path or BytesIO)."""
        pages_text = []
        with pdfplumber.open(source) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                msg = f"PDF exceeds the {MAX_PDF_PAGES}-page limit"
                raise PDFExtractionError(msg)
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        return "\n".join(pages_text)
