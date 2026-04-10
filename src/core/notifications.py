# -*- coding: utf-8 -*-
import logging
import emails
from emails.template import JinjaTemplate
from typing import Dict, Any

from src.core.config import settings

logger = logging.getLogger(__name__)

async def send_email(
    email_to: str,
    subject_template: str = "",
    html_template: str = "",
    environment: Dict[str, Any] = {},
) -> None:
    """
    Sends an email using the configured SMTP settings.
    """
    if not all([settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USER, settings.SMTP_PASSWORD]):
        logger.error("SMTP settings are not fully configured. Cannot send email.")
        return

    message = emails.Message(
        subject=JinjaTemplate(subject_template),
        html=JinjaTemplate(html_template),
        mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
    )

    smtp_options = {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER,
        "password": settings.SMTP_PASSWORD,
    }
    if settings.SMTP_TLS:
        smtp_options["tls"] = True

    try:
        response = message.send(to=email_to, render=environment, smtp=smtp_options)
        logger.info(f"Email sent to {email_to}, response: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending email to {email_to}: {e}", exc_info=True)

async def send_low_balance_notification(email_to: str, balance: float):
    """
    Sends a low balance notification email.
    """
    project_name = settings.SITE_NAME
    subject = f"Alerta de Saldo Baixo - {project_name}"
    with open(settings.EMAIL_TEMPLATES_DIR / "low_balance.html") as f:
        html_template = f.read()
    
    await send_email(
        email_to=email_to,
        subject_template=subject,
        html_template=html_template,
        environment={
            "project_name": project_name,
            "balance": f"{balance:.2f}",
            "recharge_url": f"{settings.SITE_URL}/#/wallet",
        },
    )
