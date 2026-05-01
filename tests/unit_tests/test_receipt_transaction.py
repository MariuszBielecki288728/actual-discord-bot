from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem
from actual_discord_bot.receipts.transaction import (
    create_receipt_split_transaction,
    find_matching_transaction,
    generate_receipt_imported_id,
)


class TestGenerateReceiptImportedId:
    def test_generates_deterministic_id(self):
        receipt = ParsedReceipt(
            store_name="Kaufland",
            items=[],
            total=Decimal("23.48"),
            date=date(2026, 4, 30),
        )
        id1 = generate_receipt_imported_id(receipt)
        id2 = generate_receipt_imported_id(receipt)
        assert id1 == id2

    def test_includes_receipt_prefix(self):
        receipt = ParsedReceipt(
            store_name="Biedronka",
            items=[],
            total=Decimal("50.00"),
            date=date(2026, 5, 1),
        )
        imported_id = generate_receipt_imported_id(receipt)
        assert imported_id.startswith("receipt:")

    def test_includes_store_name(self):
        receipt = ParsedReceipt(
            store_name="Lidl",
            items=[],
            total=Decimal("10.00"),
            date=date(2026, 5, 1),
        )
        imported_id = generate_receipt_imported_id(receipt)
        assert "Lidl" in imported_id

    def test_different_stores_produce_different_ids(self):
        receipt1 = ParsedReceipt(
            store_name="Kaufland",
            items=[],
            total=Decimal("23.48"),
            date=date(2026, 4, 30),
        )
        receipt2 = ParsedReceipt(
            store_name="Biedronka",
            items=[],
            total=Decimal("23.48"),
            date=date(2026, 4, 30),
        )
        assert generate_receipt_imported_id(receipt1) != generate_receipt_imported_id(
            receipt2
        )

    def test_different_totals_produce_different_ids(self):
        receipt1 = ParsedReceipt(
            store_name="Kaufland",
            items=[],
            total=Decimal("23.48"),
            date=date(2026, 4, 30),
        )
        receipt2 = ParsedReceipt(
            store_name="Kaufland",
            items=[],
            total=Decimal("23.49"),
            date=date(2026, 4, 30),
        )
        assert generate_receipt_imported_id(receipt1) != generate_receipt_imported_id(
            receipt2
        )

    def test_different_dates_produce_different_ids(self):
        receipt1 = ParsedReceipt(
            store_name="Kaufland",
            items=[],
            total=Decimal("23.48"),
            date=date(2026, 4, 30),
        )
        receipt2 = ParsedReceipt(
            store_name="Kaufland",
            items=[],
            total=Decimal("23.48"),
            date=date(2026, 5, 1),
        )
        assert generate_receipt_imported_id(receipt1) != generate_receipt_imported_id(
            receipt2
        )

    def test_none_date_handled(self):
        receipt = ParsedReceipt(
            store_name="TestStore",
            items=[],
            total=Decimal("10.00"),
            date=None,
        )
        imported_id = generate_receipt_imported_id(receipt)
        assert imported_id.startswith("receipt:")
        assert "None" in imported_id


class TestFindMatchingTransaction:
    def test_returns_none_when_no_matches(self):
        mock_actual = MagicMock()
        with patch(
            "actual_discord_bot.receipts.transaction.get_transactions", return_value=[]
        ):
            result = find_matching_transaction(
                actual=mock_actual,
                amount=Decimal("23.48"),
                transaction_date=date(2026, 4, 30),
                account_name="TestAccount",
            )
        assert result is None

    def test_returns_matching_receipt_transaction(self):
        mock_actual = MagicMock()
        mock_txn = MagicMock()
        mock_txn.financial_id = "receipt:Kaufland:2026-04-30:23.48:abc12345"
        mock_txn.is_child = False

        with patch(
            "actual_discord_bot.receipts.transaction.get_transactions",
            return_value=[mock_txn],
        ):
            result = find_matching_transaction(
                actual=mock_actual,
                amount=Decimal("23.48"),
                transaction_date=date(2026, 4, 30),
                account_name="TestAccount",
            )
        assert result is mock_txn

    def test_returns_matching_bank_transaction(self):
        mock_actual = MagicMock()
        mock_txn = MagicMock()
        mock_txn.financial_id = None
        mock_txn.is_child = False

        with patch(
            "actual_discord_bot.receipts.transaction.get_transactions",
            return_value=[mock_txn],
        ):
            result = find_matching_transaction(
                actual=mock_actual,
                amount=Decimal("23.48"),
                transaction_date=date(2026, 4, 30),
                account_name="TestAccount",
            )
        assert result is mock_txn

    def test_ignores_child_transactions(self):
        mock_actual = MagicMock()
        mock_txn = MagicMock()
        mock_txn.is_child = True

        with patch(
            "actual_discord_bot.receipts.transaction.get_transactions",
            return_value=[mock_txn],
        ):
            result = find_matching_transaction(
                actual=mock_actual,
                amount=Decimal("23.48"),
                transaction_date=date(2026, 4, 30),
                account_name="TestAccount",
            )
        assert result is None

    def test_uses_date_tolerance(self):
        mock_actual = MagicMock()

        with patch(
            "actual_discord_bot.receipts.transaction.get_transactions", return_value=[]
        ) as mock_get:
            find_matching_transaction(
                actual=mock_actual,
                amount=Decimal("10.00"),
                transaction_date=date(2026, 5, 1),
                account_name="Account",
                date_tolerance_days=2,
            )
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["start_date"] == date(2026, 4, 29)
        assert call_kwargs["end_date"] == date(2026, 5, 4)


class TestCreateReceiptSplitTransaction:
    """Test split transaction creation logic."""

    def test_receipt_date_takes_priority_over_fallback(self):
        """Receipt date should be used over the fallback (Discord message) date."""
        mock_actual = MagicMock()

        receipt = ParsedReceipt(
            store_name="Kaufland",
            items=[
                ReceiptItem("Mleko", Decimal("1"), Decimal("4.99"), Decimal("4.99")),
            ],
            total=Decimal("4.99"),
            date=date(2026, 4, 28),  # receipt's own date
        )

        with patch(
            "actual_discord_bot.receipts.transaction.find_matching_transaction",
            return_value=None,
        ):
            with patch(
                "actual_discord_bot.receipts.transaction.create_transaction",
            ) as mock_create:
                mock_create.return_value = MagicMock()
                with patch(
                    "actual_discord_bot.receipts.transaction.create_splits",
                    return_value=MagicMock(),
                ):
                    create_receipt_split_transaction(
                        actual=mock_actual,
                        receipt=receipt,
                        account_name="TestAccount",
                        transaction_date=date(2026, 4, 30),  # fallback
                    )

        # Should use receipt date (4/28), not fallback (4/30)
        call_kwargs = mock_create.call_args_list[0][1]
        assert call_kwargs["date"] == date(2026, 4, 28)

    def test_fallback_date_used_when_receipt_has_no_date(self):
        """When receipt has no date, use the fallback date."""
        mock_actual = MagicMock()

        receipt = ParsedReceipt(
            store_name="Store",
            items=[
                ReceiptItem("Item", Decimal("1"), Decimal("5.00"), Decimal("5.00")),
            ],
            total=Decimal("5.00"),
            date=None,  # no receipt date
        )

        with patch(
            "actual_discord_bot.receipts.transaction.find_matching_transaction",
            return_value=None,
        ):
            with patch(
                "actual_discord_bot.receipts.transaction.create_transaction",
            ) as mock_create:
                mock_create.return_value = MagicMock()
                with patch(
                    "actual_discord_bot.receipts.transaction.create_splits",
                    return_value=MagicMock(),
                ):
                    create_receipt_split_transaction(
                        actual=mock_actual,
                        receipt=receipt,
                        account_name="TestAccount",
                        transaction_date=date(2026, 5, 1),
                    )

        call_kwargs = mock_create.call_args_list[0][1]
        assert call_kwargs["date"] == date(2026, 5, 1)

    def test_dedup_skips_creation_when_match_exists(self):
        """When a matching transaction exists, don't create a new one."""
        mock_actual = MagicMock()
        existing_txn = MagicMock()

        receipt = ParsedReceipt(
            store_name="Kaufland",
            items=[
                ReceiptItem("Mleko", Decimal("1"), Decimal("4.99"), Decimal("4.99")),
            ],
            total=Decimal("4.99"),
            date=date(2026, 4, 30),
        )

        with patch(
            "actual_discord_bot.receipts.transaction.find_matching_transaction",
            return_value=existing_txn,
        ):
            with patch(
                "actual_discord_bot.receipts.transaction.create_transaction",
            ) as mock_create:
                create_receipt_split_transaction(
                    actual=mock_actual,
                    receipt=receipt,
                    account_name="TestAccount",
                )

        mock_create.assert_not_called()

    def test_rounding_subtransaction_created_for_difference(self):
        """When items don't sum to total, a rounding adjustment is added."""
        mock_actual = MagicMock()

        receipt = ParsedReceipt(
            store_name="Store",
            items=[
                ReceiptItem("A", Decimal("1"), Decimal("10.00"), Decimal("10.00")),
                ReceiptItem("B", Decimal("1"), Decimal("5.00"), Decimal("5.00")),
            ],
            total=Decimal("15.01"),  # 0.01 difference
            date=date(2026, 4, 30),
        )

        with patch(
            "actual_discord_bot.receipts.transaction.find_matching_transaction",
            return_value=None,
        ):
            with patch(
                "actual_discord_bot.receipts.transaction.create_transaction",
            ) as mock_create:
                mock_create.return_value = MagicMock()
                with patch(
                    "actual_discord_bot.receipts.transaction.create_splits",
                ) as mock_splits:
                    mock_splits.return_value = MagicMock()
                    create_receipt_split_transaction(
                        actual=mock_actual,
                        receipt=receipt,
                        account_name="TestAccount",
                    )

        # 2 items + 1 rounding = 3 create_transaction calls
        assert mock_create.call_count == 3
        # Last call should be the rounding adjustment
        last_call_kwargs = mock_create.call_args_list[2][1]
        assert last_call_kwargs["notes"] == "Zaokrąglenie"
        assert last_call_kwargs["amount"] == Decimal("-0.01")
