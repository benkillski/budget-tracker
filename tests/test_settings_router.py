from datetime import datetime

from sqlmodel import select

from app.models import Account, AlertLog, Category, Rule, Transaction


def test_create_category_persists_limit_in_cents(session, client):
    response = client.post(
        "/settings/categories",
        data={"name": "Groceries", "monthly_limit": "300.00"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    category = session.exec(select(Category)).first()
    assert category.name == "Groceries"
    assert category.monthly_limit_cents == 30000


def test_update_category_limit_changes_existing_category(session, client):
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        f"/settings/categories/{category.id}",
        data={"monthly_limit": "150.50"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    session.refresh(category)
    assert category.monthly_limit_cents == 15050


def test_settings_page_shows_simplefin_not_configured_by_default(client, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "simplefin_access_url", "")
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Not configured" in response.text


def test_delete_category_uncategorizes_transactions_and_removes_alert_logs(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)
    txn = Transaction(
        account_id=account.id,
        posted_at=datetime(2026, 9, 1),
        payee="Chipotle",
        amount_cents=-1000,
        category_id=category.id,
    )
    session.add(txn)
    session.add(
        AlertLog(
            category_id=category.id, year=2026, month=9, threshold_pct=80, sent_at=datetime(2026, 9, 15)
        )
    )
    session.commit()

    response = client.post(f"/settings/categories/{category.id}/delete", follow_redirects=False)
    assert response.status_code == 303

    assert session.get(Category, category.id) is None
    session.refresh(txn)
    assert txn.category_id is None
    assert session.exec(select(AlertLog)).first() is None


def test_delete_category_blocks_when_rule_still_targets_it(session, client):
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)
    session.add(Rule(match_type="contains", match_value="Chipotle", category_id=category.id, priority=0))
    session.commit()

    response = client.post(f"/settings/categories/{category.id}/delete", follow_redirects=False)
    assert response.status_code == 409

    assert session.get(Category, category.id) is not None


def test_delete_category_returns_404_for_unknown_id(client):
    response = client.post("/settings/categories/99999/delete", follow_redirects=False)
    assert response.status_code == 404


def test_create_category_with_is_income_flag(session, client):
    response = client.post(
        "/settings/categories",
        data={"name": "Salary", "monthly_limit": "0", "is_income": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    category = session.exec(select(Category).where(Category.name == "Salary")).first()
    assert category.is_income is True


def test_update_category_toggles_is_income(session, client):
    category = Category(name="Salary", monthly_limit_cents=0, is_income=False)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        f"/settings/categories/{category.id}",
        data={"monthly_limit": "0", "is_income": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.refresh(category)
    assert category.is_income is True

    # Omitting the checkbox (unchecked) flips it off.
    response = client.post(
        f"/settings/categories/{category.id}",
        data={"monthly_limit": "0"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.refresh(category)
    assert category.is_income is False
