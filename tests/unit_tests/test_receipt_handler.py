from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from PIL import Image

from actual_discord_bot.receipts.handler import (
    ReceiptHandler,
    ReceiptProcessingError,
)
from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem


@pytest.fixture
def mock_ocr():
    ocr = MagicMock()
    ocr.extract_text.return_value = (
        "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nSUMA PLN 10,00\n"
    )
    return ocr


@pytest.fixture
def mock_pdf_extractor():
    extractor = MagicMock()
    extractor.extract_text.return_value = (
        "Store\nPARAGON FISKALNY\nItem 1 x5,00 5,00B\nSUMA PLN 5,00\n"
    )
    extractor.extract_text_from_bytes.return_value = (
        "Store\nPARAGON FISKALNY\nItem 1 x5,00 5,00B\nSUMA PLN 5,00\n"
    )
    return extractor


@pytest.fixture
def handler(mock_ocr, mock_pdf_extractor):
    return ReceiptHandler(
        ocr_provider=mock_ocr,
        pdf_extractor=mock_pdf_extractor,
    )


class TestReceiptHandlerProcessImage:
    def test_process_image_bytes_calls_ocr(self, handler, mock_ocr):
        fake_image = Image.new("RGB", (100, 100))
        import io

        buf = io.BytesIO()
        fake_image.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        receipt = handler.process_image_bytes(image_bytes)

        mock_ocr.extract_text.assert_called_once()
        assert receipt.store_name == "Store"
        assert receipt.source == "photo"

    def test_process_image_bytes_empty_ocr_raises(self, handler, mock_ocr):
        mock_ocr.extract_text.return_value = ""
        fake_image = Image.new("RGB", (100, 100))
        import io

        buf = io.BytesIO()
        fake_image.save(buf, format="PNG")

        with pytest.raises(ReceiptProcessingError, match="OCR returned empty text"):
            handler.process_image_bytes(buf.getvalue())

    def test_process_image_uses_fallback_date(self, handler, mock_ocr):
        # OCR text has no date
        mock_ocr.extract_text.return_value = (
            "Store\nPARAGON FISKALNY\nItem 1 x10,00 10,00B\nSUMA PLN 10,00\n"
        )
        fake_image = Image.new("RGB", (100, 100))
        import io

        buf = io.BytesIO()
        fake_image.save(buf, format="PNG")

        receipt = handler.process_image_bytes(buf.getvalue(), date(2026, 5, 1))
        assert receipt.date == date(2026, 5, 1)


class TestReceiptHandlerProcessPDF:
    def test_process_pdf_bytes_calls_extractor(self, handler, mock_pdf_extractor):
        receipt = handler.process_pdf_bytes(b"pdf_content")

        mock_pdf_extractor.extract_text_from_bytes.assert_called_once_with(
            b"pdf_content"
        )
        assert receipt.source == "pdf"

    def test_process_pdf_bytes_empty_text_raises(self, handler, mock_pdf_extractor):
        mock_pdf_extractor.extract_text_from_bytes.return_value = ""

        with pytest.raises(
            ReceiptProcessingError, match="PDF text extraction returned empty text"
        ):
            handler.process_pdf_bytes(b"empty_pdf")

    def test_process_pdf_uses_fallback_date(self, handler, mock_pdf_extractor):
        mock_pdf_extractor.extract_text_from_bytes.return_value = (
            "Store\nPARAGON FISKALNY\nItem 1 x5,00 5,00B\nSUMA PLN 5,00\n"
        )
        receipt = handler.process_pdf_bytes(b"pdf", date(2026, 5, 1))
        assert receipt.date == date(2026, 5, 1)


class TestReceiptHandlerValidation:
    def test_validate_exact_match(self):
        receipt = ParsedReceipt(
            store_name="Store",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
                ReceiptItem("B", Decimal("1"), Decimal("5.00"), Decimal("5.00")),
            ],
            total=Decimal("15.00"),
        )
        is_valid, diff = ReceiptHandler.validate_receipt(receipt)
        assert is_valid is True
        assert diff == Decimal("0")

    def test_validate_within_threshold(self):
        receipt = ParsedReceipt(
            store_name="Store",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
            ],
            total=Decimal("10.01"),
        )
        is_valid, diff = ReceiptHandler.validate_receipt(receipt)
        assert is_valid is True
        assert diff == Decimal("0.01")

    def test_validate_exceeds_threshold(self):
        receipt = ParsedReceipt(
            store_name="Store",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
            ],
            total=Decimal("12.00"),
        )
        is_valid, diff = ReceiptHandler.validate_receipt(receipt)
        assert is_valid is False
        assert diff == Decimal("2.00")

    def test_validate_negative_diff(self):
        receipt = ParsedReceipt(
            store_name="Store",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
                ReceiptItem("B", Decimal("1"), Decimal("5.00"), Decimal("5.00")),
            ],
            total=Decimal("10.00"),
        )
        is_valid, diff = ReceiptHandler.validate_receipt(receipt)
        assert is_valid is False
        assert diff == Decimal("-5.00")


class TestReceiptHandlerProcessFile:
    """Test process_file with different file types."""

    def test_process_pdf_file(self, handler, mock_pdf_extractor):
        import tempfile

        mock_pdf_extractor.extract_text.return_value = (
            "Store\nPARAGON FISKALNY\nItem 1 x5,00 5,00B\nSUMA PLN 5,00\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            receipt = handler.process_file(f.name)

        assert receipt.source == "pdf"
        mock_pdf_extractor.extract_text.assert_called_once()

    def test_process_image_file(self, handler, mock_ocr):
        import tempfile

        from PIL import Image

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img = Image.new("RGB", (100, 100))
            img.save(f, format="JPEG")
            tmp_path = f.name

        try:
            receipt = handler.process_file(tmp_path)
            assert receipt.source == "photo"
            mock_ocr.extract_text.assert_called_once()
        finally:
            import os

            os.unlink(tmp_path)

    def test_process_unsupported_file_raises(self, handler):
        with pytest.raises(ReceiptProcessingError, match="Unsupported file type"):
            handler.process_file("/tmp/receipt.docx")

    def test_process_pdf_empty_text_raises(self, handler, mock_pdf_extractor):
        import tempfile

        mock_pdf_extractor.extract_text.return_value = ""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            with pytest.raises(
                ReceiptProcessingError, match="PDF text extraction returned empty text"
            ):
                handler.process_file(f.name)
