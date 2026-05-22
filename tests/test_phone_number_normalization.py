from __future__ import annotations

from bot_api.security.access_control import (
    _comparable_number,
    _normalize_number,
    _preferred_storage_number,
)


def test_normalize_number_adds_country_code_for_local_formats() -> None:
    assert _normalize_number("(83) 99123-4567") == "5583991234567"
    assert _normalize_number("83 9123-4567") == "558391234567"


def test_comparable_number_treats_optional_ninth_digit_as_same_whatsapp() -> None:
    assert _comparable_number("5583991234567") == "558391234567"
    assert _comparable_number("558391234567") == "558391234567"
    assert _comparable_number("(83) 99123-4567") == "558391234567"
    assert _comparable_number("83 9123-4567") == "558391234567"


def test_preferred_storage_number_keeps_more_complete_mobile_format_when_available() -> None:
    assert _preferred_storage_number(["558391234567", "5583991234567"]) == "5583991234567"
    assert _preferred_storage_number(["8391234567", "83991234567"]) == "5583991234567"
