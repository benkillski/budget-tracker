from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import Account, Category, Transaction
from app.money import format_money

router = APIRouter(prefix="/transactions")
templates = Jinja2Templates(directory="app/templates")


def _accounts_by_id(session: Session) -> dict[int, Account]:
    return {a.id: a for a in session.exec(select(Account)).all()}


@router.get("")
def list_transactions(
    request: Request,
    uncategorized_only: bool = False,
    account_id: str = "",
    session: Session = Depends(get_session),
):
    try:
        selected_account_id: int | None = int(account_id) if account_id else None
    except ValueError:
        selected_account_id = None

    query = select(Transaction).order_by(Transaction.posted_at.desc())
    if uncategorized_only:
        query = query.where(Transaction.category_id.is_(None))
    if selected_account_id is not None:
        query = query.where(Transaction.account_id == selected_account_id)
    transactions = session.exec(query).all()
    categories = session.exec(select(Category)).all()
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
            "format_money": format_money,
            "uncategorized_only": uncategorized_only,
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
