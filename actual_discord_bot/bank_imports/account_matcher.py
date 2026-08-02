"""Conservative, pure matching of a detected bank format to Actual accounts."""

import re
import unicodedata
from collections.abc import Iterable

from actual_discord_bot.bank_imports.models import ImportableActualAccount

_NON_IDENTIFYING_TOKENS = frozenset(
    {"account", "bank", "checking", "credit", "pl", "savings"}
)
_SPECIAL_CASE_FOLD_TRANSLITERATION = str.maketrans({"ł": "l", "ø": "o", "đ": "d"})


def normalize_account_name(value: str, *, remove_generic_tokens: bool = False) -> str:
    """Case-fold, de-accent, and normalize an account or format name."""
    decomposed = unicodedata.normalize(
        "NFKD", value.casefold().translate(_SPECIAL_CASE_FOLD_TRANSLITERATION)
    )
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", without_accents)
    if remove_generic_tokens:
        tokens = [token for token in tokens if token not in _NON_IDENTIFYING_TOKENS]
    return " ".join(tokens)


def match_account(
    bank_format: str, accounts: Iterable[ImportableActualAccount]
) -> ImportableActualAccount | None:
    """Return an account only for an unambiguous exact or core-token match."""
    open_accounts = tuple(accounts)
    if len(open_accounts) == 1:
        return open_accounts[0]

    normalized_format = normalize_account_name(bank_format)
    exact_matches = [
        account
        for account in open_accounts
        if normalize_account_name(account.name) == normalized_format
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if exact_matches:
        return None

    core_format = normalize_account_name(bank_format, remove_generic_tokens=True)
    if not core_format:
        return None
    core_matches = [
        account
        for account in open_accounts
        if normalize_account_name(account.name, remove_generic_tokens=True) == core_format
    ]
    return core_matches[0] if len(core_matches) == 1 else None
