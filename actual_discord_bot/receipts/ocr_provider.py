from abc import ABC, abstractmethod

import environ
import pytesseract
from PIL import Image


class OCRProvider(ABC):
    """Abstract base for OCR backends."""

    @abstractmethod
    def extract_text(self, image: Image.Image) -> str:
        """Extract text from a preprocessed PIL Image."""


class TesseractProvider(OCRProvider):
    """Local Tesseract-based OCR (default, free)."""

    def __init__(self, lang: str = "pol", psm: int = 6) -> None:
        self.lang = lang
        self.psm = psm

    def extract_text(self, image: Image.Image) -> str:
        config = f"--psm {self.psm}"
        return pytesseract.image_to_string(image, lang=self.lang, config=config)


class AmazonTextractProvider(OCRProvider):
    """AWS Textract cloud OCR (paid, higher accuracy). Not implemented."""

    def extract_text(self, image: Image.Image) -> str:
        raise NotImplementedError


class GoogleCloudVisionProvider(OCRProvider):
    """Google Cloud Vision OCR (paid, higher accuracy). Not implemented."""

    def extract_text(self, image: Image.Image) -> str:
        raise NotImplementedError


@environ.config(prefix="OCR")
class OCRConfig:
    provider: str = environ.var(default="tesseract")
    tesseract_lang: str = environ.var(default="pol")
    tesseract_psm: int = environ.var(default=6, converter=int)


def create_ocr_provider(config: OCRConfig) -> OCRProvider:
    match config.provider:
        case "tesseract":
            return TesseractProvider(
                lang=config.tesseract_lang,
                psm=config.tesseract_psm,
            )
        case "textract":
            return AmazonTextractProvider()
        case "google_vision":
            return GoogleCloudVisionProvider()
        case _:
            msg = f"Unknown OCR provider: {config.provider}"
            raise ValueError(msg)
