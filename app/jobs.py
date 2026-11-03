import logging
from calendar import monthrange
from datetime import date, timedelta

from sqlmodel import Session, func, select

from app.budget_calc import compute_budget_period, compute_income_period, month_bounds
from app.config import Settings
from app.models import AlertLog, SyncStatus, Transaction
from app.notifications import (
    AlertContext,
    DigestContent,
    RecentTransaction,
    SMTPConfig,
    send_alert_email,
    send_digest_email,
    send_sync_failure_email,
    send_sync_recovery_email,
)
from app.simplefin_client import SimpleFINClient
from app.sync_service import run_sync
from app.timeutil import utc_now

SYNC_FAILURE_RENOTIFY = timedelta(hours=24)
ALERT_RECENT_TRANSACTIONS_LIMIT = 5

logger = logging.getLogger(__name__)


def _recent_transactions(session, category_id, start, end) -> list[RecentTransaction]:
    """Return the most-recent expense transactions in a category for the
    current month, newest first, up to ALERT_RECENT_TRANSACTIONS_LIMIT."""
    rows = session.exec(
        select(Transaction)
        .where(
            Transaction.category_id == category_id,
            Transaction.posted_at >= start,
            Transaction.posted_at <= end,
            Transaction.amount_cents < 0,
        )
        .order_by(Transaction.posted_at.desc())
        .limit(ALERT_RECENT_TRANSACTIONS_LIMIT)
    ).all()
    return [
        RecentTransaction(
            posted_at_label=t.posted_at.strftime("%Y-%m-%d"),
            payee=t.payee,
            amount_cents=t.amount_cents,
        )
        for t in rows
    ]


def _smtp_config(settings: Settings) -> SMTPConfig:
    return SMTPConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_addr=settings.smtp_from,
        to_addr=settings.smtp_to,
    )


def daily_sync_job(settings: Settings, engine) -> None:
    client = SimpleFINClient(
        settings.simplefin_access_url,
        timeout_seconds=settings.simplefin_timeout_seconds,
    )
    smtp_config = _smtp_config(settings)
    with Session(engine) as session:
        status = session.get(SyncStatus, 1) or SyncStatus(id=1)
        was_in_failure_streak = status.failure_notified_at is not None
        previous_error = status.last_error
        try:
            result = run_sync(session, client, settings.warning_threshold_pct, settings.alert_threshold_pct)

            now = utc_now()
            start, end = month_bounds(now.year, now.month)
            days_in_month = monthrange(now.year, now.month)[1]
            for crossing in result.newly_crossed:
                recent = _recent_transactions(session, crossing.category_id, start, end)
                context = AlertContext(
                    crossing=crossing,
                    recent_transactions=recent,
                    days_elapsed=now.day,
                    days_in_month=days_in_month,
                )
                # Send first, log only after success: if SMTP fails, no AlertLog is
                # written, so the threshold crossing is retried on the next sync.
                send_alert_email(smtp_config, context)
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
        except Exception as exc:
            now = utc_now()
            status.last_synced_at = now
            status.last_sync_ok = False
            status.last_error = str(exc)
            # Dedupe failure emails: send on first failure in a streak OR after
            # the renotify window elapses. Don't let email errors mask the sync
            # error — that's the one the caller cares about.
            should_notify = (
                status.failure_notified_at is None
                or (now - status.failure_notified_at) >= SYNC_FAILURE_RENOTIFY
            )
            if should_notify:
                try:
                    send_sync_failure_email(smtp_config, str(exc))
                    status.failure_notified_at = now
                except Exception:
                    logger.exception("Failed to send sync-failure email")
            session.add(status)
            session.commit()
            raise

        status.last_synced_at = utc_now()
        status.last_sync_ok = True
        status.last_error = None
        if was_in_failure_streak:
            try:
                send_sync_recovery_email(smtp_config, last_error=previous_error)
            except Exception:
                logger.exception("Failed to send sync-recovery email")
        status.failure_notified_at = None
        session.add(status)
        session.commit()


def digest_job(settings: Settings, engine) -> None:
    now = utc_now()
    with Session(engine) as session:
        periods = compute_budget_period(session, now.year, now.month)
        incomes = compute_income_period(session, now.year, now.month)
        start, end = month_bounds(now.year, now.month)
        uncategorized_count = session.exec(
            select(func.count()).select_from(Transaction).where(
                Transaction.posted_at >= start,
                Transaction.posted_at <= end,
                Transaction.category_id.is_(None),
            )
        ).one()
        content = DigestContent(
            periods=periods,
            incomes=incomes,
            uncategorized_count=uncategorized_count,
            month_label=date(now.year, now.month, 1).strftime("%B %Y"),
        )
        send_digest_email(_smtp_config(settings), content)
