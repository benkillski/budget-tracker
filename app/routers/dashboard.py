from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.budget_calc import compute_budget_period
from app.db import get_session
from app.models import Account, SyncStatus
from app.money import format_money
from app.timeutil import utc_now

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def home(request: Request, session: Session = Depends(get_session)):
    now = utc_now()
    periods = compute_budget_period(session, now.year, now.month)
    accounts = session.exec(select(Account)).all()
    sync_status = session.get(SyncStatus, 1)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "periods": periods,
            "accounts": accounts,
            "format_money": format_money,
            "month_label": now.strftime("%B %Y"),
            "sync_status": sync_status,
        },
    )
