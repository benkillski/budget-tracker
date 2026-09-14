from datetime import datetime

from app.models import Account, Category, Transaction


def _seed(session):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Groceries", monthly_limit_cents=30000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    categorized = Transaction(account_id=account.id, posted_at=datetime(2026, 9, 1), payee="Kroger",
                               amount_cents=-1000, category_id=category.id)
    uncategorized = Transaction(account_id=account.id, posted_at=datetime(2026, 9, 2), payee="Mystery Charge",
                                 amount_cents=-500)
    session.add(categorized)
    session.add(uncategorized)
    session.commit()
    session.refresh(categorized)
    session.refresh(uncategorized)
    return category, categorized, uncategorized


def test_list_transactions_shows_all_by_default(session, client):
    _seed(session)

    response = client.get("/transactions")

    assert response.status_code == 200
    assert "Kroger" in response.text
    assert "Mystery Charge" in response.text


def test_list_transactions_filters_to_uncategorized(session, client):
    _seed(session)

    response = client.get("/transactions?uncategorized_only=true")

    assert response.status_code == 200
    assert "Mystery Charge" in response.text
    assert "Kroger" not in response.text


def test_set_category_persists_and_returns_updated_row(session, client):
    category, _categorized, uncategorized = _seed(session)

    response = client.post(
        f"/transactions/{uncategorized.id}/category",
        data={"category_id": str(category.id)},
    )

    assert response.status_code == 200
    assert "selected" in response.text
    assert "Groceries" in response.text

    session.refresh(uncategorized)
    assert uncategorized.category_id == category.id
