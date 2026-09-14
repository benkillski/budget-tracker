import pytest

from app.models import Rule
from app.rules_engine import apply_rules


def _rule(match_type: str, match_value: str, priority: int = 0, category_id: int = 1) -> Rule:
    return Rule(match_type=match_type, match_value=match_value, category_id=category_id, priority=priority)


def test_contains_match_is_case_insensitive():
    rule = _rule("contains", "kroger")
    result = apply_rules("KROGER #123", [rule])
    assert result is rule


def test_equals_match_requires_exact_payee():
    rule = _rule("equals", "Netflix")
    assert apply_rules("Netflix", [rule]) is rule
    assert apply_rules("Netflix Inc", [rule]) is None


def test_regex_match():
    rule = _rule("regex", r"^AMZN\*")
    assert apply_rules("AMZN*ABC123", [rule]) is rule
    assert apply_rules("NOT AMZN", [rule]) is None


def test_first_match_wins_by_list_order():
    high_priority = _rule("contains", "STORE", priority=0, category_id=1)
    low_priority = _rule("contains", "STORE", priority=1, category_id=2)
    result = apply_rules("MY STORE", [high_priority, low_priority])
    assert result is high_priority


def test_no_match_returns_none():
    rule = _rule("contains", "STARBUCKS")
    assert apply_rules("KROGER", [rule]) is None


def test_unknown_match_type_raises():
    rule = _rule("fuzzy", "whatever")
    with pytest.raises(ValueError):
        apply_rules("anything", [rule])
