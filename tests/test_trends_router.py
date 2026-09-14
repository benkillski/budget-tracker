from datetime import date, datetime

from app.models import Account, Category, Transaction


def test_trends_includes_budgeted_category_series(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Groceries", monthly_limit_cents=30000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    today = date.today()
    session.add(
        Transaction(account_id=account.id, posted_at=datetime(today.year, today.month, 1), payee="Store",
                    amount_cents=-2000, category_id=category.id)
    )
    session.commit()

    response = client.get("/trends")

    assert response.status_code == 200
    assert "Groceries" in response.text
    assert f"{today.year}-{today.month:02d}" in response.text
