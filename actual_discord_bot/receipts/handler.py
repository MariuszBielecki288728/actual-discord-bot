import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from PIL import Image

from actual_discord_bot.receipts.models import ParsedReceipt
from actual_discord_bot.receipts.ocr_provider import (
    OCRConfig,
    OCRProvider,
    create_ocr_provider,
)
from actual_discord_bot.receipts.parser import ReceiptParser
from actual_discord_bot.receipts.pdf_extractor import PDFExtractor
from actual_discord_bot.receipts.preprocessing import preprocess_image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
PDF_EXTENSIONS = {".pdf"}


class ReceiptProcessingError(Exception):
    """Raised when receipt processing fails."""


class ReceiptHandler:
    """Orchestrates the full receipt processing pipeline."""

    def __init__(
        self,
        ocr_provider: OCRProvider | None = None,
        parser: ReceiptParser | None = None,
        pdf_extractor: PDFExtractor | None = None,
    ) -> None:
        self.ocr_provider = ocr_provider or create_ocr_provider(
            OCRConfig.from_environ()
        )
        self.parser = parser or ReceiptParser()
        self.pdf_extractor = pdf_extractor or PDFExtractor()

    def process_image_bytes(
        self, image_bytes: bytes, fallback_date: date | None = None
    ) -> ParsedReceipt:
        """Process a receipt image from raw bytes."""
        image = Image.open(io.BytesIO(image_bytes))
        return self.process_image(image, fallback_date)

    def process_image(
        self, image: Image.Image, fallback_date: date | None = None
    ) -> ParsedReceipt:
        """Process a receipt image through OCR pipeline."""
        preprocessed = preprocess_image(image)
        text = self.ocr_provider.extract_text(preprocessed)
        if not text.strip():
            msg = "OCR returned empty text"
            raise ReceiptProcessingError(msg)
        receipt = self.parser.parse(text, source="photo")
        if receipt.date is None:
            receipt.date = fallback_date
        return receipt

    def process_pdf_bytes(
        self, pdf_bytes: bytes, fallback_date: date | None = None
    ) -> ParsedReceipt:
        """Process a PDF receipt from raw bytes."""
        text = self.pdf_extractor.extract_text_from_bytes(pdf_bytes)
        if not text.strip():
            msg = "PDF text extraction returned empty text"
            raise ReceiptProcessingError(msg)
        receipt = self.parser.parse(text, source="pdf")
        if receipt.date is None:
            receipt.date = fallback_date
        return receipt

    def process_file(
        self, file_path: str | Path, fallback_date: date | None = None
    ) -> ParsedReceipt:
        """Process a receipt file (image or PDF) from disk."""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix in PDF_EXTENSIONS:
            text = self.pdf_extractor.extract_text(str(path))
            if not text.strip():
                msg = "PDF text extraction returned empty text"
                raise ReceiptProcessingError(msg)
            receipt = self.parser.parse(text, source="pdf")
        elif suffix in IMAGE_EXTENSIONS:
            image = Image.open(path)
            return self.process_image(image, fallback_date)
        else:
            msg = f"Unsupported file type: {suffix}"
            raise ReceiptProcessingError(msg)

        if receipt.date is None:
            receipt.date = fallback_date
        return receipt

    @staticmethod
    def validate_receipt(receipt: ParsedReceipt) -> tuple[bool, Decimal]:
        """
        Validate that item prices sum to the receipt total.

        Returns (is_valid, difference).
        """
        items_sum = sum(item.total_price for item in receipt.items)
        diff = receipt.total - items_sum
        threshold = Decimal("0.02")
        return abs(diff) <= threshold, diff
