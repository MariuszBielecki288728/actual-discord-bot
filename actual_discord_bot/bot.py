import asyncio

import discord
from cogwatch import watch
from discord.ext import commands

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.bank_notifications import PekaoNotification
from actual_discord_bot.config import ActualConfig, DiscordConfig
from actual_discord_bot.errors import ParseNotificationError
from actual_discord_bot.receipts.handler import (
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    ReceiptHandler,
    ReceiptProcessingError,
)
from actual_discord_bot.receipts.ocr_provider import OCRConfig, create_ocr_provider

REACTION_EMOJI = "✅"
REACTION_ERROR = "❌"
REACTION_WARNING = "⚠️"
MAX_ITEMS_IN_SUMMARY = 5
MAX_RECEIPT_ATTACHMENT_BYTES = 10 * 1024 * 1024

HELP_MESSAGE = """**Actual Budget bot — channel guide**

I turn messages in the configured bank-notification channel into Actual Budget transactions. Currently I understand Bank Pekao card payments, incoming and outgoing transfers, and phone top-ups forwarded in this format:
```
Title: <notification title>
Text: <notification text>
Timestamp: <timestamp>
```
A ✅ means the transaction was saved. A message without ✅ was not imported; check the bot logs, correct the message if needed, and run `!catch_up`.

In the configured receipts channel, attach one JPG, JPEG, PNG, WebP, or PDF receipt (maximum 10 MB). I extract the merchant, date, total, and items, then create one split transaction. I reply with the result and react with ✅ when created, ⚠️ for a duplicate or totals mismatch, and ❌ when processing fails. Receipt OCR is best-effort, so verify imported transactions in Actual Budget.

**Commands**
`!help` — show this guide
`!catch_up` — retry every bank-channel message that does not already have my ✅

Commands may be sent in either configured channel. I ignore other text in the receipts channel and unsupported attachments. Never post Actual or Discord passwords in a channel."""

STARTUP_MESSAGE = (
    "I am online and watching this channel. Here is how to use me:\n\n" + HELP_MESSAGE
)


class ActualDiscordBot(commands.Bot):
    def __init__(
        self,
        config: DiscordConfig,
        actual_connector: ActualConnector,
        receipt_handler: ReceiptHandler | None = None,
    ) -> None:
        self.channel_name = config.bank_notification_channel
        self.receipt_channel_name = config.receipt_channel
        self.actual_connector = actual_connector
        self.receipt_handler = receipt_handler
        self.receipt_processing_slots = asyncio.Semaphore(1)
        self._startup_help_sent = False

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.target_channel: discord.TextChannel | None = None
        self.receipt_target_channel: discord.TextChannel | None = None

    @watch(path="actual_discord_bot")
    async def on_ready(self) -> None:
        for guild in self.guilds:
            channel = discord.utils.get(guild.channels, name=self.channel_name)
            if channel:
                self.target_channel = channel
            if self.receipt_channel_name:
                receipt_channel = discord.utils.get(
                    guild.channels, name=self.receipt_channel_name
                )
                if receipt_channel:
                    self.receipt_target_channel = receipt_channel
            if self.target_channel:
                break
        if not self.target_channel:
            print(f"Warning: Could not find channel '{self.channel_name}'")

        if not self._startup_help_sent:
            await self._send_startup_help()
            self._startup_help_sent = True

    async def _send_startup_help(self) -> None:
        """Announce the bot once per process in every configured channel found."""
        channels = {channel.id: channel for channel in self._followed_channels()}
        for channel in channels.values():
            try:
                await channel.send(STARTUP_MESSAGE)
            except (discord.Forbidden, discord.HTTPException) as error:
                print(f"Could not send startup help to '{channel.name}': {error}")

    def _followed_channels(self) -> tuple[discord.TextChannel, ...]:
        return tuple(
            channel
            for channel in (self.target_channel, self.receipt_target_channel)
            if channel is not None
        )

    async def create_actual_transaction(self, message: discord.Message) -> bool:
        try:
            notification = PekaoNotification.from_message(message.content)
            transaction_data = notification.to_transaction()
            self.actual_connector.save_transaction(transaction_data)
        except ParseNotificationError:
            print(
                f"ParseNotificationError: Could not parse message {message.id} with content: {message.content}",
            )
            return False
        except Exception as e:  # noqa: BLE001
            print(f"Exception occurred while processing message {message.id}: {e}")
            print(
                f"Error processing message {message.id} with content {message.content}: {e}",
            )
            return False
        else:
            return True

    async def handle_message(self, message: discord.Message) -> None:
        if await self.create_actual_transaction(message):
            await message.add_reaction(REACTION_EMOJI)

    async def handle_receipt_message(self, message: discord.Message) -> None:
        """Handle a receipt image/PDF posted to the receipts channel."""
        if not self.receipt_handler:
            return

        attachment = self._get_receipt_attachment(message)
        if not attachment:
            return

        try:
            attachment_size = getattr(attachment, "size", None)
            if (
                isinstance(attachment_size, int)
                and attachment_size > MAX_RECEIPT_ATTACHMENT_BYTES
            ):
                self._raise_attachment_too_large()

            async with self.receipt_processing_slots:
                await self._process_receipt_attachment(message, attachment)

        except ReceiptProcessingError as e:
            await message.add_reaction(REACTION_ERROR)
            await message.reply(f"Could not process receipt: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"Error processing receipt from message {message.id}: {e}")
            await message.add_reaction(REACTION_ERROR)
            await message.reply(
                "An unexpected error occurred while processing the receipt."
            )

    async def _process_receipt_attachment(
        self,
        message: discord.Message,
        attachment: discord.Attachment,
    ) -> None:
        """Parse and persist one receipt while the processing slot is held."""
        file_bytes = await attachment.read()
        if len(file_bytes) > MAX_RECEIPT_ATTACHMENT_BYTES:
            self._raise_attachment_too_large()

        suffix = "." + attachment.filename.rsplit(".", 1)[-1].lower()
        fallback_date = message.created_at.date()

        if suffix in PDF_EXTENSIONS:
            receipt = await asyncio.to_thread(
                self.receipt_handler.process_pdf_bytes,
                file_bytes,
                fallback_date,
            )
        elif suffix in IMAGE_EXTENSIONS:
            receipt = await asyncio.to_thread(
                self.receipt_handler.process_image_bytes,
                file_bytes,
                fallback_date,
            )
        else:
            return

        is_valid, diff = self.receipt_handler.validate_receipt(receipt)

        items_summary = ", ".join(
            f"{item.name} ({item.total_price})"
            for item in receipt.items[:MAX_ITEMS_IN_SUMMARY]
        )
        more = (
            f" +{len(receipt.items) - MAX_ITEMS_IN_SUMMARY} more"
            if len(receipt.items) > MAX_ITEMS_IN_SUMMARY
            else ""
        )

        if not is_valid:
            await message.add_reaction(REACTION_WARNING)
            await message.reply(
                "Receipt was not saved because of an item-total mismatch: "
                f"the receipt total differs by {diff} PLN.\n"
                f"Items: {items_summary}{more}",
            )
            return

        created = await asyncio.to_thread(
            self.actual_connector.save_receipt_transaction,
            receipt,
            fallback_date,
        )
        if not created:
            await message.add_reaction(REACTION_WARNING)
            await message.reply(
                f"Receipt already exists: **{receipt.store_name}**, "
                f"{receipt.total} PLN. No transaction was created.",
            )
            return

        await message.add_reaction(REACTION_EMOJI)
        await message.reply(
            f"Created split transaction: **{receipt.store_name}**, "
            f"{len(receipt.items)} items, {receipt.total} PLN\n"
            f"Items: {items_summary}{more}",
        )

    @staticmethod
    def _raise_attachment_too_large() -> None:
        msg = "Receipt attachment exceeds the 10 MB limit."
        raise ReceiptProcessingError(msg)

    @staticmethod
    def _get_receipt_attachment(
        message: discord.Message,
    ) -> discord.Attachment | None:
        """Get the first valid receipt attachment from a message."""
        for attachment in message.attachments:
            if "." not in attachment.filename:
                continue
            suffix = "." + attachment.filename.rsplit(".", 1)[-1].lower()
            if suffix in IMAGE_EXTENSIONS or suffix in PDF_EXTENSIONS:
                return attachment
        return None

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        context = await self.get_context(message)
        if context.valid:
            await self.invoke(context)
            return

        if self.target_channel and message.channel.id == self.target_channel.id:
            await self.handle_message(message)
        elif (
            self.receipt_target_channel
            and message.channel.id == self.receipt_target_channel.id
        ):
            await self.handle_receipt_message(message)

    @commands.command(name="catch_up")
    async def catch_up(self, ctx: commands.Context) -> None:
        if not self.target_channel:
            await ctx.send(f"Error: Channel '{self.channel_name}' not found.")
            return

        async with ctx.typing():
            processed_count = 0
            async for message in self.target_channel.history(limit=None):
                for reaction in message.reactions:
                    if reaction.emoji == REACTION_EMOJI and reaction.me:
                        break
                else:
                    await self.handle_message(message)
                    processed_count += 1

        await ctx.send(f"Catch-up complete. Processed {processed_count} messages.")

    @commands.command(name="help")
    async def help(self, ctx: commands.Context) -> None:
        """Show the same usage guide posted when the bot starts."""
        await ctx.send(HELP_MESSAGE)


async def main() -> None:
    discord_config = DiscordConfig.from_environ()
    actual_config = ActualConfig.from_environ()

    actual_connector = ActualConnector(actual_config)

    receipt_handler = None
    if discord_config.receipt_channel:
        ocr_config = OCRConfig.from_environ()
        ocr_provider = create_ocr_provider(ocr_config)
        receipt_handler = ReceiptHandler(ocr_provider=ocr_provider)

    client = ActualDiscordBot(discord_config, actual_connector, receipt_handler)
    await client.start(discord_config.token)


if __name__ == "__main__":
    asyncio.run(main())
