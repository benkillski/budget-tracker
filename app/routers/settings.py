from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings as app_settings
from app.db import engine, get_session
from app.jobs import daily_sync_job
from app.models import AlertLog, Category, Rule, Transaction
from app.money import to_cents

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def show_settings(
    request: Request,
    sync: str | None = None,
    msg: str | None = None,
    session: Session = Depends(get_session),
):
    categories = session.exec(select(Category).order_by(Category.name)).all()
    # Only top-level categories (parent_id IS NULL) are valid parents, so the
    # hierarchy stays one level deep.
    potential_parents = [c for c in categories if c.parent_id is None]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "categories": categories,
            "potential_parents": potential_parents,
            "simplefin_configured": bool(app_settings.simplefin_access_url),
            "warning_threshold_pct": app_settings.warning_threshold_pct,
            "alert_threshold_pct": app_settings.alert_threshold_pct,
            "digest_frequency": app_settings.digest_frequency,
            "sync_result": sync,
            "sync_message": msg,
        },
    )


@router.post("/sync-now")
def sync_now():
    if not app_settings.simplefin_access_url:
        return RedirectResponse(
            "/settings?sync=error&msg=" + quote("SimpleFIN access URL is not configured."),
            status_code=303,
        )
    try:
        daily_sync_job(app_settings, engine)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            "/settings?sync=error&msg=" + quote(str(exc)[:200]),
            status_code=303,
        )
    return RedirectResponse("/settings?sync=ok", status_code=303)


def _parse_parent_id(session: Session, raw: str, self_id: int | None) -> int | None:
    """Return a valid parent_id or None. Enforces: not self; parent exists;
    parent is itself top-level (one-level hierarchy); not a child of self."""
    if not raw:
        return None
    try:
        candidate = int(raw)
    except ValueError:
        return None
    if self_id is not None and candidate == self_id:
        raise HTTPException(status_code=400, detail="A category can't be its own parent.")
    parent = session.get(Category, candidate)
    if parent is None:
        raise HTTPException(status_code=400, detail="Parent category not found.")
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Only one level of hierarchy is supported — the chosen parent is itself a child.",
        )
    # Prevent flipping a parent into a grandchild of its own child.
    if self_id is not None:
        has_children = session.exec(
            select(Category).where(Category.parent_id == self_id)
        ).first() is not None
        if has_children:
            raise HTTPException(
                status_code=400,
                detail="Can't give this category a parent — it already has children of its own.",
            )
    return candidate


@router.post("/categories")
def create_category(
    name: str = Form(...),
    monthly_limit: str = Form("0"),
    is_income: bool = Form(False),
    parent_id: str = Form(""),
    session: Session = Depends(get_session),
):
    parent = _parse_parent_id(session, parent_id, self_id=None)
    session.add(
        Category(
            name=name,
            monthly_limit_cents=to_cents(Decimal(monthly_limit)),
            is_income=is_income,
            parent_id=parent,
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
    parent_id: str = Form(""),
    session: Session = Depends(get_session),
):
    category = session.get(Category, category_id)
    if category is not None:
        category.name = name.strip()
        category.monthly_limit_cents = to_cents(Decimal(monthly_limit))
        category.is_income = is_income
        category.parent_id = _parse_parent_id(session, parent_id, self_id=category_id)
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
