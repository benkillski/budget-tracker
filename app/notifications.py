import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.budget_calc import CategorySpend
from app.money import format_money
from app.sync_service import ThresholdCrossing

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)
_env.globals["format_money"] = format_money


@dataclass
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_addr: str
    to_addr: str


def _render_html(template_name: str, context: dict) -> str:
    """Render an email HTML template under app/templates/email/."""
    template = _env.get_template(f"email/{template_name}")
    return template.render(**context)


def _send(config: SMTPConfig, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send an email. If html_body is provided, send multipart (text + HTML).
    Email clients that can render HTML will show that; others fall back to text."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_addr
    message["To"] = config.to_addr
    message.set_content(text_body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(config.host, config.port) as smtp:
        smtp.starttls()
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def send_alert_email(config: SMTPConfig, crossing: ThresholdCrossing) -> None:
    subject = f"Budget alert: {crossing.category_name} at {crossing.threshold_pct}%"
    text_body = (
        f"{crossing.category_name} has reached {crossing.threshold_pct}% of its monthly budget.\n\n"
        f"Spent: {format_money(crossing.spent_cents)}\n"
        f"Limit: {format_money(crossing.limit_cents)}\n"
    )
    html_body = _render_html("alert.html", {"crossing": crossing})
    _send(config, subject, text_body, html_body)


def send_digest_email(config: SMTPConfig, periods: list[CategorySpend]) -> None:
    subject = "Budget digest"
    lines = [
        f"{p.category_name}: {format_money(p.spent_cents)} / {format_money(p.limit_cents)} ({p.pct_used:.0f}%)"
        for p in periods
        if p.limit_cents > 0
    ]
    text_body = "\n".join(lines) if lines else "No budgeted categories yet."
    html_body = _render_html("digest.html", {"periods": periods})
    _send(config, subject, text_body, html_body)
