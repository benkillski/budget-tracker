import re
from decimal import Decimal, InvalidOperation

from app.models import Rule

TEXT_MATCH_TYPES = {"contains", "equals", "regex"}
AMOUNT_MATCH_TYPES = {"equals", "greater_than", "less_than"}


def apply_rules(
    payee: str,
    rules: list[Rule],
    description: str = "",
    memo: str = "",
    account_id: int | None = None,
    amount_cents: int | None = None,
) -> Rule | None:
    """Return the first rule (in list order) that matches, or None.

    Each rule declares its own source (payee, description, memo, amount);
    text sources use contains/equals/regex, the amount source uses
    equals/greater_than/less_than with match_value as a dollar string
    (e.g., "9.99"). Comparisons are on absolute value of amount_cents, so
    a rule for "greater_than 1000" matches both -$1500 charges and +$1500
    deposits. Scope with account_id (and category rules) when sign matters.

    Rules may pin themselves to a specific account via rule.account_id;
    unset = match any account.

    Callers must pass rules pre-sorted ascending by priority (lower
    number = checked first) — e.g. `select(Rule).order_by(Rule.priority)`.
    """
    sources = {"payee": payee, "description": description, "memo": memo}
    for rule in rules:
        if rule.account_id is not None and rule.account_id != account_id:
            continue
        if rule.source == "amount":
            if _amount_matches(amount_cents, rule):
                return rule
            continue
        value = sources.get(rule.source, payee) or ""
        if _matches(value, rule):
            return rule
    return None


def _matches(value: str, rule: Rule) -> bool:
    if rule.match_type == "contains":
        return rule.match_value.lower() in value.lower()
    if rule.match_type == "equals":
        return value.strip().lower() == rule.match_value.strip().lower()
    if rule.match_type == "regex":
        return re.search(rule.match_value, value) is not None
    if rule.match_type in {"greater_than", "less_than"}:
        # Numeric match types are only meaningful on the amount source.
        return False
    raise ValueError(f"Unknown match_type: {rule.match_type}")


def _amount_matches(amount_cents: int | None, rule: Rule) -> bool:
    if amount_cents is None:
        return False
    if rule.match_type not in AMOUNT_MATCH_TYPES:
        return False
    try:
        target_cents = int(Decimal(rule.match_value) * 100)
    except (InvalidOperation, ValueError):
        return False
    actual_cents = abs(amount_cents)
    if rule.match_type == "equals":
        return actual_cents == target_cents
    if rule.match_type == "greater_than":
        return actual_cents > target_cents
    if rule.match_type == "less_than":
        return actual_cents < target_cents
    return False
