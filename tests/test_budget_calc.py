from datetime import datetime

from app.budget_calc import compute_budget_period, compute_income_period
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


def test_budget_period_excludes_income_categories(session):
    account = _seed_account(session)
    salary = Category(name="Salary", monthly_limit_cents=0, is_income=True)
    groceries = Category(name="Groceries", monthly_limit_cents=10000)
    session.add(salary)
    session.add(groceries)
    session.commit()
    session.refresh(salary)
    session.refresh(groceries)

    results = compute_budget_period(session, 2026, 9)
    assert [r.category_name for r in results] == ["Groceries"]


def test_fixed_category_states(session):
    account = _seed_account(session)
    rent = Category(name="Rent", monthly_limit_cents=140000, is_fixed=True)
    insurance = Category(name="Auto Insurance", monthly_limit_cents=24000, is_fixed=True)
    phone = Category(name="Phone", monthly_limit_cents=10000, is_fixed=True)
    session.add(rent)
    session.add(insurance)
    session.add(phone)
    session.commit()
    session.refresh(rent)
    session.refresh(insurance)
    session.refresh(phone)

    # Rent: not yet posted this month → pending
    # Auto Insurance: posted at exactly $240 → paid
    session.add(
        Transaction(account_id=account.id, posted_at=datetime(2026, 10, 1), payee="State Farm",
                    amount_cents=-24000, category_id=insurance.id)
    )
    # Phone: billed at $108 (bill went up — surprise)
    session.add(
        Transaction(account_id=account.id, posted_at=datetime(2026, 10, 1), payee="T-Mobile",
                    amount_cents=-10800, category_id=phone.id)
    )
    session.commit()

    results = {r.category_name: r for r in compute_budget_period(session, 2026, 10)}
    assert results["Rent"].fixed_state == "pending"
    assert results["Auto Insurance"].fixed_state == "paid"
    assert results["Phone"].fixed_state == "surprise"


def test_parent_rolls_up_children_spending(session):
    account = _seed_account(session)
    food = Category(name="Food", monthly_limit_cents=60000)
    session.add(food)
    session.commit()
    session.refresh(food)
    groceries = Category(name="Groceries", monthly_limit_cents=40000, parent_id=food.id)
    dining = Category(name="Dining Out", monthly_limit_cents=20000, parent_id=food.id)
    session.add(groceries)
    session.add(dining)
    session.commit()
    session.refresh(groceries)
    session.refresh(dining)

    session.add_all(
        [
            Transaction(account_id=account.id, posted_at=datetime(2026, 10, 5), payee="Kroger",
                        amount_cents=-10000, category_id=groceries.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 10, 10), payee="Chipotle",
                        amount_cents=-2500, category_id=dining.id),
            # Direct spend on the parent too — rolled-up should include this plus children.
            Transaction(account_id=account.id, posted_at=datetime(2026, 10, 12), payee="Mystery food",
                        amount_cents=-500, category_id=food.id),
        ]
    )
    session.commit()

    results = {r.category_name: r for r in compute_budget_period(session, 2026, 10)}
    assert results["Groceries"].spent_cents == 10000
    assert results["Groceries"].rolled_up_spent_cents == 10000  # no own children
    assert results["Dining Out"].spent_cents == 2500
    # Food's own spend is 500, plus 10000 + 2500 from children.
    assert results["Food"].spent_cents == 500
    assert results["Food"].rolled_up_spent_cents == 13000
    assert results["Food"].parent_id is None
    assert results["Groceries"].parent_id == food.id
    assert results["Food"].is_parent is True
    assert results["Groceries"].is_parent is False


def test_income_period_sums_positives_for_income_categories(session):
    account = _seed_account(session)
    salary = Category(name="Salary", monthly_limit_cents=0, is_income=True)
    refunds = Category(name="Refunds", monthly_limit_cents=0, is_income=True)
    groceries = Category(name="Groceries", monthly_limit_cents=10000, is_income=False)
    session.add(salary)
    session.add(refunds)
    session.add(groceries)
    session.commit()
    session.refresh(salary)
    session.refresh(refunds)
    session.refresh(groceries)

    session.add_all(
        [
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 1), payee="Paycheck 1",
                        amount_cents=250000, category_id=salary.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 15), payee="Paycheck 2",
                        amount_cents=250000, category_id=salary.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 20), payee="Target refund",
                        amount_cents=1500, category_id=refunds.id),
            # Prior-month paycheck must NOT count.
            Transaction(account_id=account.id, posted_at=datetime(2026, 8, 31), payee="Old paycheck",
                        amount_cents=250000, category_id=salary.id),
            # Groceries row stays out of income results, even if positive.
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 10), payee="Groceries refund",
                        amount_cents=500, category_id=groceries.id),
        ]
    )
    session.commit()

    results = {r.category_name: r.received_cents for r in compute_income_period(session, 2026, 9)}
    assert results == {"Salary": 500000, "Refunds": 1500}
