from decimal import Decimal

from app.money import format_money, to_cents, to_decimal


def test_to_cents_converts_decimal_to_integer_cents():
    assert to_cents(Decimal("12.34")) == 1234


def test_to_cents_rounds_half_up():
    assert to_cents(Decimal("12.345")) == 1235


def test_to_decimal_converts_cents_to_decimal():
    assert to_decimal(1234) == Decimal("12.34")


def test_format_money_formats_positive_cents():
    assert format_money(123456) == "$1,234.56"


def test_format_money_formats_negative_cents():
    assert format_money(-500) == "-$5.00"
