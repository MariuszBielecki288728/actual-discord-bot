import io

import pdfplumber


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
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        return "\n".join(pages_text)
