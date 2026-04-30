import os
from datetime import UTC, datetime

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.config import ActualConfig
from actual_discord_bot.dataclasses_definitions import ActualTransactionData

ACTUAL_TEST_URL = os.environ.get("ACTUAL_TEST_URL", "http://localhost:12012")


def test_actual_connector(actual):
    connector = ActualConnector(
        ActualConfig(url=ACTUAL_TEST_URL, password="test", file="TestBudget"),
    )
    transaction = connector.save_transaction(
        ActualTransactionData(
            date=datetime.now(tz=UTC).date(),
            account="TestAccount",
            amount=10,
            imported_payee="Żabka",
        ),
    )
    assert (
        transaction.amount == 10 * 100
    )  # actual stores original amount multiplied by 100
    assert transaction.imported_description == "Żabka"
