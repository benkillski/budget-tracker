from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.budget_calc import compute_budget_period
from app.db import get_session
from app.timeutil import utc_now

router = APIRouter(prefix="/trends")
templates = Jinja2Templates(directory="app/templates")

MONTHS_BACK = 6


@router.get("")
def trends(request: Request, session: Session = Depends(get_session)):
    today = utc_now().date()
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(MONTHS_BACK):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()

    labels = [f"{y}-{m:02d}" for y, m in months]
    series: dict[str, list[float]] = {}
    for y, m in months:
        periods = compute_budget_period(session, y, m)
        for period in periods:
            if period.limit_cents <= 0:
                continue
            series.setdefault(period.category_name, []).append(period.spent_cents / 100)

    return templates.TemplateResponse(request, "trends.html", {"labels": labels, "series": series})
