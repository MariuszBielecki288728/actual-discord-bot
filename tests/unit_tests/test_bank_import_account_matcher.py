import pytest

from actual_discord_bot.bank_imports.account_matcher import (
    match_account,
    normalize_account_name,
)
from actual_discord_bot.bank_imports.models import ImportableActualAccount


@pytest.mark.parametrize(
    ("value", "normalized"),
    [("Pekao — główne", "pekao glowne"), (" PL Bank Pekao ", "pl bank pekao")],
)
def test_normalize_account_name(value, normalized):
    assert normalize_account_name(value) == normalized


@pytest.mark.parametrize("account_name", ["Pekao", "Bank Pekao"])
def test_match_account_accepts_unique_exact_core_token_match(account_name):
    account = ImportableActualAccount(account_name, off_budget=False)

    assert match_account("PL Bank Pekao", (account,)) is account


def test_match_account_does_not_guess_when_core_token_match_is_tied():
    accounts = (
        ImportableActualAccount("Pekao", off_budget=False),
        ImportableActualAccount("Bank Pekao", off_budget=True),
    )

    assert match_account("PL Bank Pekao", accounts) is None


def test_match_account_returns_sole_open_account_even_when_names_differ():
    account = ImportableActualAccount("Everyday spending", off_budget=False)

    assert match_account("PL Bank Pekao", (account,)) is account
