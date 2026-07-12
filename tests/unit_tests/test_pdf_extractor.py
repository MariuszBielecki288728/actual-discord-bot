from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from actual_discord_bot.receipts.pdf_extractor import PDFExtractor

RECEIPTS_DIR = Path(__file__).parent.parent / "receipts"


class TestPDFExtractor:
    @pytest.fixture
    def extractor(self):
        return PDFExtractor()

    def test_extract_text_from_pdf_file(self, extractor):
        """Test extracting text from a real PDF receipt."""
        pdf_path = RECEIPTS_DIR / "paragon_online_kaufland.pdf"
        if not pdf_path.exists():
            pytest.skip("Test PDF not available")

        text = extractor.extract_text(str(pdf_path))
        assert len(text) > 0
        # Kaufland receipts should have some identifiable content
        assert any(
            keyword in text.upper()
            for keyword in ["KAUFLAND", "SUMA", "PLN", "PARAGON"]
        )

    def test_extract_text_from_bytes(self, extractor):
        """Test extracting text from PDF bytes."""
        pdf_path = RECEIPTS_DIR / "paragon_online_kaufland.pdf"
        if not pdf_path.exists():
            pytest.skip("Test PDF not available")

        pdf_bytes = pdf_path.read_bytes()
        text = extractor.extract_text_from_bytes(pdf_bytes)
        assert len(text) > 0

    def test_ignores_pages_without_extractable_text(self, extractor):
        page_with_text = MagicMock()
        page_with_text.extract_text.return_value = "First page"
        empty_page = MagicMock()
        empty_page.extract_text.return_value = None

        with patch(
            "actual_discord_bot.receipts.pdf_extractor.pdfplumber.open"
        ) as mock_open:
            mock_open.return_value.__enter__.return_value.pages = [
                page_with_text,
                empty_page,
            ]

            text = extractor.extract_text("receipt.pdf")

        assert text == "First page"
