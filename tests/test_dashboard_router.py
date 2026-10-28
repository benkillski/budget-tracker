from datetime import datetime

from app.models import Account, Category, SyncStatus, Transaction
from app.timeutil import utc_now


def test_home_shows_no_sync_message_when_never_synced(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "No sync has run yet" in response.text


def test_home_shows_failure_banner_when_last_sync_failed(session, client):
    session.add(SyncStatus(id=1, last_synced_at=datetime(2026, 9, 14, 6, 0), last_sync_ok=False,
                            last_error="SimpleFIN returned 401"))
    session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert "Last sync failed" in response.text
    assert "SimpleFIN returned 401" in response.text


def test_home_shows_accounts_and_budget_progress(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank", balance_cents=150000)
    category = Category(name="Groceries", monthly_limit_cents=30000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    session.add(
        Transaction(account_id=account.id, posted_at=utc_now(), payee="Store",
                    amount_cents=-1500, category_id=category.id)
    )
    session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert "Checking" in response.text
    assert "$1,500.00" in response.text
    assert "Groceries" in response.text


def test_home_shows_last_synced_time_on_success(session, client):
    session.add(SyncStatus(id=1, last_synced_at=utc_now(), last_sync_ok=True))
    session.commit()
    response = client.get("/")
    assert response.status_code == 200
    assert "Synced" in response.text


def test_home_filters_to_requested_month(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank", balance_cents=0)
    category = Category(name="Groceries", monthly_limit_cents=30000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)
    session.add(
        Transaction(account_id=account.id, posted_at=datetime(2026, 7, 15), payee="July Store",
                    amount_cents=-1500, category_id=category.id)
    )
    session.add(
        Transaction(account_id=account.id, posted_at=datetime(2026, 8, 15), payee="August Store",
                    amount_cents=-7777, category_id=category.id)
    )
    session.commit()

    july_response = client.get("/?year=2026&month=7")
    assert july_response.status_code == 200
    assert "July 2026" in july_response.text
    assert "$15.00" in july_response.text
    assert "$77.77" not in july_response.text

    august_response = client.get("/?year=2026&month=8")
    assert "August 2026" in august_response.text
    assert "$77.77" in august_response.text
    assert "Today" in august_response.text  # non-current month shows the Today link


def test_home_month_nav_rolls_year_at_december(client):
    response = client.get("/?year=2026&month=12")
    assert response.status_code == 200
    # Next link rolls to Jan 2027
    assert "year=2027&month=1" in response.text
    # Prev link stays in 2026
    assert "year=2026&month=11" in response.text


def test_home_falls_back_to_current_month_when_params_invalid(client):
    now = utc_now()
    response = client.get("/?year=2026&month=99")
    assert response.status_code == 200
    assert now.strftime("%B %Y") in response.text


def test_home_shows_income_and_net(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank", balance_cents=0)
    salary = Category(name="Salary", monthly_limit_cents=0, is_income=True)
    groceries = Category(name="Groceries", monthly_limit_cents=100000)
    session.add(account)
    session.add(salary)
    session.add(groceries)
    session.commit()
    session.refresh(account)
    session.refresh(salary)
    session.refresh(groceries)
    session.add_all(
        [
            Transaction(account_id=account.id, posted_at=datetime(2026, 7, 1), payee="Paycheck",
                        amount_cents=500000, category_id=salary.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 7, 15), payee="Grocery store",
                        amount_cents=-15000, category_id=groceries.id),
        ]
    )
    session.commit()

    response = client.get("/?year=2026&month=7")
    assert response.status_code == 200
    # Income total shows up in the "This month" summary tiles.
    assert "$5,000.00" in response.text
    # Spending total
    assert "$150.00" in response.text
    # Net = 5000 - 150 = 4850
    assert "$4,850.00" in response.text
