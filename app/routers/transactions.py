from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, Transaction
from app.money import format_money

router = APIRouter(prefix="/transactions")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def list_transactions(
    request: Request,
    uncategorized_only: bool = False,
    session: Session = Depends(get_session),
):
    query = select(Transaction).order_by(Transaction.posted_at.desc())
    if uncategorized_only:
        query = query.where(Transaction.category_id.is_(None))
    transactions = session.exec(query).all()
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "transactions": transactions,
            "categories": categories,
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
    transaction.category_id = int(category_id) if category_id else None
    transaction.rule_applied_id = None
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(
        request,
        "partials/transaction_row.html",
        {"transaction": transaction, "categories": categories, "format_money": format_money},
    )
