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

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
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
            file_bytes = await attachment.read()
            suffix = "." + attachment.filename.rsplit(".", 1)[-1].lower()
            fallback_date = message.created_at.date()

            if suffix in PDF_EXTENSIONS:
                receipt = self.receipt_handler.process_pdf_bytes(
                    file_bytes, fallback_date
                )
            elif suffix in IMAGE_EXTENSIONS:
                receipt = self.receipt_handler.process_image_bytes(
                    file_bytes, fallback_date
                )
            else:
                return

            is_valid, diff = self.receipt_handler.validate_receipt(receipt)
            self.actual_connector.save_receipt_transaction(receipt, fallback_date)

            items_summary = ", ".join(
                f"{item.name} ({item.total_price})"
                for item in receipt.items[:MAX_ITEMS_IN_SUMMARY]
            )
            more = (
                f" +{len(receipt.items) - MAX_ITEMS_IN_SUMMARY} more"
                if len(receipt.items) > MAX_ITEMS_IN_SUMMARY
                else ""
            )

            if is_valid:
                await message.add_reaction(REACTION_EMOJI)
            else:
                await message.add_reaction(REACTION_WARNING)

            warning = (
                f"\n⚠️ Sum mismatch: items total differs from receipt by {diff} PLN"
                if not is_valid
                else ""
            )
            await message.reply(
                f"Created split transaction: **{receipt.store_name}**, "
                f"{len(receipt.items)} items, {receipt.total} PLN\n"
                f"Items: {items_summary}{more}{warning}",
            )

        except ReceiptProcessingError as e:
            await message.add_reaction(REACTION_ERROR)
            await message.reply(f"Could not process receipt: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"Error processing receipt from message {message.id}: {e}")
            await message.add_reaction(REACTION_ERROR)
            await message.reply(
                "An unexpected error occurred while processing the receipt."
            )

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
