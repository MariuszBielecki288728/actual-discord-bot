import datetime
import hashlib
from datetime import date, timedelta
from decimal import Decimal

from actual import Actual
from actual.database import Transactions
from actual.queries import create_splits, create_transaction, get_transactions

from actual_discord_bot.receipts.models import ParsedReceipt

ROUNDING_TOLERANCE = Decimal("0.02")


def generate_receipt_imported_id(receipt: ParsedReceipt) -> str:
    """Generate a unique imported_id for a receipt-created transaction."""
    content = f"{receipt.store_name}:{receipt.date}:{receipt.total}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:8]
    return f"receipt:{receipt.store_name}:{receipt.date}:{receipt.total}:{hash_suffix}"


def find_matching_transaction(
    actual: Actual,
    amount: Decimal,
    transaction_date: date,
    account_name: str,
    date_tolerance_days: int = 1,
    receipt_only: bool = False,
) -> Transactions | None:
    """
    Find an existing transaction that likely represents the same purchase.

    Searches for transactions matching the amount within a date window.
    Used for deduplication between receipt and bank notification flows.
    Returns any matching transaction (receipt-created or bank-created).
    """
    start = transaction_date - timedelta(days=date_tolerance_days)
    end = transaction_date + timedelta(days=date_tolerance_days + 1)  # exclusive

    transactions = get_transactions(
        actual.session,
        start_date=start,
        end_date=end,
        account=account_name,
        amount=amount,
    )

    # Return the first matching parent transaction. Bank notification imports use
    # receipt_only so one ordinary same-amount expense cannot suppress another.
    for txn in transactions:
        is_receipt = (txn.financial_id or "").startswith("receipt:")
        if not txn.is_child and (not receipt_only or is_receipt):
            return txn

    return None


def create_receipt_split_transaction(
    actual: Actual,
    receipt: ParsedReceipt,
    account_name: str,
    transaction_date: date | None = None,
) -> None:
    """
    Create a split transaction in Actual Budget from a parsed receipt.

    Checks for duplicate transactions before creating.
    """
    txn_date = (
        receipt.date
        or transaction_date
        or datetime.datetime.now(tz=datetime.UTC).date()
    )
    imported_id = generate_receipt_imported_id(receipt)

    items_sum = sum(
        (item.total_price for item in receipt.items),
        start=Decimal("0"),
    )
    diff = receipt.total - items_sum
    if not receipt.items or receipt.total <= 0:
        msg = "Receipt must contain at least one item and have a positive total"
        raise ValueError(msg)
    if abs(diff) > ROUNDING_TOLERANCE:
        msg = (
            "Receipt item total differs from receipt total by "
            f"{diff} PLN, exceeding the rounding tolerance"
        )
        raise ValueError(msg)

    # Deduplication: check if a matching transaction already exists
    existing = find_matching_transaction(
        actual=actual,
        amount=-receipt.total,
        transaction_date=txn_date,
        account_name=account_name,
    )
    if existing:
        return

    # Create individual sub-transactions for each item
    sub_transactions = []
    for item in receipt.items:
        amount = -item.total_price  # Negative = payment
        t = create_transaction(
            actual.session,
            date=txn_date,
            account=account_name,
            amount=amount,
            notes=item.name,
        )
        sub_transactions.append(t)

    if diff != Decimal("0"):
        rounding_txn = create_transaction(
            actual.session,
            date=txn_date,
            account=account_name,
            amount=-diff,
            notes="Zaokrąglenie",
        )
        sub_transactions.append(rounding_txn)

    # Create the parent split transaction
    parent = create_splits(
        actual.session,
        transactions=sub_transactions,
        notes=f"Paragon: {receipt.store_name}",
    )
    parent.financial_id = imported_id
    actual.commit()
