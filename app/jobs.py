from sqlmodel import Session

from app.budget_calc import compute_budget_period
from app.config import Settings
from app.models import AlertLog, SyncStatus
from app.notifications import SMTPConfig, send_alert_email, send_digest_email
from app.simplefin_client import SimpleFINClient
from app.sync_service import run_sync
from app.timeutil import utc_now


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
    with Session(engine) as session:
        status = session.get(SyncStatus, 1) or SyncStatus(id=1)
        try:
            result = run_sync(session, client, settings.warning_threshold_pct, settings.alert_threshold_pct)

            smtp_config = _smtp_config(settings)
            now = utc_now()
            for crossing in result.newly_crossed:
                # Send first, log only after success: if SMTP fails, no AlertLog is
                # written, so the threshold crossing is retried on the next sync.
                send_alert_email(smtp_config, crossing)
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
            status.last_synced_at = utc_now()
            status.last_sync_ok = False
            status.last_error = str(exc)
            session.add(status)
            session.commit()
            raise

        status.last_synced_at = utc_now()
        status.last_sync_ok = True
        status.last_error = None
        session.add(status)
        session.commit()


def digest_job(settings: Settings, engine) -> None:
    now = utc_now()
    with Session(engine) as session:
        periods = compute_budget_period(session, now.year, now.month)
        send_digest_email(_smtp_config(settings), periods)
