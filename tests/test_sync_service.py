from datetime import datetime

from sqlmodel import select

from app.models import Account, Category, Rule
from app.simplefin_client import SimpleFINAccount, SimpleFINTransaction
from app.sync_service import run_sync


class FakeSimpleFINClient:
    def __init__(self, accounts: list[SimpleFINAccount]):
        self._accounts = accounts

    def get_accounts(self, start_date=None):
        return self._accounts


def _seed_category_and_rule(session) -> Category:
    category = Category(name="Groceries", monthly_limit_cents=3000)
    session.add(category)
    session.commit()
    session.refresh(category)
    session.add(Rule(match_type="contains", match_value="KROGER", category_id=category.id, priority=0))
    session.commit()
    return category


def test_run_sync_inserts_new_transactions_and_categorizes_them(session):
    category = _seed_category_and_rule(session)
    fake_account = SimpleFINAccount(
        id="acc-1",
        name="Checking",
        org_name="Test Bank",
        balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), payee="KROGER #1",
                                  amount_cents=-2500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    result = run_sync(session, client, warning_pct=80, alert_pct=100)

    assert result.new_transaction_count == 1
    account = session.exec(
        select(Account).where(Account.simplefin_account_id == "acc-1")
    ).first()
    assert account is not None
    assert account.balance_cents == 50000


def test_run_sync_does_not_duplicate_existing_transactions(session):
    _seed_category_and_rule(session)
    fake_account = SimpleFINAccount(
        id="acc-1", name="Checking", org_name="Test Bank", balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), payee="KROGER #1",
                                  amount_cents=-2500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    first = run_sync(session, client, warning_pct=80, alert_pct=100)
    second = run_sync(session, client, warning_pct=80, alert_pct=100)

    assert first.new_transaction_count == 1
    assert second.new_transaction_count == 0


def test_run_sync_reports_newly_crossed_thresholds_once(session):
    category = _seed_category_and_rule(session)  # limit is 3000 cents ($30)
    fake_account = SimpleFINAccount(
        id="acc-1", name="Checking", org_name="Test Bank", balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), payee="KROGER #1",
                                  amount_cents=-3500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    result = run_sync(session, client, warning_pct=80, alert_pct=100)

    crossed_thresholds = {c.threshold_pct for c in result.newly_crossed}
    assert crossed_thresholds == {80, 100}
    assert all(c.category_name == "Groceries" for c in result.newly_crossed)

    # A second sync with no new transactions must not re-alert.
    fake_account.transactions = []
    second = run_sync(session, client, warning_pct=80, alert_pct=100)
    assert second.newly_crossed == []
