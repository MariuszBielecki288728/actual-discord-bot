from datetime import date
from decimal import Decimal

import pytest

from actual_discord_bot.bank_imports.converter import (
    MAX_CONVERTED_ROWS,
    BankStatementConversionError,
    BankStatementConverter,
    _decode_worker_result,
)


def _synthetic_pekao_csv(*, categories: bool = False) -> bytes:
    header = (
        "Booking date;Value date;Payee;Address;Source account;Target account;Memo;"
        "Amount;Currency;Reference;Operation type"
    )
    row = (
        "01.08.2026;01.08.2026;Aster Market;;; ;Fictional groceries;-12,34;PLN;"
        "SYNTHETIC-001;CARD PAYMENT"
    )
    if categories:
        header += ";Kategoria"
        row += ";Synthetic"
    return f"{header}\n{row}\n".encode()


@pytest.mark.asyncio
async def test_converter_converts_a_synthetic_supported_pekao_statement():
    statement = await BankStatementConverter().convert(
        "Lista_operacji_20260802_021721.csv", _synthetic_pekao_csv()
    )

    assert statement.bank_format == "PL Bank Pekao"
    assert statement.transactions[0].date == date(2026, 8, 1)
    assert statement.transactions[0].amount == Decimal("-12.34")
    assert statement.transactions[0].payee == "Aster Market"


@pytest.mark.asyncio
async def test_converter_rejects_renamed_statement_and_category_variant():
    converter = BankStatementConverter()
    with pytest.raises(BankStatementConversionError, match="unmatched_filename"):
        await converter.convert("unrecognized_statement_2026.csv", _synthetic_pekao_csv())
    with pytest.raises(BankStatementConversionError, match="unsupported_layout"):
        await converter.convert(
            "Lista_operacji_20260802_021721.csv", _synthetic_pekao_csv(categories=True)
        )


def test_decode_worker_result_rejects_non_cent_amounts_and_excessive_rows():
    row = {
        "date": "2026-08-01",
        "payee": "Synthetic merchant",
        "memo": "Synthetic memo",
        "amount_milliunits": 12345,
        "upstream_import_id": "YNAB:12345:2026-08-01:1",
    }
    result = {
        "schema_version": 1,
        "status": "converted",
        "bank_format": "Synthetic bank",
        "files_processed": 1,
        "transactions": [row],
    }
    with pytest.raises(BankStatementConversionError, match="invalid_output"):
        _decode_worker_result(result, "synthetic.csv")

    result["transactions"] = [row] * (MAX_CONVERTED_ROWS + 1)
    with pytest.raises(BankStatementConversionError, match="invalid_output"):
        _decode_worker_result(result, "synthetic.csv")
