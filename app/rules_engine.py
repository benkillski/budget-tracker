import re

from app.models import Rule


def apply_rules(
    payee: str,
    rules: list[Rule],
    description: str = "",
    memo: str = "",
    account_id: int | None = None,
) -> Rule | None:
    """Return the first rule (in list order) that matches, or None.

    Each rule declares its own source (payee, description, memo); the
    engine picks the right field to match per rule. A rule may also pin
    itself to a specific account via rule.account_id — when set, the
    rule is skipped for transactions on other accounts.

    Callers must pass rules pre-sorted ascending by priority (lower
    number = checked first) — e.g. `select(Rule).order_by(Rule.priority)`.
    """
    sources = {"payee": payee, "description": description, "memo": memo}
    for rule in rules:
        if rule.account_id is not None and rule.account_id != account_id:
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
    raise ValueError(f"Unknown match_type: {rule.match_type}")
