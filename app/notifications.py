import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.budget_calc import CategorySpend
from app.money import format_money
from app.sync_service import ThresholdCrossing


@dataclass
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_addr: str
    to_addr: str


def _send(config: SMTPConfig, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_addr
    message["To"] = config.to_addr
    message.set_content(body)

    with smtplib.SMTP(config.host, config.port) as smtp:
        smtp.starttls()
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def send_alert_email(config: SMTPConfig, crossing: ThresholdCrossing) -> None:
    subject = f"Budget alert: {crossing.category_name} at {crossing.threshold_pct}%"
    body = (
        f"{crossing.category_name} has reached {crossing.threshold_pct}% of its monthly budget.\n\n"
        f"Spent: {format_money(crossing.spent_cents)}\n"
        f"Limit: {format_money(crossing.limit_cents)}\n"
    )
    _send(config, subject, body)


def send_digest_email(config: SMTPConfig, periods: list[CategorySpend]) -> None:
    subject = "Budget digest"
    lines = [
        f"{p.category_name}: {format_money(p.spent_cents)} / {format_money(p.limit_cents)} ({p.pct_used:.0f}%)"
        for p in periods
        if p.limit_cents > 0
    ]
    body = "\n".join(lines) if lines else "No budgeted categories yet."
    _send(config, subject, body)
