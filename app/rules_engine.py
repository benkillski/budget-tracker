import re

from app.models import Rule


def apply_rules(payee: str, rules: list[Rule]) -> Rule | None:
    """Return the first rule (in list order) that matches payee, or None.

    Callers must pass rules pre-sorted ascending by priority (lower
    number = checked first) — e.g. `select(Rule).order_by(Rule.priority)`.
    """
    for rule in rules:
        if _matches(payee, rule):
            return rule
    return None


def _matches(payee: str, rule: Rule) -> bool:
    if rule.match_type == "contains":
        return rule.match_value.lower() in payee.lower()
    if rule.match_type == "equals":
        return payee.strip().lower() == rule.match_value.strip().lower()
    if rule.match_type == "regex":
        return re.search(rule.match_value, payee) is not None
    raise ValueError(f"Unknown match_type: {rule.match_type}")
