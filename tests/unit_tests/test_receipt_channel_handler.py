from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from actual_discord_bot.channel_handlers.receipts import ReceiptChannelHandler
from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem
from actual_discord_bot.receipts.processor import (
    ReceiptProcessingError,
    ReceiptProcessor,
)


@pytest.fixture
def handler():
    return ReceiptChannelHandler(
        "receipts", MagicMock(), MagicMock(spec=ReceiptProcessor)
    )


@pytest.fixture
def message():
    value = AsyncMock(spec=discord.Message)
    value.id = 1
    value.created_at.date.return_value = date(2026, 4, 30)
    attachment = MagicMock(spec=discord.Attachment, filename="receipt.jpg")
    attachment.read = AsyncMock(return_value=b"image")
    value.attachments = [attachment]
    return value


def _receipt() -> ParsedReceipt:
    return ParsedReceipt(
        "Store",
        [ReceiptItem("Item", Decimal("1"), Decimal("10"), Decimal("10"))],
        Decimal("10"),
        date(2026, 4, 30),
    )


@pytest.mark.asyncio
async def test_image_receipt_is_processed_and_saved(handler, message):
    handler.receipt_processor.process_image_bytes.return_value = _receipt()
    handler.receipt_processor.validate_receipt.return_value = (True, Decimal("0"))
    handler.actual_connector.save_receipt_transaction.return_value = True
    await handler.handle(message)
    handler.receipt_processor.process_image_bytes.assert_called_once()
    handler.actual_connector.save_receipt_transaction.assert_called_once()
    message.add_reaction.assert_awaited_with("✅")


@pytest.mark.asyncio
async def test_pdf_receipt_is_processed(handler, message):
    message.attachments[0].filename = "receipt.pdf"
    handler.receipt_processor.process_pdf_bytes.return_value = _receipt()
    handler.receipt_processor.validate_receipt.return_value = (True, Decimal("0"))
    handler.actual_connector.save_receipt_transaction.return_value = True
    await handler.handle(message)
    handler.receipt_processor.process_pdf_bytes.assert_called_once()


@pytest.mark.asyncio
async def test_unsupported_or_missing_attachment_is_ignored(handler, message):
    message.attachments = []
    await handler.handle(message)
    handler.actual_connector.save_receipt_transaction.assert_not_called()


@pytest.mark.asyncio
async def test_size_limit_is_checked_before_download(handler, message):
    message.attachments[0].size = 10 * 1024 * 1024 + 1
    await handler.handle(message)
    message.attachments[0].read.assert_not_awaited()
    message.add_reaction.assert_awaited_with("❌")


@pytest.mark.asyncio
async def test_validation_mismatch_warns_without_saving(handler, message):
    handler.receipt_processor.process_image_bytes.return_value = _receipt()
    handler.receipt_processor.validate_receipt.return_value = (False, Decimal("1"))
    await handler.handle(message)
    message.add_reaction.assert_awaited_with("⚠️")
    handler.actual_connector.save_receipt_transaction.assert_not_called()


@pytest.mark.asyncio
async def test_processing_error_is_translated_to_discord_reply(handler, message):
    handler.receipt_processor.process_image_bytes.side_effect = ReceiptProcessingError(
        "bad OCR"
    )
    await handler.handle(message)
    message.add_reaction.assert_awaited_with("❌")
    assert "bad OCR" in message.reply.call_args.args[0]
