import pytest

from app.models import Rule
from app.rules_engine import apply_rules


def _rule(
    match_type: str,
    match_value: str,
    priority: int = 0,
    category_id: int = 1,
    source: str = "payee",
    account_id: int | None = None,
) -> Rule:
    return Rule(
        source=source,
        match_type=match_type,
        match_value=match_value,
        category_id=category_id,
        account_id=account_id,
        priority=priority,
    )


def test_rule_matches_memo_when_source_is_memo():
    rule = _rule("contains", "overdraft", source="memo")
    assert apply_rules("Checking fee", [rule], memo="Overdraft protection used") is rule
    assert apply_rules("Checking fee", [rule], memo="") is None


def test_rule_scoped_to_account_skips_other_accounts():
    rule = _rule("contains", "TRANSFER", account_id=42)
    # Match on account 42
    assert apply_rules("TRANSFER TO SAV", [rule], account_id=42) is rule
    # Skipped on other accounts
    assert apply_rules("TRANSFER TO SAV", [rule], account_id=7) is None
    # And when no account_id is supplied
    assert apply_rules("TRANSFER TO SAV", [rule]) is None


def test_rule_without_account_scope_matches_any_account():
    rule = _rule("contains", "TRANSFER")
    assert apply_rules("TRANSFER TO SAV", [rule], account_id=1) is rule
    assert apply_rules("TRANSFER TO SAV", [rule], account_id=999) is rule
    assert apply_rules("TRANSFER TO SAV", [rule]) is rule


def test_rule_matches_description_when_source_is_description():
    rule = _rule("equals", "KEEP THE CHANGE TRANSFER", source="description")
    # Payee alone would NOT match this rule — source is description.
    assert apply_rules("Something else", [rule], description="KEEP THE CHANGE TRANSFER") is rule
    assert apply_rules("KEEP THE CHANGE TRANSFER", [rule]) is None


def test_rule_ignores_description_when_source_is_payee():
    rule = _rule("contains", "Spotify")
    # Even if Spotify appears in description, a payee-source rule needs payee match.
    assert apply_rules("Random", [rule], description="Spotify premium charge") is None
    assert apply_rules("Spotify USA", [rule], description="unrelated") is rule


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
