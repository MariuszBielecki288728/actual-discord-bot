"""Discord workflow for private, one-file bank CSV imports."""

import asyncio
import logging
from zoneinfo import ZoneInfo

import discord

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.bank_imports.account_matcher import match_account
from actual_discord_bot.bank_imports.caption import (
    BankImportCaptionError,
    calendar_month_window,
    parse_month_caption,
)
from actual_discord_bot.bank_imports.converter import (
    MAX_BANK_ATTACHMENT_BYTES,
    REASON_ATTACHMENT_TOO_LARGE,
    BankStatementConversionError,
    BankStatementConverter,
)
from actual_discord_bot.bank_imports.models import ImportableActualAccount
from actual_discord_bot.channel_handlers.base import (
    SUCCESS_REACTION,
    BaseChannelHandler,
)

LOGGER = logging.getLogger(__name__)
REACTION_ERROR = "❌"
REACTION_WARNING = "⚠️"
PROCESSING_REACTION = "⏳"
ACCOUNT_SELECTION_TIMEOUT_SECONDS = 5 * 60
ACCOUNTS_PER_PAGE = 25
REASON_ATTACHMENT_COUNT = "attachment_count"
REASON_NO_OPEN_ACCOUNTS = "no_open_accounts"

BANK_IMPORT_HELP_MESSAGE = """👋 **Bank CSV import**

Post exactly one bank-statement CSV, retaining the filename supplied by your bank. An empty caption imports the current calendar month through today; alternatively use `1 months` through `24 months`. Pekao exports must be created **without** the optional category column.

I will select an unambiguous open Actual account automatically, or ask the uploader to choose one. Existing transactions are never changed; the reply contains only aggregate import counts. Bank statements are sensitive: keep this channel private and visible only to people you trust.

**Commands**
`!help` — show this guide
`!catch_up [X hour(s)|X day(s)|X month(s)]` — reprocess bank-statement messages in this channel
`!clear_channel` — permanently delete all deletable messages in this watched channel. Requires your Manage Messages permission."""


class AccountSelectionView(discord.ui.View):
    """A paginated account picker restricted to the original uploader."""

    def __init__(self, author_id: int, accounts: tuple[ImportableActualAccount, ...]) -> None:
        super().__init__(timeout=ACCOUNT_SELECTION_TIMEOUT_SECONDS)
        self.author_id = author_id
        self.accounts = accounts
        self.page = 0
        self.selected: ImportableActualAccount | None = None
        self.message: discord.Message | None = None
        self._render_page()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the uploader can select an import account.", ephemeral=True
        )
        return False

    def _render_page(self) -> None:
        self.clear_items()
        first = self.page * ACCOUNTS_PER_PAGE
        options = [
            discord.SelectOption(
                label=account.name[:100],
                description="Off-budget account" if account.off_budget else "On-budget account",
                value=str(index),
            )
            for index, account in enumerate(
                self.accounts[first : first + ACCOUNTS_PER_PAGE], start=first
            )
        ]
        select: discord.ui.Select = discord.ui.Select(
            placeholder="Choose an Actual account", options=options
        )
        select.callback = self._select_account  # type: ignore[method-assign]
        self.add_item(select)
        if self.page:
            previous: discord.ui.Button = discord.ui.Button(
                label="Previous", style=discord.ButtonStyle.secondary
            )
            previous.callback = self._previous_page  # type: ignore[method-assign]
            self.add_item(previous)
        if (self.page + 1) * ACCOUNTS_PER_PAGE < len(self.accounts):
            next_page: discord.ui.Button = discord.ui.Button(
                label="Next", style=discord.ButtonStyle.secondary
            )
            next_page.callback = self._next_page  # type: ignore[method-assign]
            self.add_item(next_page)
        cancel: discord.ui.Button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.danger
        )
        cancel.callback = self._cancel  # type: ignore[method-assign]
        self.add_item(cancel)

    async def _select_account(self, interaction: discord.Interaction) -> None:
        select = next(item for item in self.children if isinstance(item, discord.ui.Select))
        self.selected = self.accounts[int(select.values[0])]
        self.disable_all_items()  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _previous_page(self, interaction: discord.Interaction) -> None:
        self.page -= 1
        self._render_page()
        await interaction.response.edit_message(view=self)

    async def _next_page(self, interaction: discord.Interaction) -> None:
        self.page += 1
        self._render_page()
        await interaction.response.edit_message(view=self)

    async def _cancel(self, interaction: discord.Interaction) -> None:
        self.disable_all_items()  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self) -> None:
        self.disable_all_items()  # type: ignore[attr-defined]
        if self.message is not None:
            await self.message.edit(view=self)


class BankImportChannelHandler(BaseChannelHandler):
    """Validate, convert, select an account, and import one uploaded CSV."""

    def __init__(
        self,
        channel_name: str,
        actual_connector: ActualConnector,
        timezone: ZoneInfo,
        converter: BankStatementConverter | None = None,
        processing_slots: int = 1,
        actual_write_lock: asyncio.Lock | None = None,
    ) -> None:
        super().__init__(channel_name, BANK_IMPORT_HELP_MESSAGE)
        self.actual_connector = actual_connector
        self.timezone = timezone
        self.converter = converter or BankStatementConverter()
        self.processing_slots = asyncio.Semaphore(processing_slots)
        self.actual_write_lock = actual_write_lock
        self.approved_accounts: dict[tuple[int, str], str] = {}

    def accepts(self, message: discord.Message) -> bool:
        return any(attachment.filename.lower().endswith(".csv") for attachment in message.attachments)

    async def handle(self, message: discord.Message) -> None:
        processing_added = False
        try:
            attachment = self._validated_attachment(message)
            months = parse_month_caption(message.content)
            attachment_size = getattr(attachment, "size", None)
            if isinstance(attachment_size, int) and attachment_size > MAX_BANK_ATTACHMENT_BYTES:
                self._raise_attachment_too_large()
            await message.add_reaction(PROCESSING_REACTION)
            processing_added = True
            file_bytes = await attachment.read()
            if len(file_bytes) > MAX_BANK_ATTACHMENT_BYTES:
                self._raise_attachment_too_large()
            async with self.processing_slots:
                statement = await self.converter.convert(attachment.filename, file_bytes)
            lower_bound, upper_bound = calendar_month_window(months, self.timezone)
            eligible = tuple(
                row
                for row in statement.transactions
                if lower_bound <= row.date <= upper_bound
            )
            out_of_window = len(statement.transactions) - len(eligible)
            if not eligible:
                await self._finish(message, processing_added, REACTION_WARNING)
                await message.reply(
                    "The statement converted successfully, but contains no transactions "
                    "in the requested date interval. Nothing was imported."
                )
                return
            accounts = await asyncio.to_thread(self.actual_connector.list_import_accounts)
            account = await self._choose_account(message, statement.bank_format, accounts)
            if account is None:
                await self._finish(message, processing_added, REACTION_ERROR)
                await message.reply("Bank import was cancelled or account selection expired.")
                return
            if self.actual_write_lock is None:
                result = await asyncio.to_thread(
                    self.actual_connector.import_bank_transactions,
                    account.name,
                    statement.bank_format,
                    eligible,
                )
            else:
                async with self.actual_write_lock:
                    result = await asyncio.to_thread(
                        self.actual_connector.import_bank_transactions,
                        account.name,
                        statement.bank_format,
                        eligible,
                    )
            await self._finish(message, processing_added, SUCCESS_REACTION)
            await message.reply(
                "Bank CSV import completed. "
                f"Format: **{statement.bank_format}**; account: **{account.name}**; "
                f"interval: {lower_bound.isoformat()} through {upper_bound.isoformat()}; "
                f"converted: {len(statement.transactions)}; outside interval: {out_of_window}; "
                f"created: {result.created_count}; existing skipped: {result.duplicate_count}."
            )
        except BankImportCaptionError:
            await self._finish(message, processing_added, REACTION_ERROR)
            await message.reply("Caption must be empty or exactly `1` through `24 months`.")
        except BankStatementConversionError as error:
            await self._finish(message, processing_added, REACTION_ERROR)
            await message.reply(_conversion_error_message(error.reason))
        except ValueError:
            LOGGER.exception("Actual bank import failed for message %s", message.id)
            await self._finish(message, processing_added, REACTION_ERROR)
            await message.reply("The selected Actual account is no longer available. Nothing was imported.")
        except Exception:
            LOGGER.exception("Bank CSV import failed for message %s", message.id)
            await self._finish(message, processing_added, REACTION_ERROR)
            await message.reply("Bank import failed. Nothing was imported.")

    async def _choose_account(
        self,
        message: discord.Message,
        bank_format: str,
        accounts: tuple[ImportableActualAccount, ...],
    ) -> ImportableActualAccount | None:
        if not accounts:
            raise BankStatementConversionError(REASON_NO_OPEN_ACCOUNTS)
        cache_key = (message.author.id, bank_format)
        cached_name = self.approved_accounts.get(cache_key)
        if cached_name:
            cached = next((account for account in accounts if account.name == cached_name), None)
            if cached is not None:
                return cached
        automatic = match_account(bank_format, accounts)
        if automatic is not None:
            return automatic
        view = AccountSelectionView(message.author.id, accounts)
        view.message = await message.reply("Select the Actual account for this import.", view=view)
        timed_out = await view.wait()
        if timed_out or view.selected is None:
            return None
        self.approved_accounts[cache_key] = view.selected.name
        return view.selected

    @staticmethod
    def _validated_attachment(message: discord.Message) -> discord.Attachment:
        if len(message.attachments) != 1 or not message.attachments[0].filename.lower().endswith(".csv"):
            raise BankStatementConversionError(REASON_ATTACHMENT_COUNT)
        return message.attachments[0]

    @staticmethod
    def _raise_attachment_too_large() -> None:
        raise BankStatementConversionError(REASON_ATTACHMENT_TOO_LARGE)

    async def _finish(
        self, message: discord.Message, processing_added: bool, reaction: str
    ) -> None:
        if processing_added:
            try:
                guild = message.guild
                if guild is not None:
                    await message.remove_reaction(PROCESSING_REACTION, guild.me)
            except (AttributeError, discord.HTTPException):
                LOGGER.debug("Could not remove bank import processing reaction")
        await message.add_reaction(reaction)


def _conversion_error_message(reason: str) -> str:
    messages = {
        "attachment_count": "Attach exactly one CSV file and no other attachments.",
        "attachment_too_large": "Bank CSV attachment exceeds the 10 MiB limit.",
        "invalid_filename": "The attachment filename is invalid. Keep the original bank filename.",
        "unmatched_filename": "The original filename does not match a supported bank format.",
        "unsupported_layout": "This filename is recognized, but its CSV layout is unsupported. Pekao exports with `Kategoria` are not supported; export without categories.",
        "ambiguous_format": "The filename matches more than one supported bank format.",
        "no_transactions": "The statement was recognized but did not contain valid transactions.",
        "timeout": "Bank CSV conversion timed out.",
        "no_open_accounts": "There are no open Actual accounts available for import.",
    }
    return messages.get(reason, "Bank CSV conversion failed.")
