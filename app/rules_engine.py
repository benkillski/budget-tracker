import re

from app.models import Rule


def apply_rules(payee: str, rules: list[Rule], description: str = "") -> Rule | None:
    """Return the first rule (in list order) that matches, or None.

    Each rule declares its own source (payee or description); the engine
    picks the right field to match against per rule.

    Callers must pass rules pre-sorted ascending by priority (lower
    number = checked first) — e.g. `select(Rule).order_by(Rule.priority)`.
    """
    for rule in rules:
        value = description if rule.source == "description" else payee
        if _matches(value or "", rule):
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
