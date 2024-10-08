from actual import Actual
from actual.database import Transactions
from actual.queries import create_transaction

from actual_discord_bot.config import ActualConfig
from actual_discord_bot.dataclasses_definitions import ActualTransactionData


class ActualConnector:
    def __init__(self, config: ActualConfig) -> None:
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
            return create_transaction(
                actual.session,
                date=transaction_data.date,
                account=transaction_data.account,
                amount=transaction_data.amount,
                imported_payee=transaction_data.imported_payee,
            )
