"""Shared conservative merchant-name normalization and matching."""

import unicodedata

MIN_MATCH_NAME_LENGTH = 4
_SPECIAL_CASE_FOLD_TRANSLITERATION = str.maketrans({"ł": "l", "ø": "o", "đ": "d"})


def normalize_merchant_name(value: str) -> str:
    """Normalize merchant names from bank and OCR sources for comparison."""
    decomposed = unicodedata.normalize(
        "NFKD", value.casefold().translate(_SPECIAL_CASE_FOLD_TRANSLITERATION)
    )
    return "".join(character for character in decomposed if character.isalnum())


def merchant_names_match(expected: str, candidate: str) -> bool:
    """Return whether two meaningful merchant names contain one another."""
    expected_normalized = normalize_merchant_name(expected)
    candidate_normalized = normalize_merchant_name(candidate)
    if min(len(expected_normalized), len(candidate_normalized)) < MIN_MATCH_NAME_LENGTH:
        return False
    return (
        expected_normalized in candidate_normalized
        or candidate_normalized in expected_normalized
    )
