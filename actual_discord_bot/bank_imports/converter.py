"""Parent-side, bounded subprocess adapter for bank2ynab."""

import asyncio
import json
import os
import sys
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from actual_discord_bot.bank_imports.models import (
    BankImportTransaction,
    ConvertedBankStatement,
)

MAX_BANK_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_CONVERTED_ROWS = 50_000
MAX_WORKER_OUTPUT_BYTES = 8 * 1024 * 1024
CONVERSION_TIMEOUT_SECONDS = 30
WORKER_SCHEMA_VERSION = 1
ASCII_CONTROL_CHARACTER_LIMIT = 32
REASON_ATTACHMENT_TOO_LARGE = "attachment_too_large"
REASON_INVALID_FILENAME = "invalid_filename"
REASON_INVALID_OUTPUT = "invalid_output"
REASON_TIMEOUT = "timeout"


class BankStatementConversionError(ValueError):
    """A conversion failure that is safe to translate for Discord users."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BankStatementConverter:
    """Run the pinned bank2ynab revision in a request-scoped temporary directory."""

    async def convert(self, filename: str, file_bytes: bytes) -> ConvertedBankStatement:
        """Convert one attachment while preserving its original safe basename."""
        safe_filename = _validate_filename(filename)
        if len(file_bytes) > MAX_BANK_ATTACHMENT_BYTES:
            raise BankStatementConversionError(REASON_ATTACHMENT_TOO_LARGE)
        with tempfile.TemporaryDirectory(prefix="actual-bank-import-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            input_directory = temporary_path / "input"
            config_directory = temporary_path / "config"
            input_directory.mkdir()
            config_directory.mkdir()
            (input_directory / safe_filename).write_bytes(file_bytes)
            _write_user_configuration(config_directory, input_directory)
            result = await self._run_worker(config_directory)
        return _decode_worker_result(result, safe_filename)

    async def _run_worker(self, config_directory: Path) -> dict[str, Any]:
        environment = os.environ.copy()
        environment["BANK2YNAB_CONFIG_DIR"] = str(config_directory)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "actual_discord_bot.bank_imports.bank2ynab_worker",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=environment,
            limit=MAX_WORKER_OUTPUT_BYTES,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=CONVERSION_TIMEOUT_SECONDS
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise BankStatementConversionError(REASON_TIMEOUT) from error
        if len(stdout) > MAX_WORKER_OUTPUT_BYTES:
            raise BankStatementConversionError(REASON_INVALID_OUTPUT)
        try:
            decoded = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BankStatementConversionError(REASON_INVALID_OUTPUT) from error
        if process.returncode != 0 or not isinstance(decoded, dict):
            raise BankStatementConversionError(REASON_INVALID_OUTPUT)
        return decoded


def _validate_filename(filename: str) -> str:
    safe_filename = Path(filename).name
    if (
        not safe_filename
        or safe_filename in {".", ".."}
        or any(character.isspace() and character in "\r\n\t" for character in safe_filename)
        or any(ord(character) < ASCII_CONTROL_CHARACTER_LIMIT for character in safe_filename)
    ):
        raise BankStatementConversionError(REASON_INVALID_FILENAME)
    return safe_filename


def _write_user_configuration(config_directory: Path, input_directory: Path) -> None:
    (config_directory / "user_configuration.conf").write_text(
        "[DEFAULT]\n"
        f"Source Path = {input_directory}\n"
        "YNAB API Access Token =\n"
        "Delete Source File = False\n"
        "Save Output File = False\n"
        "Log Level = ERROR\n",
        encoding="utf-8",
    )


def _decode_worker_result(
    result: dict[str, Any], original_filename: str
) -> ConvertedBankStatement:
    if result.get("schema_version") != WORKER_SCHEMA_VERSION:
        raise BankStatementConversionError(REASON_INVALID_OUTPUT)
    status = result.get("status")
    if status != "converted":
        if status in {
            "unmatched_filename",
            "unsupported_layout",
            "ambiguous_format",
            "no_transactions",
            "conversion_failed",
        }:
            raise BankStatementConversionError(status)
        raise BankStatementConversionError(REASON_INVALID_OUTPUT)
    bank_format = result.get("bank_format")
    rows = result.get("transactions")
    if (
        result.get("files_processed") != 1
        or not isinstance(bank_format, str)
        or not bank_format.strip()
        or not isinstance(rows, list)
        or not rows
        or len(rows) > MAX_CONVERTED_ROWS
    ):
        raise BankStatementConversionError(REASON_INVALID_OUTPUT)
    try:
        transactions = tuple(_decode_transaction(row) for row in rows)
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise BankStatementConversionError(REASON_INVALID_OUTPUT) from error
    return ConvertedBankStatement(
        bank_format=bank_format.strip(),
        original_filename=original_filename,
        transactions=transactions,
    )


def _decode_transaction(row: object) -> BankImportTransaction:
    if not isinstance(row, dict):
        raise TypeError
    milliunits = Decimal(str(row["amount_milliunits"]))
    amount = milliunits / Decimal(1000)
    if amount != amount.quantize(Decimal("0.01")):
        msg = "amount is not representable in cents"
        raise ValueError(msg)
    source_date = date.fromisoformat(str(row["date"]))
    upstream_import_id = row["upstream_import_id"]
    if not isinstance(upstream_import_id, str) or not upstream_import_id.strip():
        msg = "missing upstream import id"
        raise ValueError(msg)
    return BankImportTransaction(
        date=source_date,
        amount=amount,
        payee=_normalized_optional_text(row.get("payee")),
        memo=_normalized_optional_text(row.get("memo")),
        upstream_import_id=upstream_import_id.strip(),
    )


def _normalized_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError
    return value.strip() or None
