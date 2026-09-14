from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.jobs import daily_sync_job, digest_job


def create_scheduler(settings: Settings, engine) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        daily_sync_job,
        trigger=CronTrigger(hour=settings.sync_hour_utc, minute=0),
        args=[settings, engine],
        id="daily_sync",
        replace_existing=True,
    )
    if settings.digest_frequency == "weekly":
        digest_trigger = CronTrigger(day_of_week="mon", hour=settings.sync_hour_utc, minute=15)
    else:
        digest_trigger = CronTrigger(hour=settings.sync_hour_utc, minute=15)
    scheduler.add_job(
        digest_job,
        trigger=digest_trigger,
        args=[settings, engine],
        id="digest",
        replace_existing=True,
    )
    return scheduler
