from datetime import datetime

from app.models import Account, AlertLog, Category, Rule, SyncStatus, Transaction


def test_can_create_and_query_each_model(session):
    account = Account(
        simplefin_account_id="acc-1",
        name="Checking",
        institution="Test Bank",
        balance_cents=10000,
    )
    category = Category(name="Groceries", monthly_limit_cents=40000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    rule = Rule(match_type="contains", match_value="KROGER", category_id=category.id, priority=1)
    session.add(rule)
    session.commit()
    session.refresh(rule)

    transaction = Transaction(
        account_id=account.id,
        posted_at=datetime(2026, 9, 1),
        payee="KROGER #123",
        amount_cents=-2599,
        category_id=category.id,
        rule_applied_id=rule.id,
    )
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    alert = AlertLog(category_id=category.id, year=2026, month=9, threshold_pct=100, sent_at=datetime(2026, 9, 15))
    session.add(alert)
    session.commit()
    session.refresh(alert)

    sync_status = SyncStatus(id=1, last_synced_at=datetime(2026, 9, 15, 6, 0), last_sync_ok=True)
    session.add(sync_status)
    session.commit()
    session.refresh(sync_status)

    assert account.id is not None
    assert category.id is not None
    assert rule.category_id == category.id
    assert transaction.category_id == category.id
    assert transaction.rule_applied_id == rule.id
    assert alert.category_id == category.id
    assert sync_status.last_sync_ok is True
