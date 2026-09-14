from datetime import datetime

from app.budget_calc import compute_budget_period
from app.models import Account, Category, Transaction


def _seed_account(session) -> Account:
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_sums_only_expenses_in_the_given_month(session):
    account = _seed_account(session)
    category = Category(name="Groceries", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    session.add_all(
        [
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 5), payee="Store A",
                        amount_cents=-2000, category_id=category.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 20), payee="Store B",
                        amount_cents=-1500, category_id=category.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 8, 31), payee="Store C (last month)",
                        amount_cents=-5000, category_id=category.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 10), payee="Refund",
                        amount_cents=500, category_id=category.id),
        ]
    )
    session.commit()

    [result] = compute_budget_period(session, 2026, 9)

    assert result.category_name == "Groceries"
    assert result.limit_cents == 10000
    assert result.spent_cents == 3500
    assert result.remaining_cents == 6500
    assert result.pct_used == 35.0


def test_category_with_no_transactions_has_zero_spend(session):
    session.add(Category(name="Dining", monthly_limit_cents=5000))
    session.commit()

    [result] = compute_budget_period(session, 2026, 9)

    assert result.spent_cents == 0
    assert result.pct_used == 0.0


def test_pct_used_is_zero_when_limit_is_zero(session):
    session.add(Category(name="Misc", monthly_limit_cents=0))
    session.commit()

    [result] = compute_budget_period(session, 2026, 9)

    assert result.pct_used == 0.0
