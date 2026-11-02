from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.budget_calc import month_bounds
from app.db import get_session
from app.models import Account, Category, Transaction
from app.money import format_money
from app.timeutil import utc_now

router = APIRouter(prefix="/transactions")
templates = Jinja2Templates(directory="app/templates")


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, (index % 12) + 1


def _accounts_by_id(session: Session) -> dict[int, Account]:
    return {a.id: a for a in session.exec(select(Account)).all()}


@router.get("")
def list_transactions(
    request: Request,
    uncategorized_only: bool = False,
    account_id: str = "",
    category_id: str = "",
    year: int | None = None,
    month: int | None = None,
    show_all: bool = False,
    session: Session = Depends(get_session),
):
    try:
        selected_account_id: int | None = int(account_id) if account_id else None
    except ValueError:
        selected_account_id = None
    try:
        selected_category_id: int | None = int(category_id) if category_id else None
    except ValueError:
        selected_category_id = None

    now = utc_now()
    if not show_all:
        if year is None or month is None or not (1 <= month <= 12):
            year, month = now.year, now.month
        start, end = month_bounds(year, month)
        month_label = date(year, month, 1).strftime("%B %Y")
        prev_year, prev_month = _shift_month(year, month, -1)
        next_year, next_month = _shift_month(year, month, +1)
        is_current_month = (year == now.year and month == now.month)
    else:
        start = end = None
        month_label = "All transactions"
        prev_year = prev_month = next_year = next_month = None
        is_current_month = False

    query = select(Transaction).order_by(Transaction.posted_at.desc())
    if not show_all:
        query = query.where(Transaction.posted_at >= start, Transaction.posted_at <= end)
    if uncategorized_only:
        query = query.where(Transaction.category_id.is_(None))
    if selected_account_id is not None:
        query = query.where(Transaction.account_id == selected_account_id)
    if selected_category_id is not None:
        query = query.where(Transaction.category_id == selected_category_id)
    transactions = session.exec(query).all()
    categories = session.exec(select(Category).order_by(Category.name)).all()
    accounts = session.exec(select(Account).order_by(Account.name)).all()
    accounts_by_id = {a.id: a for a in accounts}
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "transactions": transactions,
            "categories": categories,
            "accounts": accounts,
            "accounts_by_id": accounts_by_id,
            "selected_account_id": selected_account_id,
            "selected_category_id": selected_category_id,
            "format_money": format_money,
            "uncategorized_only": uncategorized_only,
            "month_label": month_label,
            "selected_year": year,
            "selected_month": month,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
            "is_current_month": is_current_month,
            "show_all": show_all,
            "transaction_count": len(transactions),
        },
    )


@router.post("/{transaction_id}/category")
def set_category(
    transaction_id: int,
    request: Request,
    category_id: str = Form(""),
    session: Session = Depends(get_session),
):
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404)
    transaction.category_id = int(category_id) if category_id else None
    transaction.rule_applied_id = None
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(
        request,
        "partials/transaction_row.html",
        {
            "transaction": transaction,
            "categories": categories,
            "accounts_by_id": _accounts_by_id(session),
            "format_money": format_money,
        },
    )
