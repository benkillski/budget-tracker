from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings
from app.scheduler import create_scheduler


def test_create_scheduler_registers_daily_sync_and_digest_jobs():
    settings = Settings(digest_frequency="daily", sync_hour_utc=6)
    scheduler = create_scheduler(settings, engine=None)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"daily_sync", "digest"}


def test_weekly_digest_uses_day_of_week_trigger():
    settings = Settings(digest_frequency="weekly", sync_hour_utc=6)
    scheduler = create_scheduler(settings, engine=None)

    digest_job = scheduler.get_job("digest")
    assert isinstance(digest_job.trigger, CronTrigger)
    field_names = {f.name for f in digest_job.trigger.fields if not f.is_default}
    assert "day_of_week" in field_names


def test_sync_defaults_to_daily_cron_trigger():
    settings = Settings(digest_frequency="daily", sync_hour_utc=6, sync_interval_minutes=0)
    scheduler = create_scheduler(settings, engine=None)
    sync_job = scheduler.get_job("daily_sync")
    assert isinstance(sync_job.trigger, CronTrigger)


def test_sync_interval_overrides_hour_schedule():
    settings = Settings(digest_frequency="daily", sync_hour_utc=6, sync_interval_minutes=30)
    scheduler = create_scheduler(settings, engine=None)
    sync_job = scheduler.get_job("daily_sync")
    assert isinstance(sync_job.trigger, IntervalTrigger)
    assert sync_job.trigger.interval.total_seconds() == 30 * 60
