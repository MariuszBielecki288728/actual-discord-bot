from datetime import date
from decimal import Decimal

from actual import Actual
from actual.database import Transactions
from actual.queries import create_transaction

from actual_discord_bot.config import ActualConfig
from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.receipts.models import ParsedReceipt
from actual_discord_bot.receipts.transaction import (
    create_receipt_split_transaction,
    find_matching_transaction,
)


class ActualConnector:
    def __init__(self, config: ActualConfig) -> None:
        self.config = config
        self.actual_manager = Actual(
            base_url=config.url,
            password=config.password,
            encryption_password=config.encryption_password,
            file=config.file,
        )

    def save_transaction(
        self,
        transaction_data: ActualTransactionData,
    ) -> Transactions:
        with self.actual_manager as actual:
            # Deduplication: check if a receipt-created transaction already exists
            # find_matching_transaction expects a positive amount (receipt total)
            amount_abs = abs(Decimal(str(transaction_data.amount)))
            existing = find_matching_transaction(
                actual=actual,
                amount=amount_abs,
                transaction_date=transaction_data.date,
                account_name=transaction_data.account,
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
            return transaction

    def save_receipt_transaction(
        self,
        receipt: ParsedReceipt,
        fallback_date: date | None = None,
    ) -> None:
        """Create a split transaction from a parsed receipt."""
        with self.actual_manager as actual:
            create_receipt_split_transaction(
                actual=actual,
                receipt=receipt,
                account_name=self.config.account,
                transaction_date=fallback_date,
            )
