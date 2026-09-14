from datetime import datetime, timezone


def utc_now() -> datetime:
    """Current time as a naive datetime representing UTC.

    Naive (no tzinfo) so it compares cleanly against other stored
    timestamps in SQLite, which has no native timezone-aware type.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
