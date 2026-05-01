from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from actual_discord_bot import ActualDiscordBot
from actual_discord_bot.config import DiscordConfig
from actual_discord_bot.receipts.handler import ReceiptHandler, ReceiptProcessingError
from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem


@pytest.fixture
def receipt_handler():
    mock_ocr = MagicMock()
    mock_ocr.extract_text.return_value = ""
    return ReceiptHandler(
        ocr_provider=mock_ocr,
        parser=MagicMock(),
        pdf_extractor=MagicMock(),
    )


@pytest.fixture
def bot(receipt_handler):
    config = DiscordConfig(
        token="token",
        bank_notification_channel="bank-notifications",
        receipt_channel="receipts",
    )
    mock_actual_connector = MagicMock()
    return ActualDiscordBot(config, mock_actual_connector, receipt_handler)


@pytest.fixture
def mock_receipt_message():
    message = AsyncMock(spec=discord.Message)
    message.created_at = MagicMock()
    message.created_at.date.return_value = date(2026, 4, 30)
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = "receipt.jpg"
    attachment.read = AsyncMock(return_value=b"fake_image_bytes")
    message.attachments = [attachment]
    return message


class TestReceiptMessageHandler:
    @pytest.mark.asyncio
    async def test_image_attachment_triggers_processing(
        self, bot, mock_receipt_message
    ):
        """Test that an image attachment triggers receipt processing."""
        parsed_receipt = ParsedReceipt(
            store_name="Test Store",
            items=[
                ReceiptItem("Item1", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
            ],
            total=Decimal("10.00"),
            date=date(2026, 4, 30),
            source="photo",
        )
        bot.receipt_handler.process_image_bytes = MagicMock(return_value=parsed_receipt)
        bot.receipt_handler.validate_receipt = MagicMock(
            return_value=(True, Decimal("0"))
        )

        await bot.handle_receipt_message(mock_receipt_message)

        bot.receipt_handler.process_image_bytes.assert_called_once()
        bot.actual_connector.save_receipt_transaction.assert_called_once()
        mock_receipt_message.add_reaction.assert_called_with("✅")

    @pytest.mark.asyncio
    async def test_pdf_attachment_triggers_processing(self, bot):
        """Test that a PDF attachment triggers PDF processing."""
        message = AsyncMock(spec=discord.Message)
        message.created_at = MagicMock()
        message.created_at.date.return_value = date(2026, 4, 30)
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename = "receipt.pdf"
        attachment.read = AsyncMock(return_value=b"fake_pdf_bytes")
        message.attachments = [attachment]

        parsed_receipt = ParsedReceipt(
            store_name="Kaufland",
            items=[
                ReceiptItem("Mleko", Decimal("1"), Decimal("4.99"), Decimal("4.99")),
            ],
            total=Decimal("4.99"),
            date=date(2026, 4, 30),
            source="pdf",
        )
        bot.receipt_handler.process_pdf_bytes = MagicMock(return_value=parsed_receipt)
        bot.receipt_handler.validate_receipt = MagicMock(
            return_value=(True, Decimal("0"))
        )

        await bot.handle_receipt_message(message)

        bot.receipt_handler.process_pdf_bytes.assert_called_once()
        bot.actual_connector.save_receipt_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_attachment_does_nothing(self, bot):
        """Test that a message without attachments is ignored."""
        message = AsyncMock(spec=discord.Message)
        message.attachments = []

        await bot.handle_receipt_message(message)

        bot.actual_connector.save_receipt_transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_processing_error_sends_error_reaction(self, bot):
        """Test that a processing error results in error reaction."""
        message = AsyncMock(spec=discord.Message)
        message.created_at = MagicMock()
        message.created_at.date.return_value = date(2026, 4, 30)
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename = "bad.jpg"
        attachment.read = AsyncMock(return_value=b"bad_data")
        message.attachments = [attachment]

        bot.receipt_handler.process_image_bytes = MagicMock(
            side_effect=ReceiptProcessingError("OCR returned empty text")
        )

        await bot.handle_receipt_message(message)

        message.add_reaction.assert_called_with("❌")

    @pytest.mark.asyncio
    async def test_unsupported_file_ignored(self, bot):
        """Test that non-image/non-PDF files are ignored."""
        message = AsyncMock(spec=discord.Message)
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename = "document.docx"
        message.attachments = [attachment]

        await bot.handle_receipt_message(message)

        bot.actual_connector.save_receipt_transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_mismatch_sends_warning_reaction(self, bot):
        """Test that a sum mismatch results in warning reaction."""
        message = AsyncMock(spec=discord.Message)
        message.created_at = MagicMock()
        message.created_at.date.return_value = date(2026, 4, 30)
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename = "receipt.jpg"
        attachment.read = AsyncMock(return_value=b"image_bytes")
        message.attachments = [attachment]

        parsed_receipt = ParsedReceipt(
            store_name="Store",
            items=[
                ReceiptItem("Item1", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
            ],
            total=Decimal("15.00"),  # 5 PLN mismatch
            date=date(2026, 4, 30),
            source="photo",
        )
        bot.receipt_handler.process_image_bytes = MagicMock(return_value=parsed_receipt)
        bot.receipt_handler.validate_receipt = MagicMock(
            return_value=(False, Decimal("5.00"))
        )

        await bot.handle_receipt_message(message)

        message.add_reaction.assert_called_with("⚠️")
        bot.actual_connector.save_receipt_transaction.assert_called_once()
        # Check that warning is in the reply
        reply_text = message.reply.call_args[0][0]
        assert "mismatch" in reply_text.lower()

    @pytest.mark.asyncio
    async def test_no_filename_extension_ignored(self, bot):
        """Test that attachments without extensions are skipped."""
        message = AsyncMock(spec=discord.Message)
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename = "no_extension"
        message.attachments = [attachment]

        await bot.handle_receipt_message(message)

        bot.actual_connector.save_receipt_transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_unexpected_error_sends_generic_message(self, bot):
        """Test that an unexpected error sends a generic error message."""
        message = AsyncMock(spec=discord.Message)
        message.created_at = MagicMock()
        message.created_at.date.return_value = date(2026, 4, 30)
        message.id = 12345
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename = "receipt.jpg"
        attachment.read = AsyncMock(return_value=b"image_bytes")
        message.attachments = [attachment]

        bot.receipt_handler.process_image_bytes = MagicMock(
            side_effect=RuntimeError("Unexpected failure")
        )

        await bot.handle_receipt_message(message)

        message.add_reaction.assert_called_with("❌")
        reply_text = message.reply.call_args[0][0]
        assert "unexpected error" in reply_text.lower()

    @pytest.mark.asyncio
    async def test_no_receipt_handler_does_nothing(self):
        """Test that handle_receipt_message is a no-op when no handler configured."""
        config = DiscordConfig(
            token="token",
            bank_notification_channel="bank-notifications",
            receipt_channel="receipts",
        )
        mock_actual_connector = MagicMock()
        bot = ActualDiscordBot(config, mock_actual_connector, receipt_handler=None)

        message = AsyncMock(spec=discord.Message)
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename = "receipt.jpg"
        message.attachments = [attachment]

        await bot.handle_receipt_message(message)

        mock_actual_connector.save_receipt_transaction.assert_not_called()
