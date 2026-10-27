from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.jobs import daily_sync_job, digest_job
from app.models import AlertLog, Category, Rule, SyncStatus
from app.sync_service import SyncResult, ThresholdCrossing


def _make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@patch("app.jobs.send_alert_email")
@patch("app.jobs.run_sync")
@patch("app.jobs.SimpleFINClient")
def test_daily_sync_job_sends_alert_for_each_crossing(mock_client_class, mock_run_sync, mock_send_alert):
    engine = _make_engine()
    settings = Settings(simplefin_access_url="https://u:p@bridge.example.com/simplefin")
    crossing = ThresholdCrossing(category_id=1, category_name="Groceries", threshold_pct=100,
                                  spent_cents=3500, limit_cents=3000)
    mock_run_sync.return_value = SyncResult(new_transaction_count=1, newly_crossed=[crossing])

    daily_sync_job(settings, engine)

    mock_client_class.assert_called_once_with(
        settings.simplefin_access_url, timeout_seconds=settings.simplefin_timeout_seconds
    )
    mock_run_sync.assert_called_once()
    mock_send_alert.assert_called_once()
    assert mock_send_alert.call_args[0][1] is crossing

    with Session(engine) as session:
        status = session.get(SyncStatus, 1)
        assert status.last_sync_ok is True
        assert status.last_synced_at is not None


@patch("app.jobs.send_alert_email")
@patch("app.jobs.run_sync")
@patch("app.jobs.SimpleFINClient")
def test_daily_sync_job_records_failure_and_reraises(mock_client_class, mock_run_sync, mock_send_alert):
    engine = _make_engine()
    settings = Settings(simplefin_access_url="https://u:p@bridge.example.com/simplefin")
    mock_run_sync.side_effect = RuntimeError("SimpleFIN returned 401")

    with pytest.raises(RuntimeError):
        daily_sync_job(settings, engine)

    mock_send_alert.assert_not_called()
    with Session(engine) as session:
        status = session.get(SyncStatus, 1)
        assert status.last_sync_ok is False
        assert status.last_error == "SimpleFIN returned 401"


@patch("app.jobs.send_alert_email")
@patch("app.jobs.run_sync")
@patch("app.jobs.SimpleFINClient")
def test_daily_sync_job_writes_alert_log_after_successful_send(mock_client_class, mock_run_sync, mock_send_alert):
    engine = _make_engine()
    settings = Settings(simplefin_access_url="https://u:p@bridge.example.com/simplefin")
    crossing = ThresholdCrossing(category_id=1, category_name="Groceries", threshold_pct=100,
                                  spent_cents=3500, limit_cents=3000)
    mock_run_sync.return_value = SyncResult(new_transaction_count=1, newly_crossed=[crossing])

    daily_sync_job(settings, engine)

    with Session(engine) as session:
        logs = session.exec(select(AlertLog)).all()
        assert len(logs) == 1
        assert logs[0].category_id == 1
        assert logs[0].threshold_pct == 100


@patch("app.jobs.send_alert_email")
@patch("app.jobs.run_sync")
@patch("app.jobs.SimpleFINClient")
def test_daily_sync_job_does_not_log_alert_on_smtp_failure(mock_client_class, mock_run_sync, mock_send_alert):
    engine = _make_engine()
    settings = Settings(simplefin_access_url="https://u:p@bridge.example.com/simplefin")
    crossing = ThresholdCrossing(category_id=1, category_name="Groceries", threshold_pct=100,
                                  spent_cents=3500, limit_cents=3000)
    mock_run_sync.return_value = SyncResult(new_transaction_count=1, newly_crossed=[crossing])
    mock_send_alert.side_effect = RuntimeError("SMTP connection refused")

    with pytest.raises(RuntimeError):
        daily_sync_job(settings, engine)

    with Session(engine) as session:
        logs = session.exec(select(AlertLog)).all()
        assert logs == []
        status = session.get(SyncStatus, 1)
        assert status.last_sync_ok is False
        assert status.last_error == "SMTP connection refused"


@patch("app.jobs.send_digest_email")
def test_digest_job_sends_digest_with_current_budget_periods(mock_send_digest):
    engine = _make_engine()
    with Session(engine) as session:
        category = Category(name="Groceries", monthly_limit_cents=3000)
        session.add(category)
        session.commit()
        session.refresh(category)
    settings = Settings()

    digest_job(settings, engine)

    mock_send_digest.assert_called_once()
    periods_arg = mock_send_digest.call_args[0][1]
    assert any(p.category_name == "Groceries" for p in periods_arg)
