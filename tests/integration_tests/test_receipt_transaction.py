import os
from datetime import date
from decimal import Decimal

import pytest
from actual import Actual
from actual.queries import create_account, get_transactions

from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem
from actual_discord_bot.receipts.transaction import create_receipt_split_transaction

ACTUAL_TEST_URL = os.environ.get("ACTUAL_TEST_URL", "http://localhost:12012")


@pytest.fixture
def actual_with_account():
    with Actual(
        base_url=ACTUAL_TEST_URL,
        password="test",
        bootstrap=True,
    ) as actual:
        actual.create_budget("ReceiptTestBudget")
        actual.upload_budget()
        create_account(actual.session, "TestAccount")
        actual.commit()
        yield actual
        actual.delete_budget()
        actual.commit()


class TestReceiptToActualBudget:
    """Integration tests: parsed receipt → split transaction in Actual Budget."""

    def test_create_split_transaction_from_receipt(self, actual_with_account):
        receipt = ParsedReceipt(
            store_name="Kaufland",
            items=[
                ReceiptItem(
                    "Mleko 3.2%", Decimal("1"), Decimal("4.99"), Decimal("4.99")
                ),
                ReceiptItem(
                    "Chleb 500g", Decimal("1"), Decimal("5.49"), Decimal("5.49")
                ),
                ReceiptItem("Masło", Decimal("2"), Decimal("6.50"), Decimal("13.00")),
            ],
            total=Decimal("23.48"),
            date=date(2026, 4, 30),
            source="pdf",
        )

        create_receipt_split_transaction(
            actual=actual_with_account,
            receipt=receipt,
            account_name="TestAccount",
        )

        # Verify the split transaction was created
        transactions = get_transactions(
            actual_with_account.session,
            account="TestAccount",
            is_parent=True,
        )
        assert len(transactions) == 1
        parent = transactions[0]
        # Total amount should be negative (payment)
        assert parent.get_amount() == Decimal("-23.48")
        assert "Kaufland" in parent.notes

        # Check splits
        splits = parent.splits
        assert len(splits) == 3
        amounts = sorted([s.get_amount() for s in splits])
        assert Decimal("-13.00") in amounts
        assert Decimal("-5.49") in amounts
        assert Decimal("-4.99") in amounts

    def test_create_split_transaction_with_rounding(self, actual_with_account):
        """Test that rounding differences create an extra sub-transaction."""
        receipt = ParsedReceipt(
            store_name="TestStore",
            items=[
                ReceiptItem("Item1", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
                ReceiptItem("Item2", Decimal("1"), Decimal("5.00"), Decimal("5.00")),
            ],
            total=Decimal("15.01"),  # 0.01 PLN rounding difference
            date=date(2026, 4, 30),
            source="photo",
        )

        create_receipt_split_transaction(
            actual=actual_with_account,
            receipt=receipt,
            account_name="TestAccount",
        )

        transactions = get_transactions(
            actual_with_account.session,
            account="TestAccount",
            is_parent=True,
        )
        assert len(transactions) == 1
        parent = transactions[0]
        assert parent.get_amount() == Decimal("-15.01")

        # Should have 3 splits: 2 items + 1 rounding
        splits = parent.splits
        assert len(splits) == 3
