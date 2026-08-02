import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from actual import Actual
from actual.database import Accounts, Transactions
from actual.queries import (
    create_schedule as create_actual_schedule,
)
from actual.queries import (
    create_schedule_config,
    create_transaction,
    get_account,
    get_payee,
    get_schedules,
    get_transactions,
)
from sqlmodel import select

from actual_discord_bot.bank_imports.models import (
    BankImportResult,
    BankImportTransaction,
    ImportableActualAccount,
)
from actual_discord_bot.config import ActualConfig
from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.errors import ScheduleSourceNotFound
from actual_discord_bot.receipts.models import ParsedReceipt
from actual_discord_bot.receipts.transaction import (
    create_receipt_split_transaction,
    find_matching_transaction,
)
from actual_discord_bot.schedules import ScheduleRecurrence
from actual_discord_bot.transaction_matching import merchant_names_match


class ScheduleCreationStatus(StrEnum):
    """The result of an idempotent schedule creation request."""

    CREATED = "created"
    ALREADY_EXISTS = "already_exists"


@dataclass(frozen=True)
class ActualScheduleData:
    """All project-owned inputs required to create one Actual schedule."""

    start: date
    account: str
    amount: Decimal
    payee: str
    name: str
    recurrence: ScheduleRecurrence


class ActualConnector:
    def __init__(self, config: ActualConfig) -> None:
        self.config = config

    def _create_actual_manager(self) -> Actual:
        """Create one disposable Actual client for a single import operation."""
        return Actual(
            base_url=self.config.url,
            password=self.config.password,
            encryption_password=self.config.encryption_password,
            file=self.config.file,
        )

    def save_transaction(
        self,
        transaction_data: ActualTransactionData,
    ) -> Transactions:
        with self._create_actual_manager() as actual:
            # Receipt imports are expenses. Do not deduplicate a deposit against
            # an expense with the same absolute value.
            if transaction_data.amount < 0:
                existing = find_matching_transaction(
                    actual=actual,
                    amount=Decimal(str(transaction_data.amount)),
                    transaction_date=transaction_data.date,
                    account_name=transaction_data.account,
                    receipt_only=True,
                    expected_payee=transaction_data.imported_payee,
                )
                if existing:
                    return existing

            transaction = create_transaction(
                actual.session,
                date=transaction_data.date,
                account=transaction_data.account,
                amount=transaction_data.amount,
                imported_payee=transaction_data.imported_payee,
            )
            actual.commit()
            actual.session.refresh(transaction)
            actual.session.expunge(transaction)
            return transaction

    def save_receipt_transaction(
        self,
        receipt: ParsedReceipt,
        fallback_date: date | None = None,
    ) -> bool:
        """Create a split transaction from a parsed receipt."""
        with self._create_actual_manager() as actual:
            return create_receipt_split_transaction(
                actual=actual,
                receipt=receipt,
                account_name=self.config.account,
                transaction_date=fallback_date,
            )

    def create_schedule(self, data: ActualScheduleData) -> ScheduleCreationStatus:
        """Create a never-ending, manually approved schedule if its name is new."""
        with self._create_actual_manager() as actual:
            existing = next(
                (
                    schedule
                    for schedule in get_schedules(
                        actual.session,
                        include_completed=True,
                    )
                    if schedule.name
                    and schedule.name.casefold() == data.name.casefold()
                ),
                None,
            )
            if existing is not None:
                return ScheduleCreationStatus.ALREADY_EXISTS

            account = get_account(actual.session, data.account)
            payee = get_payee(actual.session, data.payee)
            if account is None or payee is None:
                raise ScheduleSourceNotFound

            recurrence = create_schedule_config(
                start=data.start,
                interval=data.recurrence.interval,
                frequency=data.recurrence.frequency.value,
                end_mode="never",
                skip_weekend=False,
            )
            create_actual_schedule(
                actual.session,
                date=recurrence,
                amount=data.amount,
                amount_operation="is",
                name=data.name,
                payee=payee,
                account=account,
                posts_transaction=False,
            )
            actual.commit()
            return ScheduleCreationStatus.CREATED

    def list_import_accounts(self) -> tuple[ImportableActualAccount, ...]:
        """Return all currently open accounts available to bank statement imports."""
        with self._create_actual_manager() as actual:
            accounts = actual.session.exec(select(Accounts)).all()
            return tuple(
                ImportableActualAccount(
                    name=account.name,
                    off_budget=bool(account.offbudget),
                )
                for account in accounts
                if isinstance(account.name, str)
                and not bool(account.closed)
                and not bool(account.tombstone)
            )

    def import_bank_transactions(
        self,
        account_name: str,
        bank_format: str,
        transactions: Iterable[BankImportTransaction],
    ) -> BankImportResult:
        """Idempotently create missing bank rows in one Actual commit."""
        rows = tuple(transactions)
        _validate_bank_transactions(rows)
        with self._create_actual_manager() as actual:
            account = _find_open_account(actual, account_name)
            if account is None:
                msg = "Selected Actual account is no longer open"
                raise ValueError(msg)
            existing = _get_import_transactions(actual, account)
            created_count = 0
            duplicate_count = 0
            consumed_candidates: set[int] = set()
            existing_ids = {
                transaction.financial_id
                for transaction in existing
                if isinstance(transaction.financial_id, str)
            }
            for row in rows:
                financial_id = generate_bank_imported_id(
                    bank_format, row.upstream_import_id
                )
                if financial_id in existing_ids or _fallback_duplicate(
                    row, existing, consumed_candidates
                ):
                    duplicate_count += 1
                    continue
                create_transaction(
                    actual.session,
                    date=row.date,
                    account=account,
                    amount=row.amount,
                    imported_id=financial_id,
                    imported_payee=row.payee,
                    notes=row.memo or "",
                    cleared=True,
                )
                existing_ids.add(financial_id)
                created_count += 1
            if created_count:
                actual.commit()
            return BankImportResult(created_count, duplicate_count)


def generate_bank_imported_id(bank_format: str, upstream_import_id: str) -> str:
    """Namespace an upstream YNAB import ID for Actual's financial ID field."""
    content = f"{bank_format}\0{upstream_import_id}".encode()
    return f"bank2ynab:{hashlib.sha256(content).hexdigest()[:32]}"


def _validate_bank_transactions(rows: tuple[BankImportTransaction, ...]) -> None:
    for row in rows:
        if row.amount != row.amount.quantize(Decimal("0.01")):
            msg = "Bank transaction amount must use cent precision"
            raise ValueError(msg)
        if not row.upstream_import_id.strip():
            msg = "Bank transaction requires an upstream import ID"
            raise ValueError(msg)


def _find_open_account(actual: Actual, account_name: str) -> Accounts | None:
    for account in actual.session.exec(select(Accounts)).all():
        if (
            isinstance(account.name, str)
            and account.name == account_name
            and not bool(account.closed)
            and not bool(account.tombstone)
        ):
            return account
    return None


def _get_import_transactions(
    actual: Actual, account: Accounts
) -> tuple[Transactions, ...]:
    """Return ordinary transactions and split parents, excluding split children later."""
    return tuple(get_transactions(actual.session, account=account)) + tuple(
        get_transactions(actual.session, account=account, is_parent=True)
    )


def _fallback_duplicate(
    source: BankImportTransaction,
    existing: tuple[Transactions, ...],
    consumed_candidates: set[int],
) -> bool:
    for candidate in existing:
        if id(candidate) in consumed_candidates or bool(candidate.is_child):
            continue
        if Decimal(str(candidate.amount)) != source.amount:
            continue
        candidate_date = candidate.date
        if not isinstance(candidate_date, date):
            continue
        date_difference = abs((candidate_date - source.date).days)
        if date_difference > 1:
            continue
        if source.payee is None and candidate_date != source.date:
            continue
        if source.payee is not None and not any(
            merchant_names_match(source.payee, value)
            for value in _transaction_merchant_names(candidate)
        ):
            continue
        consumed_candidates.add(id(candidate))
        return True
    return False


def _transaction_merchant_names(transaction: Transactions) -> tuple[str, ...]:
    payee = getattr(transaction, "payee", None)
    values = (
        transaction.imported_description,
        transaction.notes,
        getattr(payee, "name", None),
    )
    return tuple(value for value in values if isinstance(value, str) and value.strip())
