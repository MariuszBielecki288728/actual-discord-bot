from pathlib import Path

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
