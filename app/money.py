from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def to_decimal(cents: int) -> Decimal:
    return Decimal(cents) / Decimal(100)


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole = abs(cents) // 100
    frac = abs(cents) % 100
    return f"{sign}${whole:,}.{frac:02d}"
