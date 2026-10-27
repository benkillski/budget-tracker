from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, Rule, Transaction

router = APIRouter(prefix="/rules")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def list_rules(request: Request, session: Session = Depends(get_session)):
    rules = session.exec(select(Rule).order_by(Rule.priority)).all()
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(request, "rules.html", {"rules": rules, "categories": categories})


@router.post("")
def create_rule(
    match_type: str = Form(...),
    match_value: str = Form(...),
    category_id: int = Form(...),
    priority: int = Form(0),
    source: str = Form("payee"),
    session: Session = Depends(get_session),
):
    session.add(
        Rule(
            source=source,
            match_type=match_type,
            match_value=match_value,
            category_id=category_id,
            priority=priority,
        )
    )
    session.commit()
    return RedirectResponse("/rules", status_code=303)


@router.post("/from-transaction/{transaction_id}")
def create_rule_from_transaction(
    transaction_id: int,
    category_id: int = Form(...),
    session: Session = Depends(get_session),
):
    transaction = session.get(Transaction, transaction_id)
    if transaction is not None:
        session.add(Rule(match_type="contains", match_value=transaction.payee, category_id=category_id, priority=0))
        transaction.category_id = category_id
        session.add(transaction)
        session.commit()
    return RedirectResponse("/transactions", status_code=303)


@router.post("/{rule_id}")
def update_rule(
    rule_id: int,
    match_type: str = Form(...),
    match_value: str = Form(...),
    category_id: int = Form(...),
    priority: int = Form(0),
    source: str = Form("payee"),
    session: Session = Depends(get_session),
):
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.source = source
    rule.match_type = match_type
    rule.match_value = match_value
    rule.category_id = category_id
    rule.priority = priority
    session.add(rule)
    session.commit()
    return RedirectResponse("/rules", status_code=303)


@router.post("/{rule_id}/delete")
def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    for txn in session.exec(select(Transaction).where(Transaction.rule_applied_id == rule_id)).all():
        txn.rule_applied_id = None
        session.add(txn)
    session.delete(rule)
    session.commit()
    return RedirectResponse("/rules", status_code=303)
