import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal

from actual.queries import create_payee, get_schedules, get_transactions

from actual_discord_bot.actual_connector import (
    ActualConnector,
    ActualScheduleData,
    ScheduleCreationStatus,
)
from actual_discord_bot.bank_imports.models import BankImportTransaction
from actual_discord_bot.config import ActualConfig
from actual_discord_bot.dataclasses_definitions import ActualTransactionData
from actual_discord_bot.schedules import RecurrenceFrequency, ScheduleRecurrence

ACTUAL_TEST_URL = os.environ.get("ACTUAL_TEST_URL", "http://localhost:12013")


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


def test_bank_csv_import_is_idempotent_and_creates_a_cleared_transaction(actual):
    connector = ActualConnector(
        ActualConfig(url=ACTUAL_TEST_URL, password="test", file="TestBudget"),
    )
    row = BankImportTransaction(
        date=date(2026, 8, 1),
        amount=Decimal("-12.34"),
        payee="Synthetic Market",
        memo="Synthetic bank statement row",
        upstream_import_id="YNAB:-12340:2026-08-01:1",
    )

    first = connector.import_bank_transactions("TestAccount", "Synthetic bank", [row])
    second = connector.import_bank_transactions("TestAccount", "Synthetic bank", [row])

    assert (first.created_count, first.duplicate_count) == (1, 0)
    assert (second.created_count, second.duplicate_count) == (0, 1)
    transactions = get_transactions(actual.session, account="TestAccount")
    imported = next(
        transaction
        for transaction in transactions
        if transaction.imported_description == "Synthetic Market"
    )
    assert imported.get_amount() == Decimal("-12.34")
    assert imported.cleared == 1
    assert imported.notes == "Synthetic bank statement row"
    assert imported.financial_id.startswith("bank2ynab:")


def test_schedule_creation_is_manual_and_idempotent(actual):
    create_payee(actual.session, "Synthetic Schedule Payee")
    actual.commit()
    connector = ActualConnector(
        ActualConfig(url=ACTUAL_TEST_URL, password="test", file="TestBudget"),
    )
    data = ActualScheduleData(
        start=date(2024, 9, 23),
        account="TestAccount",
        amount=Decimal("-90.45"),
        payee="Synthetic Schedule Payee",
        name="Synthetic Schedule Payee",
        recurrence=ScheduleRecurrence(2, RecurrenceFrequency.MONTHLY),
    )

    assert connector.create_schedule(data) is ScheduleCreationStatus.CREATED
    assert connector.create_schedule(data) is ScheduleCreationStatus.ALREADY_EXISTS

    schedules = get_schedules(actual.session, include_completed=True)
    schedule = next(
        schedule
        for schedule in schedules
        if schedule.name == "Synthetic Schedule Payee"
    )
    assert schedule.posts_transaction == 0
    conditions = {
        condition["field"]: condition
        for condition in json.loads(schedule.rule.conditions)
    }
    assert conditions["amount"] == {
        "field": "amount",
        "op": "is",
        "value": -9045,
        "type": "number",
    }
    assert conditions["date"]["value"] == {
        "start": "2024-09-23",
        "interval": 2,
        "frequency": "monthly",
        "patterns": [],
        "skipWeekend": False,
        "weekendSolveMode": "after",
        "endMode": "never",
        "endOccurrences": 1,
        "endDate": "2024-09-23",
    }
