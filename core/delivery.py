"""
Email delivery for the Publish stage. Disabled by default (EMAIL_ENABLED=false);
enable it and set SMTP_* env vars to have each report emailed automatically.
"""
import logging
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core import config

logger = logging.getLogger("agent.delivery")


def send_email_report(title: str, markdown_body: str, pdf_path: str | None):
    if not (config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD and config.EMAIL_TO):
        logger.warning("Email requested but SMTP settings are incomplete; skipping.")
        return

    recipients = [addr.strip() for addr in config.EMAIL_TO.split(",") if addr.strip()]
    msg = MIMEMultipart()
    msg["Subject"] = f"[AI Breakthrough Report] {title}"
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(markdown_body, "plain"))

    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
            part.add_header("Content-Disposition", "attachment",
                             filename=os.path.basename(pdf_path))
            msg.attach(part)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.EMAIL_FROM, recipients, msg.as_string())

    logger.info("Emailed report to %s", recipients)
