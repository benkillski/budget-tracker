from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings as app_settings
from app.db import get_session
from app.models import Category
from app.money import to_cents

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def show_settings(request: Request, session: Session = Depends(get_session)):
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "categories": categories,
            "simplefin_configured": bool(app_settings.simplefin_access_url),
            "warning_threshold_pct": app_settings.warning_threshold_pct,
            "alert_threshold_pct": app_settings.alert_threshold_pct,
            "digest_frequency": app_settings.digest_frequency,
        },
    )


@router.post("/categories")
def create_category(
    name: str = Form(...),
    monthly_limit: str = Form("0"),
    session: Session = Depends(get_session),
):
    session.add(Category(name=name, monthly_limit_cents=to_cents(Decimal(monthly_limit))))
    session.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/categories/{category_id}")
def update_category_limit(
    category_id: int,
    monthly_limit: str = Form(...),
    session: Session = Depends(get_session),
):
    category = session.get(Category, category_id)
    if category is not None:
        category.monthly_limit_cents = to_cents(Decimal(monthly_limit))
        session.add(category)
        session.commit()
    return RedirectResponse("/settings", status_code=303)
