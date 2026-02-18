"""Email notifications (master): quota exceeded, container removed. Resolve email via OAuth."""

import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any

from flask import current_app

from app.utils import get_logger

logger = get_logger(__name__)


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send a single email via SMTP. Returns True on success."""
    smtp_host = current_app.config.get("SMTP_HOST")
    smtp_port = current_app.config.get("SMTP_PORT", 587)
    smtp_user = current_app.config.get("SMTP_USER")
    smtp_password = current_app.config.get("SMTP_PASSWORD")
    from_addr = current_app.config.get("NOTIFICATION_FROM") or (smtp_user or "qman@localhost")
    if not smtp_host:
        logger.warning("SMTP_HOST not configured; skipping email to %s", to_email)
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Qman Quota", from_addr))
    msg["To"] = to_email
    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                if smtp_port == 587:
                    server.starttls()
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, [to_email], msg.as_string())
        logger.info("Notification email sent to %s: %s", to_email, subject)
        return True
    except Exception as e:
        logger.warning("Failed to send email to %s: %s", to_email, e)
        return False


def resolve_oauth_user_id(host_id: str, host_user_name: str) -> int | None:
    """Resolve (host_id, host_user_name) to oauth_user_id via OAuthHostUserMapping."""
    from app.db import SessionLocal
    from app.models_db import OAuthHostUserMapping
    db = SessionLocal()
    try:
        row = (
            db.query(OAuthHostUserMapping)
            .filter(
                OAuthHostUserMapping.host_id == host_id,
                OAuthHostUserMapping.host_user_name == host_user_name,
            )
            .first()
        )
        return row.oauth_user_id if row else None
    finally:
        db.close()


def get_email_for_oauth_user(oauth_user_id: int) -> str | None:
    """Get email for oauth_user_id via OAuth server. Uses NOTIFICATION_OAUTH_ACCESS_TOKEN if set."""
    from auth_connect import oauth
    token = current_app.config.get("NOTIFICATION_OAUTH_ACCESS_TOKEN")
    if token:
        try:
            user = oauth.get_user_by_id_with_token(oauth_user_id, token)
            if user and getattr(user, "email", None):
                return user.email
        except Exception as e:
            logger.warning("Could not resolve email for oauth_user_id=%s: %s", oauth_user_id, e)
        return None
    try:
        user = oauth.get_user_by_id(oauth_user_id)
        if user and getattr(user, "email", None):
            return user.email
    except Exception as e:
        logger.warning("Could not resolve email for oauth_user_id=%s: %s", oauth_user_id, e)
    return None


def process_slave_events(host_id: str, events: list[dict[str, Any]]) -> None:
    """Process events from slave: resolve host_user_name -> email, send notifications."""
    for ev in events:
        host_user_name = ev.get("host_user_name")
        event_type = ev.get("event_type")
        detail = ev.get("detail") or {}
        if not host_user_name:
            continue
        oauth_uid = resolve_oauth_user_id(host_id, host_user_name)
        if oauth_uid is None:
            logger.info(
                "Slave event skipped (no OAuth mapping): host_id=%s host_user_name=%s event_type=%s",
                host_id, host_user_name, event_type,
            )
            continue
        email = get_email_for_oauth_user(oauth_uid)
        if not email:
            logger.debug("No email for oauth_user_id=%s; skip notification", oauth_uid)
            continue
        if event_type == "quota_exceeded":
            subject = "[Qman] Docker quota exceeded"
            body = (
                f"Your Docker quota on host {host_id} has been exceeded.\n"
                f"User: {host_user_name}\n"
                f"Detail: {detail}\n"
                "Some containers may be stopped and removed to bring usage under the limit.\n"
            )
            send_email(email, subject, body)
        elif event_type == "container_removed":
            subject = "[Qman] Container(s) removed due to quota"
            body = (
                f"One or more of your Docker containers on host {host_id} were removed due to quota enforcement.\n"
                f"User: {host_user_name}\n"
                f"Detail: {detail}\n"
            )
            send_email(email, subject, body)
