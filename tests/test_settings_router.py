from datetime import datetime
from unittest.mock import patch

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
        data={"name": "Dining", "monthly_limit": "150.50"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    session.refresh(category)
    assert category.monthly_limit_cents == 15050


def test_update_category_renames_it(session, client):
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        f"/settings/categories/{category.id}",
        data={"name": "Dining Out", "monthly_limit": "100.00"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    session.refresh(category)
    assert category.name == "Dining Out"
    assert category.monthly_limit_cents == 10000


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


def test_create_category_with_parent(session, client):
    parent = Category(name="Food", monthly_limit_cents=60000)
    session.add(parent)
    session.commit()
    session.refresh(parent)

    response = client.post(
        "/settings/categories",
        data={"name": "Groceries", "monthly_limit": "400.00", "parent_id": str(parent.id)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    child = session.exec(select(Category).where(Category.name == "Groceries")).first()
    assert child.parent_id == parent.id


def test_create_category_rejects_grandchild(session, client):
    """One-level hierarchy only: can't make a child of a child."""
    parent = Category(name="Food", monthly_limit_cents=60000)
    session.add(parent)
    session.commit()
    session.refresh(parent)
    middle = Category(name="Groceries", monthly_limit_cents=40000, parent_id=parent.id)
    session.add(middle)
    session.commit()
    session.refresh(middle)

    response = client.post(
        "/settings/categories",
        data={"name": "Organic", "monthly_limit": "0", "parent_id": str(middle.id)},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_update_category_rejects_self_as_parent(session, client):
    category = Category(name="Food", monthly_limit_cents=60000)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        f"/settings/categories/{category.id}",
        data={"name": "Food", "monthly_limit": "600.00", "parent_id": str(category.id)},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_update_category_rejects_parent_when_it_has_children(session, client):
    parent = Category(name="Food", monthly_limit_cents=60000)
    session.add(parent)
    session.commit()
    session.refresh(parent)
    other_top = Category(name="Housing", monthly_limit_cents=200000)
    session.add(other_top)
    session.commit()
    session.refresh(other_top)
    child = Category(name="Groceries", monthly_limit_cents=40000, parent_id=parent.id)
    session.add(child)
    session.commit()

    # Can't flip Food (which has children) into Housing's child.
    response = client.post(
        f"/settings/categories/{parent.id}",
        data={"name": "Food", "monthly_limit": "600.00", "parent_id": str(other_top.id)},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_create_category_with_is_tracked_only_flag(session, client):
    response = client.post(
        "/settings/categories",
        data={"name": "Health", "monthly_limit": "0", "is_tracked_only": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    category = session.exec(select(Category).where(Category.name == "Health")).first()
    assert category.is_tracked_only is True
    assert category.monthly_limit_cents == 0


def test_dashboard_renders_tracked_only_category(session, client):
    from app.models import Account, Transaction
    from datetime import datetime
    from app.timeutil import utc_now

    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank", balance_cents=0)
    health = Category(name="Health", monthly_limit_cents=0, is_tracked_only=True)
    session.add(account)
    session.add(health)
    session.commit()
    session.refresh(account)
    session.refresh(health)
    now = utc_now()
    session.add(
        Transaction(account_id=account.id, posted_at=now, payee="Doctor",
                    amount_cents=-15000, category_id=health.id)
    )
    session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert "Health" in response.text
    assert "tracked" in response.text  # the state tag
    assert "$150.00" in response.text


def test_create_category_with_is_income_flag(session, client):
    response = client.post(
        "/settings/categories",
        data={"name": "Salary", "monthly_limit": "0", "is_income": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    category = session.exec(select(Category).where(Category.name == "Salary")).first()
    assert category.is_income is True


def test_sync_now_requires_simplefin_configured(client, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "simplefin_access_url", "")

    response = client.post("/settings/sync-now", follow_redirects=False)
    assert response.status_code == 303
    assert "sync=error" in response.headers["location"]
    assert "not%20configured" in response.headers["location"].lower()


def test_sync_now_redirects_ok_on_success(client, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "simplefin_access_url", "https://user:pass@bridge.example.com/sf")

    with patch("app.routers.settings.daily_sync_job") as mock_job:
        response = client.post("/settings/sync-now", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?sync=ok"
    mock_job.assert_called_once()


def test_sync_now_surfaces_error_message_on_failure(client, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "simplefin_access_url", "https://user:pass@bridge.example.com/sf")

    with patch("app.routers.settings.daily_sync_job", side_effect=RuntimeError("broker unreachable")):
        response = client.post("/settings/sync-now", follow_redirects=False)

    assert response.status_code == 303
    assert "sync=error" in response.headers["location"]
    assert "broker%20unreachable" in response.headers["location"]


def test_settings_page_renders_sync_banner(client, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "simplefin_access_url", "https://user:pass@bridge.example.com/sf")

    ok_response = client.get("/settings?sync=ok")
    assert ok_response.status_code == 200
    assert "Sync complete" in ok_response.text

    error_response = client.get("/settings?sync=error&msg=network+down")
    assert "Sync failed" in error_response.text
    assert "network down" in error_response.text


def test_update_category_toggles_is_income(session, client):
    category = Category(name="Salary", monthly_limit_cents=0, is_income=False)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        f"/settings/categories/{category.id}",
        data={"name": category.name, "monthly_limit": "0", "is_income": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.refresh(category)
    assert category.is_income is True

    # Omitting the checkbox (unchecked) flips it off.
    response = client.post(
        f"/settings/categories/{category.id}",
        data={"name": category.name, "monthly_limit": "0"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.refresh(category)
    assert category.is_income is False
