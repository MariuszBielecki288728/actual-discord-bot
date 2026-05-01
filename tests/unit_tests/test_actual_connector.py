from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from actual_discord_bot.actual_connector import ActualConnector
from actual_discord_bot.config import ActualConfig
from actual_discord_bot.dataclasses_definitions import ActualTransactionData


@pytest.fixture
def mock_actual_manager():
    """Mock the Actual context manager."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.session = MagicMock()
    return mock


@pytest.fixture
def connector(mock_actual_manager):
    with patch(
        "actual_discord_bot.actual_connector.Actual", return_value=mock_actual_manager
    ):
        return ActualConnector(
            ActualConfig(url="http://test:5006", password="test", file="TestBudget")
        )


class TestBankNotificationDeduplication:
    """Test that bank notifications don't create duplicates when receipts exist."""

    def test_skips_creation_when_receipt_transaction_exists(
        self, connector, mock_actual_manager
    ):
        """If a matching receipt transaction already exists, don't create a duplicate."""
        existing_txn = MagicMock()
        existing_txn.financial_id = "receipt:Kaufland:2026-04-30:23.48:abc12345"

        transaction_data = ActualTransactionData(
            date=date(2026, 4, 30),
            account="Pekao",
            amount=Decimal("-23.48"),
            imported_payee="Kaufland",
        )

        with patch(
            "actual_discord_bot.actual_connector.find_matching_transaction",
            return_value=existing_txn,
        ) as mock_find:
            result = connector.save_transaction(transaction_data)

        assert result is existing_txn
        mock_find.assert_called_once_with(
            actual=mock_actual_manager,
            amount=Decimal("23.48"),  # abs value
            transaction_date=date(2026, 4, 30),
            account_name="Pekao",
        )

    def test_creates_transaction_when_no_receipt_exists(
        self, connector, mock_actual_manager
    ):
        """If no matching receipt transaction exists, create normally."""
        transaction_data = ActualTransactionData(
            date=date(2026, 4, 30),
            account="Pekao",
            amount=Decimal("-23.48"),
            imported_payee="Kaufland",
        )

        with patch(
            "actual_discord_bot.actual_connector.find_matching_transaction",
            return_value=None,
        ):
            with patch(
                "actual_discord_bot.actual_connector.create_transaction",
                return_value=MagicMock(),
            ) as mock_create:
                connector.save_transaction(transaction_data)

        mock_create.assert_called_once_with(
            mock_actual_manager.session,
            date=date(2026, 4, 30),
            account="Pekao",
            amount=Decimal("-23.48"),
            imported_payee="Kaufland",
        )

    def test_dedup_uses_absolute_amount(self, connector, mock_actual_manager):
        """Ensure deduplication passes absolute amount (positive) to find_matching."""
        transaction_data = ActualTransactionData(
            date=date(2026, 5, 1),
            account="Pekao",
            amount=Decimal("-50.00"),
            imported_payee="Biedronka",
        )

        with patch(
            "actual_discord_bot.actual_connector.find_matching_transaction",
            return_value=None,
        ) as mock_find:
            with patch(
                "actual_discord_bot.actual_connector.create_transaction",
                return_value=MagicMock(),
            ):
                connector.save_transaction(transaction_data)

        mock_find.assert_called_once_with(
            actual=mock_actual_manager,
            amount=Decimal("50.00"),
            transaction_date=date(2026, 5, 1),
            account_name="Pekao",
        )

    def test_dedup_handles_positive_deposit(self, connector, mock_actual_manager):
        """For deposits (positive amounts), dedup also uses absolute value."""
        transaction_data = ActualTransactionData(
            date=date(2026, 5, 1),
            account="Pekao",
            amount=Decimal("100.00"),
            imported_payee="Transfer",
        )

        with patch(
            "actual_discord_bot.actual_connector.find_matching_transaction",
            return_value=None,
        ) as mock_find:
            with patch(
                "actual_discord_bot.actual_connector.create_transaction",
                return_value=MagicMock(),
            ):
                connector.save_transaction(transaction_data)

        mock_find.assert_called_once_with(
            actual=mock_actual_manager,
            amount=Decimal("100.00"),
            transaction_date=date(2026, 5, 1),
            account_name="Pekao",
        )

    def test_save_transaction_commits(self, connector, mock_actual_manager):
        """Verify that save_transaction commits changes to sync with server."""
        transaction_data = ActualTransactionData(
            date=date(2026, 5, 1),
            account="Pekao",
            amount=Decimal("-10.00"),
            imported_payee="TestStore",
        )

        with patch(
            "actual_discord_bot.actual_connector.find_matching_transaction",
            return_value=None,
        ):
            with patch(
                "actual_discord_bot.actual_connector.create_transaction",
                return_value=MagicMock(),
            ):
                connector.save_transaction(transaction_data)

        mock_actual_manager.commit.assert_called_once()

    def test_save_transaction_no_commit_on_dedup(self, connector, mock_actual_manager):
        """When dedup finds an existing transaction, no commit is needed."""
        existing_txn = MagicMock()
        transaction_data = ActualTransactionData(
            date=date(2026, 5, 1),
            account="Pekao",
            amount=Decimal("-10.00"),
            imported_payee="TestStore",
        )

        with patch(
            "actual_discord_bot.actual_connector.find_matching_transaction",
            return_value=existing_txn,
        ):
            connector.save_transaction(transaction_data)

        mock_actual_manager.commit.assert_not_called()


class TestSaveReceiptTransaction:
    """Test the save_receipt_transaction method on ActualConnector."""

    def test_calls_create_receipt_split_transaction(
        self, connector, mock_actual_manager
    ):
        from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem

        receipt = ParsedReceipt(
            store_name="Kaufland",
            items=[
                ReceiptItem("Mleko", Decimal("1"), Decimal("4.99"), Decimal("4.99")),
            ],
            total=Decimal("4.99"),
            date=date(2026, 4, 30),
        )

        with patch(
            "actual_discord_bot.actual_connector.create_receipt_split_transaction",
        ) as mock_create:
            connector.save_receipt_transaction(receipt, fallback_date=date(2026, 5, 1))

        mock_create.assert_called_once_with(
            actual=mock_actual_manager,
            receipt=receipt,
            account_name="Pekao",
            transaction_date=date(2026, 5, 1),
        )
