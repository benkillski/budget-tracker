from datetime import datetime

from sqlmodel import select

from app.models import Account, AlertLog, Category, Rule, Transaction
from app.simplefin_client import SimpleFINAccount, SimpleFINTransaction
from app.sync_service import run_sync
from app.timeutil import utc_now


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
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), transacted_at=None,
                                  payee="KROGER #1", description="KROGER #1 CINCINNATI OH", memo="",
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
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), transacted_at=None,
                                  payee="KROGER #1", description="", memo="",
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
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), transacted_at=None,
                                  payee="KROGER #1", description="", memo="",
                                  amount_cents=-3500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    result = run_sync(session, client, warning_pct=80, alert_pct=100)

    crossed_thresholds = {c.threshold_pct for c in result.newly_crossed}
    assert crossed_thresholds == {80, 100}
    assert all(c.category_name == "Groceries" for c in result.newly_crossed)

    # run_sync no longer writes AlertLog itself (see app/jobs.py::daily_sync_job,
    # which logs only after a successful send). Simulate that here so the
    # "alert once per month" gate inside run_sync can be exercised.
    now = utc_now()
    for crossing in result.newly_crossed:
        session.add(
            AlertLog(
                category_id=crossing.category_id,
                year=now.year,
                month=now.month,
                threshold_pct=crossing.threshold_pct,
                sent_at=now,
            )
        )
    session.commit()

    # A second sync with no new transactions must not re-alert.
    fake_account.transactions = []
    second = run_sync(session, client, warning_pct=80, alert_pct=100)
    assert second.newly_crossed == []


def test_run_sync_stores_description_on_new_transaction(session):
    _seed_category_and_rule(session)
    fake_account = SimpleFINAccount(
        id="acc-1", name="Checking", org_name="Test Bank", balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), transacted_at=None,
                                  payee="KROGER #1", description="KROGER #1 CINCINNATI OH", memo="",
                                  amount_cents=-2500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    run_sync(session, client, warning_pct=80, alert_pct=100)

    txn = session.exec(
        select(Transaction).where(Transaction.simplefin_transaction_id == "txn-1")
    ).first()
    assert txn.description == "KROGER #1 CINCINNATI OH"


def test_run_sync_backfills_description_on_existing_transaction(session):
    _seed_category_and_rule(session)
    fake_account = SimpleFINAccount(
        id="acc-1", name="Checking", org_name="Test Bank", balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), transacted_at=None,
                                  payee="KROGER #1", description="", memo="",
                                  amount_cents=-2500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])
    run_sync(session, client, warning_pct=80, alert_pct=100)

    txn = session.exec(
        select(Transaction).where(Transaction.simplefin_transaction_id == "txn-1")
    ).first()
    assert txn.description is None

    fake_account.transactions = [
        SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), transacted_at=None,
                              payee="KROGER #1", description="KROGER #1 CINCINNATI OH", memo="",
                              amount_cents=-2500, pending=False),
    ]
    run_sync(session, client, warning_pct=80, alert_pct=100)

    session.refresh(txn)
    assert txn.description == "KROGER #1 CINCINNATI OH"
