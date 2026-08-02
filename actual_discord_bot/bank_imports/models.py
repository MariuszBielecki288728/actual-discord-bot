"""Immutable values exchanged by the bank CSV import workflow."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class BankImportTransaction:
    """One bank2ynab-normalized transaction ready for Actual."""

    date: date
    amount: Decimal
    payee: str | None
    memo: str | None
    upstream_import_id: str


@dataclass(frozen=True)
class ConvertedBankStatement:
    """A successful conversion of one uploaded bank statement."""

    bank_format: str
    original_filename: str
    transactions: tuple[BankImportTransaction, ...]


@dataclass(frozen=True)
class ImportableActualAccount:
    """An open Actual account that may receive an imported statement."""

    name: str
    off_budget: bool


@dataclass(frozen=True)
class BankImportResult:
    """Aggregate result of one idempotent Actual import."""

    created_count: int
    duplicate_count: int
