from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.budget_calc import compute_budget_period, compute_income_period
from app.db import get_session
from app.models import Account, SyncStatus
from app.money import format_money
from app.timeutil import utc_now

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, (index % 12) + 1


@router.get("/")
def home(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    session: Session = Depends(get_session),
):
    now = utc_now()
    if year is None or month is None or not (1 <= month <= 12):
        year, month = now.year, now.month

    periods = compute_budget_period(session, year, month)
    incomes = compute_income_period(session, year, month)
    accounts = session.exec(select(Account)).all()
    sync_status = session.get(SyncStatus, 1)

    total_income_cents = sum(i.received_cents for i in incomes)
    total_spent_cents = sum(p.spent_cents for p in periods)
    net_cents = total_income_cents - total_spent_cents

    prev_year, prev_month = _shift_month(year, month, -1)
    next_year, next_month = _shift_month(year, month, +1)

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "periods": periods,
            "incomes": incomes,
            "total_income_cents": total_income_cents,
            "total_spent_cents": total_spent_cents,
            "net_cents": net_cents,
            "accounts": accounts,
            "format_money": format_money,
            "month_label": date(year, month, 1).strftime("%B %Y"),
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "is_current_month": (year == now.year and month == now.month),
            "sync_status": sync_status,
        },
    )
