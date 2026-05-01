from unittest.mock import patch

import pytest
from PIL import Image

from actual_discord_bot.receipts.ocr_provider import (
    AmazonTextractProvider,
    GoogleCloudVisionProvider,
    OCRConfig,
    TesseractProvider,
    create_ocr_provider,
)


class TestOCRProviderFactory:
    def test_create_tesseract_provider(self):
        config = OCRConfig(provider="tesseract", tesseract_lang="pol", tesseract_psm=6)
        provider = create_ocr_provider(config)
        assert isinstance(provider, TesseractProvider)
        assert provider.lang == "pol"
        assert provider.psm == 6

    def test_create_tesseract_custom_lang(self):
        config = OCRConfig(provider="tesseract", tesseract_lang="eng", tesseract_psm=4)
        provider = create_ocr_provider(config)
        assert isinstance(provider, TesseractProvider)
        assert provider.lang == "eng"
        assert provider.psm == 4

    def test_create_textract_provider(self):
        config = OCRConfig(provider="textract", tesseract_lang="pol", tesseract_psm=6)
        provider = create_ocr_provider(config)
        assert isinstance(provider, AmazonTextractProvider)

    def test_create_google_vision_provider(self):
        config = OCRConfig(
            provider="google_vision", tesseract_lang="pol", tesseract_psm=6
        )
        provider = create_ocr_provider(config)
        assert isinstance(provider, GoogleCloudVisionProvider)

    def test_unknown_provider_raises(self):
        config = OCRConfig(provider="unknown", tesseract_lang="pol", tesseract_psm=6)
        with pytest.raises(ValueError, match="Unknown OCR provider"):
            create_ocr_provider(config)


class TestTesseractProvider:
    def test_extract_text_calls_pytesseract(self):
        provider = TesseractProvider(lang="pol", psm=6)
        image = Image.new("L", (100, 100))

        with patch("pytesseract.image_to_string", return_value="test text") as mock:
            result = provider.extract_text(image)

        mock.assert_called_once_with(image, lang="pol", config="--psm 6")
        assert result == "test text"


class TestUnimplementedProviders:
    def test_textract_not_implemented(self):
        provider = AmazonTextractProvider()
        image = Image.new("L", (100, 100))
        with pytest.raises(NotImplementedError):
            provider.extract_text(image)

    def test_google_vision_not_implemented(self):
        provider = GoogleCloudVisionProvider()
        image = Image.new("L", (100, 100))
        with pytest.raises(NotImplementedError):
            provider.extract_text(image)
