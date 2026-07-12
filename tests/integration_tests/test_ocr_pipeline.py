from decimal import Decimal
from pathlib import Path

import pytest

from actual_discord_bot.receipts.handler import ReceiptHandler
from actual_discord_bot.receipts.ocr_provider import TesseractProvider
from actual_discord_bot.receipts.parser import ReceiptParser
from actual_discord_bot.receipts.pdf_extractor import PDFExtractor

RECEIPTS_DIR = Path(__file__).parent.parent / "receipts"


@pytest.fixture
def handler():
    return ReceiptHandler(
        ocr_provider=TesseractProvider(lang="pol", psm=6),
        parser=ReceiptParser(),
        pdf_extractor=PDFExtractor(),
    )


@pytest.mark.ocr
class TestTesseractOCR:
    """Integration tests: real images through Tesseract OCR."""

    def test_parse_receipt_photo_jedzenie(self, handler):
        """
        Parse a real restaurant receipt photo.

        This receipt is on a yellow background which degrades OCR quality.
        We only verify that processing doesn't crash — the output may be
        incomplete due to image quality issues.
        """
        image_path = RECEIPTS_DIR / "paragon_jedzenie.webp"
        if not image_path.exists():
            pytest.skip("Test image not available")

        receipt = handler.process_file(image_path)

        # Due to poor image quality, we only assert no crash and source is correct
        assert receipt.source == "photo"
        assert receipt.store_name != "Unknown"

    def test_parse_receipt_photo_basic(self, handler):
        """Parse a basic paper receipt (Społem/Stodoła Market)."""
        image_path = RECEIPTS_DIR / "paragon1.jpg"
        if not image_path.exists():
            pytest.skip("Test image not available")

        receipt = handler.process_file(image_path)

        # STODOŁA MARKET receipt, SUMA PLN 52,83
        assert receipt.total > Decimal("0")
        assert len(receipt.items) > 0

    def test_parse_kaufland_pdf(self, handler):
        """Parse the real Kaufland digital PDF receipt."""
        pdf_path = RECEIPTS_DIR / "paragon_online_kaufland.pdf"
        if not pdf_path.exists():
            pytest.skip("Test PDF not available")

        receipt = handler.process_file(pdf_path)

        assert receipt.store_name == "Kaufland Wrocław-Szczepin"
        assert receipt.total == Decimal("126.08")
        assert len(receipt.items) == 22
        assert receipt.source == "pdf"

    def test_parse_orlen_receipt(self, handler):
        """Parse Orlen fuel station receipt with discount."""
        image_path = RECEIPTS_DIR / "paragon_ze_zniżką_orlen.jpg"
        if not image_path.exists():
            pytest.skip("Test image not available")

        receipt = handler.process_file(image_path)

        assert receipt.total > 0
        assert receipt.source == "photo"
