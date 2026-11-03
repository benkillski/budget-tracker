from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.budget_calc import previous_month
from app.config import settings as app_settings
from app.db import engine, get_session
from app.jobs import build_month_end_summary, daily_sync_job, digest_job
from app.models import AlertLog, Category, Rule, Transaction
from app.money import to_cents
from app.notifications import send_month_end_summary_email
from app.timeutil import utc_now

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def show_settings(
    request: Request,
    sync: str | None = None,
    msg: str | None = None,
    test_digest: str | None = None,
    test_digest_msg: str | None = None,
    test_recap: str | None = None,
    test_recap_msg: str | None = None,
    session: Session = Depends(get_session),
):
    categories = session.exec(select(Category).order_by(Category.name)).all()
    # Only top-level categories (parent_id IS NULL) are valid parents, so the
    # hierarchy stays one level deep.
    potential_parents = [c for c in categories if c.parent_id is None]
    smtp_configured = bool(app_settings.smtp_host and app_settings.smtp_to)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "categories": categories,
            "potential_parents": potential_parents,
            "simplefin_configured": bool(app_settings.simplefin_access_url),
            "smtp_configured": smtp_configured,
            "smtp_to": app_settings.smtp_to,
            "warning_threshold_pct": app_settings.warning_threshold_pct,
            "alert_threshold_pct": app_settings.alert_threshold_pct,
            "digest_frequency": app_settings.digest_frequency,
            "sync_result": sync,
            "sync_message": msg,
            "test_digest_result": test_digest,
            "test_digest_message": test_digest_msg,
            "test_recap_result": test_recap,
            "test_recap_message": test_recap_msg,
            "month_end_summary_day": app_settings.month_end_summary_day,
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


@router.post("/send-test-digest")
def send_test_digest():
    if not app_settings.smtp_host or not app_settings.smtp_to:
        return RedirectResponse(
            "/settings?test_digest=error&msg=" + quote("SMTP is not configured."),
            status_code=303,
        )
    try:
        digest_job(app_settings, engine)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            "/settings?test_digest=error&msg=" + quote(str(exc)[:200]),
            status_code=303,
        )
    return RedirectResponse("/settings?test_digest=ok", status_code=303)


@router.post("/send-test-month-end-summary")
def send_test_month_end_summary(session: Session = Depends(get_session)):
    """Build the previous month's summary with real data and send it right
    now, bypassing the dedupe log so the preview can run any day."""
    if not app_settings.smtp_host or not app_settings.smtp_to:
        return RedirectResponse(
            "/settings?test_recap=error&test_recap_msg=" + quote("SMTP is not configured."),
            status_code=303,
        )
    try:
        now = utc_now()
        year, month = previous_month(now.year, now.month)
        summary = build_month_end_summary(session, year, month)
        from app.jobs import _smtp_config
        send_month_end_summary_email(_smtp_config(app_settings), summary, test=True)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(
            "/settings?test_recap=error&test_recap_msg=" + quote(str(exc)[:200]),
            status_code=303,
        )
    return RedirectResponse("/settings?test_recap=ok", status_code=303)


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
    is_fixed: bool = Form(False),
    is_tracked_only: bool = Form(False),
    parent_id: str = Form(""),
    session: Session = Depends(get_session),
):
    parent = _parse_parent_id(session, parent_id, self_id=None)
    session.add(
        Category(
            name=name,
            monthly_limit_cents=to_cents(Decimal(monthly_limit)),
            is_income=is_income,
            is_fixed=is_fixed,
            is_tracked_only=is_tracked_only,
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
    is_fixed: bool = Form(False),
    is_tracked_only: bool = Form(False),
    parent_id: str = Form(""),
    session: Session = Depends(get_session),
):
    category = session.get(Category, category_id)
    if category is not None:
        category.name = name.strip()
        category.monthly_limit_cents = to_cents(Decimal(monthly_limit))
        category.is_income = is_income
        category.is_fixed = is_fixed
        category.is_tracked_only = is_tracked_only
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
