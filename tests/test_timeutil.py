from datetime import datetime

from app.timeutil import utc_now


def test_utc_now_returns_naive_datetime():
    result = utc_now()
    assert isinstance(result, datetime)
    assert result.tzinfo is None
