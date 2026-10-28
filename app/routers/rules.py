from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import Account, Category, Rule, Transaction
from app.rules_engine import apply_rules

router = APIRouter(prefix="/rules")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def list_rules(
    request: Request,
    applied: int | None = None,
    scope: str | None = None,
    session: Session = Depends(get_session),
):
    rules = session.exec(select(Rule).order_by(Rule.priority)).all()
    categories = session.exec(select(Category).order_by(Category.name)).all()
    accounts = session.exec(select(Account).order_by(Account.name)).all()
    return templates.TemplateResponse(
        request,
        "rules.html",
        {
            "rules": rules,
            "categories": categories,
            "accounts": accounts,
            "applied_count": applied,
            "applied_scope": scope,
        },
    )


def _parse_optional_int(raw: str) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.post("")
def create_rule(
    match_type: str = Form(...),
    match_value: str = Form(...),
    category_id: int = Form(...),
    priority: int = Form(0),
    source: str = Form("payee"),
    account_id: str = Form(""),
    session: Session = Depends(get_session),
):
    session.add(
        Rule(
            source=source,
            match_type=match_type,
            match_value=match_value,
            category_id=category_id,
            account_id=_parse_optional_int(account_id),
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


@router.post("/apply-all")
def apply_rules_to_existing(
    scope: str = Form("uncategorized"),
    session: Session = Depends(get_session),
):
    rules = session.exec(select(Rule).order_by(Rule.priority)).all()
    query = select(Transaction)
    if scope != "all":
        scope = "uncategorized"
        query = query.where(Transaction.category_id.is_(None))

    changed = 0
    for txn in session.exec(query).all():
        matched = apply_rules(
            txn.payee,
            rules,
            description=txn.description or "",
            memo=txn.memo or "",
            account_id=txn.account_id,
        )
        if matched is None:
            continue
        if txn.category_id == matched.category_id and txn.rule_applied_id == matched.id:
            continue
        txn.category_id = matched.category_id
        txn.rule_applied_id = matched.id
        session.add(txn)
        changed += 1

    session.commit()
    return RedirectResponse(f"/rules?applied={changed}&scope={scope}", status_code=303)


@router.post("/{rule_id}")
def update_rule(
    rule_id: int,
    match_type: str = Form(...),
    match_value: str = Form(...),
    category_id: int = Form(...),
    priority: int = Form(0),
    source: str = Form("payee"),
    account_id: str = Form(""),
    session: Session = Depends(get_session),
):
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.source = source
    rule.match_type = match_type
    rule.match_value = match_value
    rule.category_id = category_id
    rule.account_id = _parse_optional_int(account_id)
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
