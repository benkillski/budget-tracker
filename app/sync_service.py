from dataclasses import dataclass, field
from datetime import timedelta

from sqlmodel import Session, select

from app.budget_calc import compute_budget_period
from app.models import Account, AlertLog, Rule, Transaction
from app.rules_engine import apply_rules
from app.simplefin_client import SimpleFINClient
from app.timeutil import utc_now

SYNC_LOOKBACK_DAYS = 35


@dataclass
class ThresholdCrossing:
    category_id: int
    category_name: str
    threshold_pct: int
    spent_cents: int
    limit_cents: int


@dataclass
class SyncResult:
    new_transaction_count: int = 0
    newly_crossed: list[ThresholdCrossing] = field(default_factory=list)


def run_sync(session: Session, client: SimpleFINClient, warning_pct: int, alert_pct: int) -> SyncResult:
    result = SyncResult()
    start_date = utc_now() - timedelta(days=SYNC_LOOKBACK_DAYS)
    sf_accounts = client.get_accounts(start_date=start_date)

    rules = session.exec(select(Rule).order_by(Rule.priority)).all()

    for sf_account in sf_accounts:
        account = session.exec(
            select(Account).where(Account.simplefin_account_id == sf_account.id)
        ).first()
        if account is None:
            account = Account(
                simplefin_account_id=sf_account.id,
                name=sf_account.name,
                institution=sf_account.org_name,
                balance_cents=sf_account.balance_cents,
            )
        else:
            account.balance_cents = sf_account.balance_cents
        session.add(account)
        session.flush()

        for sf_txn in sf_account.transactions:
            existing = session.exec(
                select(Transaction).where(Transaction.simplefin_transaction_id == sf_txn.id)
            ).first()
            if existing is not None:
                existing.pending = sf_txn.pending
                if not existing.description and sf_txn.description:
                    existing.description = sf_txn.description
                session.add(existing)
                continue

            matched_rule = apply_rules(
                sf_txn.payee,
                rules,
                description=sf_txn.description or "",
                memo=sf_txn.memo or "",
                account_id=account.id,
            )
            session.add(
                Transaction(
                    simplefin_transaction_id=sf_txn.id,
                    account_id=account.id,
                    posted_at=sf_txn.posted_at,
                    transacted_at=sf_txn.transacted_at,
                    payee=sf_txn.payee,
                    description=sf_txn.description or None,
                    memo=sf_txn.memo or None,
                    amount_cents=sf_txn.amount_cents,
                    pending=sf_txn.pending,
                    category_id=matched_rule.category_id if matched_rule else None,
                    rule_applied_id=matched_rule.id if matched_rule else None,
                    import_source="simplefin",
                )
            )
            result.new_transaction_count += 1

    session.commit()

    now = utc_now()
    budget_periods = compute_budget_period(session, now.year, now.month)
    for period in budget_periods:
        if period.limit_cents <= 0:
            continue
        for threshold in sorted({warning_pct, alert_pct}):
            if period.pct_used < threshold:
                continue
            already_alerted = session.exec(
                select(AlertLog).where(
                    AlertLog.category_id == period.category_id,
                    AlertLog.year == now.year,
                    AlertLog.month == now.month,
                    AlertLog.threshold_pct == threshold,
                )
            ).first()
            if already_alerted is not None:
                continue
            result.newly_crossed.append(
                ThresholdCrossing(
                    category_id=period.category_id,
                    category_name=period.category_name,
                    threshold_pct=threshold,
                    spent_cents=period.spent_cents,
                    limit_cents=period.limit_cents,
                )
            )
    return result
