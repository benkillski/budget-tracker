from datetime import datetime

from app.models import Account, Category, SyncStatus, Transaction


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
        Transaction(account_id=account.id, posted_at=datetime.utcnow(), payee="Store",
                    amount_cents=-1500, category_id=category.id)
    )
    session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert "Checking" in response.text
    assert "$1,500.00" in response.text
    assert "Groceries" in response.text
