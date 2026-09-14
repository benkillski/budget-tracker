from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.csv_import import CSVImportError, import_csv_transactions, parse_csv
from app.db import get_session
from app.models import Account

router = APIRouter(prefix="/import")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def show_import_form(request: Request, session: Session = Depends(get_session)):
    accounts = session.exec(select(Account)).all()
    return templates.TemplateResponse(request, "import.html", {"accounts": accounts, "result": None, "error": None})


@router.post("")
def import_csv(
    request: Request,
    account_id: int = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    accounts = session.exec(select(Account)).all()
    try:
        rows = parse_csv(file.file.read())
        inserted = import_csv_transactions(session, account_id, rows)
        return templates.TemplateResponse(request, "import.html", {"accounts": accounts, "result": inserted, "error": None})
    except CSVImportError as exc:
        return templates.TemplateResponse(request, "import.html", {"accounts": accounts, "result": None, "error": str(exc)})
