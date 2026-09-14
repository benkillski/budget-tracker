from apscheduler.triggers.cron import CronTrigger

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
