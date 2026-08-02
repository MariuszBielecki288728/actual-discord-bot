"""
Isolated adapter around the pinned bank2ynab internals.

This module is deliberately invoked in a child process.  It writes exactly one
small, versioned JSON document to stdout and never invokes the YNAB API.
"""

import json
from collections.abc import Sequence
from typing import Any

from bank2ynab.bank_handler import build_bank  # type: ignore[import-untyped]
from bank2ynab.config_handler import ConfigHandler  # type: ignore[import-untyped]
from bank2ynab.transactionfile_reader import get_files  # type: ignore[import-untyped]

SCHEMA_VERSION = 1


def _result(status: str, **values: object) -> None:
    print(json.dumps({"schema_version": SCHEMA_VERSION, "status": status, **values}))


def _matching_banks(config_handler: ConfigHandler) -> Sequence[tuple[str, Any]]:
    matches: list[tuple[str, Any]] = []
    for section in config_handler.config.sections():
        config = config_handler.fix_conf_params(section)
        if get_files(
            name=config.bank_name,
            file_pattern=config.input_filename,
            try_path=config.path,
            regex_active=config.regex,
            ext=config.ext,
            prefix=config.fixed_prefix,
        ):
            matches.append((section, config))
    return matches


def _serialized_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "date": row["date"],
            "payee": row.get("payee_name"),
            "memo": row.get("memo"),
            "amount_milliunits": row["amount"],
            "upstream_import_id": row["import_id"],
        }
        for row in rows
    ]


def main() -> None:
    """Convert the one isolated input file and return its safe result contract."""
    try:
        config_handler = ConfigHandler()
        matches = _matching_banks(config_handler)
        if not matches:
            _result("unmatched_filename")
            return
        if len(matches) != 1:
            _result("ambiguous_format")
            return
        section, config = matches[0]
        bank = build_bank(config)
        bank.run()
        if bank.files_processed != 1:
            _result("unsupported_layout", bank_format=section)
            return
        if not bank.transaction_list:
            _result("no_transactions", bank_format=section, files_processed=1)
            return
        _result(
            "converted",
            bank_format=section,
            files_processed=1,
            transactions=_serialized_rows(bank.transaction_list),
        )
    except Exception:  # noqa: BLE001 - child boundary deliberately hides upstream errors
        _result("conversion_failed")


if __name__ == "__main__":
    main()
