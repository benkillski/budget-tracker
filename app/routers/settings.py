from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings as app_settings
from app.db import get_session
from app.models import AlertLog, Category, Rule, Transaction
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
    is_income: bool = Form(False),
    session: Session = Depends(get_session),
):
    session.add(
        Category(
            name=name,
            monthly_limit_cents=to_cents(Decimal(monthly_limit)),
            is_income=is_income,
        )
    )
    session.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/categories/{category_id}")
def update_category(
    category_id: int,
    name: str = Form(...),
    monthly_limit: str = Form(...),
    is_income: bool = Form(False),
    session: Session = Depends(get_session),
):
    category = session.get(Category, category_id)
    if category is not None:
        category.name = name.strip()
        category.monthly_limit_cents = to_cents(Decimal(monthly_limit))
        category.is_income = is_income
        session.add(category)
        session.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/categories/{category_id}/delete")
def delete_category(category_id: int, session: Session = Depends(get_session)):
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    rule_count = len(session.exec(select(Rule).where(Rule.category_id == category_id)).all())
    if rule_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Delete the {rule_count} rule(s) pointing at this category first.",
        )

    for txn in session.exec(select(Transaction).where(Transaction.category_id == category_id)).all():
        txn.category_id = None
        session.add(txn)
    for alert in session.exec(select(AlertLog).where(AlertLog.category_id == category_id)).all():
        session.delete(alert)
    session.delete(category)
    session.commit()
    return RedirectResponse("/settings", status_code=303)
