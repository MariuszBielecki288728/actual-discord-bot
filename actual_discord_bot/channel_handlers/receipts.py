"""Discord workflow for receipt attachments."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import date

import discord

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.channel_handlers.base import (
    SUCCESS_REACTION,
    BaseChannelHandler,
    format_unexpected_error,
)
from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem
from actual_discord_bot.receipts.processor import (
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    ReceiptProcessingError,
    ReceiptProcessor,
)

LOGGER = logging.getLogger(__name__)
REACTION_ERROR = "❌"
REACTION_WARNING = "⚠️"
MAX_ITEMS_IN_SUMMARY = 5
MAX_RECEIPT_ATTACHMENT_BYTES = 10 * 1024 * 1024

RECEIPT_HELP_MESSAGE = """👋 **Hello! I am your Actual Budget receipt assistant.**

Attach one JPG, JPEG, PNG, WebP, or PDF receipt to this channel (maximum 10 MB). I extract the merchant, date, total, and product lines, then create one split transaction in Actual Budget.

I react with ✅ and reply with a summary when a transaction is created. ⚠️ means I found a likely duplicate or the extracted item totals did not match the receipt total, so nothing was saved. ❌ means processing failed. Image text is read with OCR and may be imperfect; use a sharp, evenly lit, straight-on photo and always verify the result in Actual Budget. I ignore ordinary text and unsupported attachments.

**Commands**
`!help` — show this receipt guide
`!clear_channel` — permanently delete all deletable messages in this watched channel. Requires your Manage Messages permission.

Receipts may contain sensitive information, so only post them in a private channel that is visible to people you trust."""


class ReceiptChannelHandler(BaseChannelHandler):
    """Process supported receipt attachments posted in one Discord channel."""

    def __init__(
        self,
        channel_name: str,
        actual_connector: ActualConnector,
        receipt_processor: ReceiptProcessor,
        processing_slots: int = 1,
        actual_write_lock: asyncio.Lock | None = None,
        show_error_tracebacks: bool = True,
    ) -> None:
        super().__init__(channel_name, RECEIPT_HELP_MESSAGE)
        self.actual_connector = actual_connector
        self.receipt_processor = receipt_processor
        self.actual_write_lock = actual_write_lock
        self.show_error_tracebacks = show_error_tracebacks
        self.processing_slots = asyncio.Semaphore(processing_slots)

    def accepts(self, message: discord.Message) -> bool:
        return self._get_receipt_attachment(message) is not None

    async def handle(self, message: discord.Message) -> None:
        attachment = self._get_receipt_attachment(message)
        if attachment is None:
            return
        try:
            attachment_size = getattr(attachment, "size", None)
            if (
                isinstance(attachment_size, int)
                and attachment_size > MAX_RECEIPT_ATTACHMENT_BYTES
            ):
                self._raise_attachment_too_large()
            async with self.processing_slots:
                await self._process_attachment(message, attachment)
        except ReceiptProcessingError as error:
            await message.add_reaction(REACTION_ERROR)
            await message.reply(f"Could not process receipt: {error}")
        except Exception as error:
            LOGGER.exception("Error processing receipt from message %s", message.id)
            await message.add_reaction(REACTION_ERROR)
            await message.reply(
                format_unexpected_error(
                    "An unexpected error occurred while processing the receipt.",
                    error,
                    show_traceback=self.show_error_tracebacks,
                )
            )

    async def _process_attachment(
        self, message: discord.Message, attachment: discord.Attachment
    ) -> None:
        file_bytes = await attachment.read()
        if len(file_bytes) > MAX_RECEIPT_ATTACHMENT_BYTES:
            self._raise_attachment_too_large()
        suffix = "." + attachment.filename.rsplit(".", 1)[-1].lower()
        fallback_date = message.created_at.date()
        if suffix in PDF_EXTENSIONS:
            receipt = await asyncio.to_thread(
                self.receipt_processor.process_pdf_bytes, file_bytes, fallback_date
            )
        else:
            receipt = await asyncio.to_thread(
                self.receipt_processor.process_image_bytes, file_bytes, fallback_date
            )

        is_valid, diff = self.receipt_processor.validate_receipt(receipt)
        items_summary = _format_items_summary(receipt.items)
        if not is_valid:
            await message.add_reaction(REACTION_WARNING)
            await message.reply(
                "Receipt was not saved because of an item-total mismatch: "
                f"the receipt total differs by {diff} PLN.\nItems: {items_summary}"
            )
            return

        created = await self._save_receipt(receipt, fallback_date)
        if not created:
            await message.add_reaction(REACTION_WARNING)
            await message.reply(
                f"Receipt already exists: **{receipt.store_name}**, "
                f"{receipt.total} PLN. No transaction was created."
            )
            return
        await message.add_reaction(SUCCESS_REACTION)
        await message.reply(
            f"Created split transaction: **{receipt.store_name}**, "
            f"{len(receipt.items)} items, {receipt.total} PLN\nItems: {items_summary}"
        )

    async def _save_receipt(self, receipt: ParsedReceipt, fallback_date: date) -> bool:
        if self.actual_write_lock is None:
            return await asyncio.to_thread(
                self.actual_connector.save_receipt_transaction, receipt, fallback_date
            )
        async with self.actual_write_lock:
            return await asyncio.to_thread(
                self.actual_connector.save_receipt_transaction, receipt, fallback_date
            )

    @staticmethod
    def _get_receipt_attachment(
        message: discord.Message,
    ) -> discord.Attachment | None:
        for attachment in message.attachments:
            if "." not in attachment.filename:
                continue
            suffix = "." + attachment.filename.rsplit(".", 1)[-1].lower()
            if suffix in IMAGE_EXTENSIONS or suffix in PDF_EXTENSIONS:
                return attachment
        return None

    @staticmethod
    def _raise_attachment_too_large() -> None:
        msg = "Receipt attachment exceeds the 10 MB limit."
        raise ReceiptProcessingError(msg)


def _format_items_summary(items: Sequence[ReceiptItem]) -> str:
    summary = ", ".join(
        f"{item.name} ({item.total_price})" for item in items[:MAX_ITEMS_IN_SUMMARY]
    )
    if len(items) > MAX_ITEMS_IN_SUMMARY:
        return f"{summary} +{len(items) - MAX_ITEMS_IN_SUMMARY} more"
    return summary
