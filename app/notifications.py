"""Email notifications (master): handle events from slaves and send/log emails.

Supports Docker quota events and non-Docker disk quota events. Resolves users via OAuth
and records all email attempts in NotificationEmailLog with basic throttling.
"""

import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app, request

from app.utils import get_logger

logger = get_logger(__name__)


def _my_usage_url() -> str:
    """Return an absolute URL to the 'my usage' page if possible.

    Prefers the current request's url_root; falls back to PUBLIC_WEB_BASE_URL
    config if set; otherwise uses a relative /my-usage path (mainly for
    offline preview generation).
    """
    try:
        root = request.url_root  # e.g. "https://qman.example.com/"
        if root:
            return root.rstrip("/") + "/my-usage"
    except RuntimeError:
        # No request context; fall back to config-based base URL if available.
        base = current_app.config.get("PUBLIC_WEB_BASE_URL")
        if isinstance(base, str) and base:
            return base.rstrip("/") + "/my-usage"
    return "/my-usage"


def send_email(to_email: str, subject: str, body: str, *, html: bool = False) -> bool:
    """Send a single email via SMTP. Returns True on success.

    If html=True, the body is sent as text/html, otherwise text/plain.
    """
    smtp_host = current_app.config.get("SMTP_HOST")
    smtp_port = current_app.config.get("SMTP_PORT", 587)
    smtp_user = current_app.config.get("SMTP_USER")
    smtp_password = current_app.config.get("SMTP_PASSWORD")
    from_addr = current_app.config.get("NOTIFICATION_FROM") or (smtp_user or "qman@localhost")
    if not smtp_host:
        logger.warning("SMTP_HOST not configured; skipping email to %s", to_email)
        return False
    subtype = "html" if html else "plain"
    msg = MIMEText(body, subtype, "utf-8")
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

def _bytes_to_gib(value: int) -> float:
    """Convert bytes to GiB (float)."""
    return value / (1024**3) if value > 0 else 0.0


def _build_docker_quota_email(
    host_id: str, host_user_name: str, event_type: str, detail: dict[str, Any]
) -> tuple[str, str, str, str | None]:
    """Return (subject, HTML body, quota_type, device_name) for Docker quota events (bi-lingual).

    Supports both legacy event names ("quota_exceeded", "container_removed") and
    the newer docker_* names.
    """
    normalized = event_type
    if event_type == "quota_exceeded":
        normalized = "docker_quota_exceeded"
    elif event_type == "container_removed":
        normalized = "docker_container_removed"

    if normalized == "docker_quota_exceeded":
        subject = "[Qman] Docker quota exceeded"
        lead_en = "Your Docker quota on this host has been exceeded."
        lead_zh = "您在此主机上的 Docker 配额已被超出。"
    else:
        subject = "[Qman] Container(s) removed due to Docker quota"
        lead_en = "One or more of your Docker containers were removed due to quota enforcement."
        lead_zh = "由于配额限制，您的部分 Docker 容器已被移除。"

    detail_json = json.dumps(detail, ensure_ascii=False, indent=2)

    my_usage = _my_usage_url()

    body_zh = (
        f"<p>您好 {host_user_name}，</p>"
        f"<p>{lead_zh}</p>"
        f"<p><strong>主机:</strong> {host_id}</p>"
        "<p><strong>详细信息:</strong></p>"
        "<pre style=\"background-color:#f5f5f5;padding:8px;border-radius:4px;white-space:pre-wrap;\">"
        f"{detail_json}"
        "</pre>"
        f"<p style=\"margin-top:12px;\">查看当前配额使用情况："
        f'<a href="{my_usage}">{my_usage}</a>'
        "</p>"
        "<p>Qman</p>"
    )

    body_en = (
        f"<p>Hello {host_user_name},</p>"
        f"<p>{lead_en}</p>"
        f"<p><strong>Host:</strong> {host_id}</p>"
        "<p><strong>Detail:</strong></p>"
        "<pre style=\"background-color:#f5f5f5;padding:8px;border-radius:4px;white-space:pre-wrap;\">"
        f"{detail_json}"
        "</pre>"
        "<p>If this is unexpected, please review your containers and images and remove anything no longer needed, "
        "or contact your administrator for assistance.</p>"
        f"<p style=\"margin-top:12px;\">View your current quota usage: "
        f'<a href="{my_usage}">{my_usage}</a>'
        "</p>"
        "<p>Qman</p>"
    )

    body_html = body_zh + '<hr style="margin:16px 0;"/>' + body_en
    return subject, body_html, "docker", None


def _disk_event_subject_and_lead(event_type: str) -> tuple[str, str]:
    """Return (subject, lead) for a disk quota event type."""
    if event_type == "disk_soft_limit_exceeded":
        return (
            "[Qman] Disk quota soft limit exceeded",
            "Your disk usage has exceeded the soft quota limit.",
        )
    if event_type == "disk_soft_grace_ending":
        return (
            "[Qman] Disk quota grace period ending soon",
            "Your disk usage is still over the soft limit and the grace period will end soon.",
        )
    if event_type == "disk_soft_grace_expired":
        return (
            "[Qman] Disk quota grace period expired",
            "Your disk usage is over the soft limit and the grace period has expired.",
        )
    if event_type == "disk_hard_limit_reached":
        return (
            "[Qman] Disk quota hard limit reached",
            "Your disk usage has reached the hard quota limit; further writes may be blocked.",
        )
    if event_type == "disk_back_to_ok":
        return (
            "[Qman] Disk quota back within limits",
            "Your disk usage is now back within the configured quota limits.",
        )
    return (
        "[Qman] Disk quota notification",
        "There is an update related to your disk quota.",
    )


def _build_disk_quota_event_section(
    host_id: str,
    host_user_name: str,
    event_type: str,
    detail: dict[str, Any],
) -> tuple[str, str, str, str]:
    """Return (subject, quota_type, zh_section_html, en_section_html) for a single disk quota event."""
    device_name = detail.get("device_name") or "unknown"

    block_current = int(detail.get("block_current", 0) or 0)
    block_soft = int(detail.get("block_soft_limit", 0) or 0)
    block_hard = int(detail.get("block_hard_limit", 0) or 0)
    inode_current = int(detail.get("inode_current", 0) or 0)
    inode_soft = int(detail.get("inode_soft_limit", 0) or 0)
    inode_hard = int(detail.get("inode_hard_limit", 0) or 0)

    block_time_limit = detail.get("block_time_limit")
    inode_time_limit = detail.get("inode_time_limit")

    quota_type = _derive_disk_quota_type_from_detail(detail)
    subject, lead = _disk_event_subject_and_lead(event_type)
    # For section heading, drop the "[Qman] " prefix if present, since it's already in the email subject.
    heading = subject[7:] if subject.startswith("[Qman] ") else subject

    now_ts = int(datetime.utcnow().timestamp())

    def _format_ts(ts: Any) -> str | None:
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            return None
        if ts_int <= 0:
            return None
        dt = datetime.utcfromtimestamp(ts_int)
        return dt.isoformat() + "Z"

    def _format_ts_utc_display(ts: Any) -> str | None:
        """Format timestamp as UTC with explicit 'UTC' label for English email."""
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            return None
        if ts_int <= 0:
            return None
        dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S") + " UTC"

    def _format_ts_beijing(ts: Any) -> str | None:
        """Format timestamp in Asia/Shanghai (Beijing time) for Chinese email."""
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            return None
        if ts_int <= 0:
            return None
        utc_dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
        beijing_dt = utc_dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return beijing_dt.strftime("%Y-%m-%d %H:%M:%S")

    block_grace_end = _format_ts(block_time_limit)
    inode_grace_end = _format_ts(inode_time_limit)
    block_grace_end_utc = _format_ts_utc_display(block_time_limit)
    inode_grace_end_utc = _format_ts_utc_display(inode_time_limit)
    block_grace_end_beijing = _format_ts_beijing(block_time_limit)
    inode_grace_end_beijing = _format_ts_beijing(inode_time_limit)

    section_parts: list[str] = []
    section_parts.append(
        f"<h3 style=\"font-size:15px;margin:16px 0 4px;\">{heading} ({device_name})</h3>"
    )
    section_parts.append(
        f"<p>The following describes the current quota state for <code>{device_name}</code>.</p>"
    )
    section_parts.append(f"<p>{lead}</p>")

    section_parts.append("<ul>")

    # Only show block line if at least one block limit is configured.
    block_has_limit = block_soft > 0 or block_hard > 0
    if block_has_limit:
        block_parts: list[str] = [f"Block usage: <strong>{_bytes_to_gib(block_current):.2f} GiB</strong>"]
        limit_bits: list[str] = []
        if block_soft > 0:
            limit_bits.append(f"soft limit: {_bytes_to_gib(block_soft * 1024):.2f} GiB")
        if block_hard > 0:
            limit_bits.append(f"hard limit: {_bytes_to_gib(block_hard * 1024):.2f} GiB")
        if limit_bits:
            block_parts.append(" (" + ", ".join(limit_bits) + ")")
        section_parts.append("<li>" + " ".join(block_parts) + ".</li>")

    # Only show inode line if at least one inode limit is configured.
    inode_has_limit = inode_soft > 0 or inode_hard > 0
    if inode_has_limit:
        inode_parts: list[str] = [f"Inode usage: <strong>{inode_current}</strong>"]
        limit_bits: list[str] = []
        if inode_soft > 0:
            limit_bits.append(f"soft limit: {inode_soft}")
        if inode_hard > 0:
            limit_bits.append(f"hard limit: {inode_hard}")
        if limit_bits:
            inode_parts.append(" (" + ", ".join(limit_bits) + ")")
        section_parts.append("<li>" + " ".join(inode_parts) + ".</li>")

    # Grace period: show remaining time in a human-readable form when applicable.
    # English: show UTC time with explicit "UTC" label.
    grace_items: list[str] = []
    if isinstance(block_time_limit, (int, float, str)):
        try:
            ts_int = int(block_time_limit)
            if ts_int > now_ts and block_grace_end_utc:
                remaining = ts_int - now_ts
                grace_items.append(
                    f"<li>Block grace ends in about {_format_duration(remaining)} "
                    f"(at <strong>{block_grace_end_utc}</strong>).</li>"
                )
        except (TypeError, ValueError):
            pass
    if isinstance(inode_time_limit, (int, float, str)):
        try:
            ts_int = int(inode_time_limit)
            if ts_int > now_ts and inode_grace_end_utc:
                remaining = ts_int - now_ts
                grace_items.append(
                    f"<li>Inode grace ends in about {_format_duration(remaining)} "
                    f"(at <strong>{inode_grace_end_utc}</strong>).</li>"
                )
        except (TypeError, ValueError):
            pass

    if grace_items:
        section_parts.append("<li>Grace period:<ul>")
        section_parts.extend(grace_items)
        section_parts.append("</ul></li>")

    # Close metrics list before starting a new section.
    section_parts.append("</ul>")

    # Recommended actions (generic but useful).
    section_parts.append(
        "<p style=\"margin:8px 0 0 0;\">Recommended actions:</p>"
        "<ul>"
        "<li>Delete files you no longer need on this device.</li>"
        "<li>Move large, non-critical data (e.g. temporary files, caches, old logs) to other storage.</li>"
        "<li>Contact your administrator if you are unsure what can be safely removed.</li>"
        "</ul>"
    )

    en_section_html = "".join(section_parts)

    # Build a Simplified Chinese version of the same section.
    zh_parts: list[str] = []
    zh_heading = _disk_event_zh_heading(event_type, device_name)
    zh_lead = _disk_event_zh_lead(event_type)

    zh_parts.append(
        f"<h3 style=\"font-size:15px;margin:16px 0 4px;\">{zh_heading}</h3>"
    )
    zh_parts.append(
        f"<p>下面是设备 <code>{device_name}</code> 当前的配额状态。</p>"
    )
    zh_parts.append(f"<p>{zh_lead}</p>")

    zh_parts.append("<ul>")

    if block_has_limit:
        zh_block_bits: list[str] = [f"块使用量：<strong>{_bytes_to_gib(block_current):.2f} GiB</strong>"]
        limit_bits_zh: list[str] = []
        if block_soft > 0:
            limit_bits_zh.append(f"软限制：{_bytes_to_gib(block_soft * 1024):.2f} GiB")
        if block_hard > 0:
            limit_bits_zh.append(f"硬限制：{_bytes_to_gib(block_hard * 1024):.2f} GiB")
        if limit_bits_zh:
            zh_block_bits.append("（" + "，".join(limit_bits_zh) + "）")
        zh_parts.append("<li>" + " ".join(zh_block_bits) + "。</li>")

    if inode_has_limit:
        zh_inode_bits: list[str] = [f"Inode 使用量：<strong>{inode_current}</strong>"]
        limit_bits_zh: list[str] = []
        if inode_soft > 0:
            limit_bits_zh.append(f"软限制：{inode_soft}")
        if inode_hard > 0:
            limit_bits_zh.append(f"硬限制：{inode_hard}")
        if limit_bits_zh:
            zh_inode_bits.append("（" + "，".join(limit_bits_zh) + "）")
        zh_parts.append("<li>" + " ".join(zh_inode_bits) + "。</li>")

    # Chinese: show Beijing time (Asia/Shanghai).
    zh_grace_items: list[str] = []
    if isinstance(block_time_limit, (int, float, str)):
        try:
            ts_int = int(block_time_limit)
            if ts_int > now_ts and block_grace_end_beijing:
                remaining = ts_int - now_ts
                zh_grace_items.append(
                    f"<li>块配额宽限期将在大约 {_format_duration(remaining)} 后结束"
                    f"（北京时间 <strong>{block_grace_end_beijing}</strong>）。</li>"
                )
        except (TypeError, ValueError):
            pass
    if isinstance(inode_time_limit, (int, float, str)):
        try:
            ts_int = int(inode_time_limit)
            if ts_int > now_ts and inode_grace_end_beijing:
                remaining = ts_int - now_ts
                zh_grace_items.append(
                    f"<li>Inode 配额宽限期将在大约 {_format_duration(remaining)} 后结束"
                    f"（北京时间 <strong>{inode_grace_end_beijing}</strong>）。</li>"
                )
        except (TypeError, ValueError):
            pass

    if zh_grace_items:
        zh_parts.append("<li>宽限期信息：<ul>")
        zh_parts.extend(zh_grace_items)
        zh_parts.append("</ul></li>")

    zh_parts.append("</ul>")

    zh_parts.append(
        "<p style=\"margin:8px 0 0 0;\">推荐操作：</p>"
        "<ul>"
        "<li>删除不再需要的文件。</li>"
        "<li>将体积较大且不关键的数据（例如临时文件、缓存、旧日志）移动到其他存储位置。</li>"
        "<li>如果不确定哪些数据可以安全删除，请联系管理员。</li>"
        "</ul>"
    )

    zh_section_html = "".join(zh_parts)

    return subject, quota_type, zh_section_html, en_section_html


def _compute_state_key(
    *,
    source: str,
    host_id: str,
    host_user_name: str | None,
    device_name: str | None,
    event_type: str,
) -> str:
    """Compute a normalized state key for throttling.

    The key groups similar states (e.g. per user/host/device/event_type).
    """
    return "|".join(
        [
            source,
            host_id,
            host_user_name or "",
            device_name or "",
            event_type,
        ]
    )


def _create_notification_event(
    db: Any,
    *,
    oauth_user_id: int | None,
    email: str | None,
    host_id: str,
    host_user_name: str,
    device_name: str | None,
    quota_type: str,
    event_type: str,
    detail: dict[str, Any],
    source: str,
) -> Any:
    """Create and persist a NotificationEvent row."""
    from app.models_db import NotificationEvent

    # For disk events, try to derive a more specific quota_type from detail.
    if source == "disk":
        quota_type = _derive_disk_quota_type_from_detail(detail)

    state_key = _compute_state_key(
        source=source,
        host_id=host_id,
        host_user_name=host_user_name,
        device_name=device_name,
        event_type=event_type,
    )

    payload = {"detail": detail}
    ev = NotificationEvent(
        oauth_user_id=oauth_user_id,
        email=email,
        host_id=host_id,
        host_user_name=host_user_name,
        device_name=device_name,
        quota_type=quota_type,
        event_type=event_type,
        payload=json.dumps(payload, ensure_ascii=False),
        state_key=state_key,
        email_log_id=None,
    )
    db.add(ev)
    return ev


def _derive_disk_quota_type_from_detail(detail: dict[str, Any]) -> str:
    """Derive quota_type ('block'|'inode'|'both'|'unknown') from a disk quota detail dict."""
    block_soft = int(detail.get("block_soft_limit", 0) or 0)
    block_hard = int(detail.get("block_hard_limit", 0) or 0)
    inode_soft = int(detail.get("inode_soft_limit", 0) or 0)
    inode_hard = int(detail.get("inode_hard_limit", 0) or 0)

    block_has_limit = block_soft > 0 or block_hard > 0
    inode_has_limit = inode_soft > 0 or inode_hard > 0

    if block_has_limit and inode_has_limit:
        return "both"
    if block_has_limit:
        return "block"
    if inode_has_limit:
        return "inode"
    return "unknown"


def _format_duration(seconds: int) -> str:
    """Return a human-readable duration like '1 day 3 hours'."""
    if seconds <= 0:
        return "0 minutes"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    parts: list[str] = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if not days and minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts:
        parts.append("less than 1 minute")
    return " ".join(parts)


def _disk_event_zh_heading(event_type: str, device_name: str) -> str:
    """Return a Simplified Chinese heading for the event."""
    if event_type == "disk_soft_limit_exceeded":
        base = "磁盘配额软限制已超出"
    elif event_type == "disk_soft_grace_ending":
        base = "磁盘配额宽限期即将结束"
    elif event_type == "disk_soft_grace_expired":
        base = "磁盘配额宽限期已结束"
    elif event_type == "disk_hard_limit_reached":
        base = "磁盘配额硬限制已达到"
    elif event_type == "disk_back_to_ok":
        base = "磁盘配额已恢复正常"
    else:
        base = "磁盘配额通知"
    return f"{base} ({device_name})"


def _disk_event_zh_lead(event_type: str) -> str:
    """Return a Simplified Chinese lead sentence for the event."""
    if event_type == "disk_soft_limit_exceeded":
        return "您的磁盘使用量已超过配置的软限制。"
    if event_type == "disk_soft_grace_ending":
        return "您的磁盘使用量仍高于软限制，并且宽限期即将结束。"
    if event_type == "disk_soft_grace_expired":
        return "您的磁盘使用量已超过软限制，且宽限期已经结束。"
    if event_type == "disk_hard_limit_reached":
        return "您的磁盘使用量已达到硬限制，写入操作很可能已经被阻止。"
    if event_type == "disk_back_to_ok":
        return "您的磁盘使用量已回到配置的配额限制之内。"
    return "您的磁盘配额状态发生了变化。"


def _maybe_send_email_for_events(
    db: Any,
    *,
    oauth_user_id: int | None,
    email: str | None,
    host_id: str,
    subject: str,
    body: str,
    events: list[Any],
    html: bool,
) -> None:
    """Insert a NotificationEmailLog row for a batch of events and send email if not throttled.

    Throttling is based on the first event's state_key within the configured dedupe window.
    All events passed in are assumed to be eligible for emailing (any per-event throttling
    should have been applied before calling this function).
    """
    from app.models_db import NotificationEmailLog, NotificationEvent

    if not events:
        return

    primary: NotificationEvent = events[0]
    dedupe_key = primary.state_key or ""

    now = datetime.utcnow()
    window_seconds = int(current_app.config.get("QUOTA_NOTIFICATION_DEDUPE_WINDOW_SECONDS", 86400) or 86400)
    cutoff = now - timedelta(seconds=window_seconds)

    existing = (
        db.query(NotificationEmailLog)
        .filter(
            NotificationEmailLog.dedupe_key == dedupe_key,
            NotificationEmailLog.created_at >= cutoff,
            NotificationEmailLog.send_status.in_(["success", "skipped"]),
        )
        .first()
    )

    log_row = NotificationEmailLog(
        oauth_user_id=oauth_user_id,
        email=email,
        host_id=host_id,
        host_user_name=primary.host_user_name,
        device_name=primary.device_name,
        quota_type=primary.quota_type,
        event_type=primary.event_type,
        subject=subject,
        body_preview=body[:2000],
        send_status="pending",
        error_message=None,
        dedupe_key=dedupe_key,
        last_state=None,
        batch_id=None,
        body_html=body if html else None,
    )

    if existing is not None:
        log_row.send_status = "skipped"
        log_row.error_message = "throttled (duplicate state within dedupe window)"
        db.add(log_row)
        db.flush()
        for ev in events:
            ev.email_log_id = log_row.id
        return

    if not email:
        log_row.send_status = "skipped"
        log_row.error_message = "no email address for user"
        db.add(log_row)
        db.flush()
        for ev in events:
            ev.email_log_id = log_row.id
        return

    ok = send_email(email, subject, body, html=html)
    if ok:
        log_row.send_status = "success"
    else:
        log_row.send_status = "failed"
        log_row.error_message = "send_email returned False"
    db.add(log_row)
    db.flush()
    for ev in events:
        ev.email_log_id = log_row.id


def process_slave_events(host_id: str, events: list[dict[str, Any]]) -> None:
    """Process events from slave: resolve host_user_name -> email, send/log notifications."""
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        # First pass: create NotificationEvent rows and collect disk events for batching.
        disk_events_by_user: dict[tuple[int, str | None], list[Any]] = {}

        for ev in events:
            host_user_name = ev.get("host_user_name")
            event_type = ev.get("event_type")
            detail = ev.get("detail") or {}
            if not host_user_name or not event_type:
                continue

            oauth_uid = resolve_oauth_user_id(host_id, host_user_name)
            if oauth_uid is None:
                logger.info(
                    "Slave event skipped (no OAuth mapping): host_id=%s host_user_name=%s event_type=%s",
                    host_id,
                    host_user_name,
                    event_type,
                )
                continue
            email = get_email_for_oauth_user(oauth_uid)

            if event_type in ("quota_exceeded", "docker_quota_exceeded", "container_removed", "docker_container_removed"):
                # Docker events: one email per event, still logged as individual events.
                subject, body, quota_type, device_name = _build_docker_quota_email(
                    host_id, host_user_name, event_type, detail
                )
                ev_row = _create_notification_event(
                    db,
                    oauth_user_id=oauth_uid,
                    email=email,
                    host_id=host_id,
                    host_user_name=host_user_name,
                    device_name=device_name,
                    quota_type=quota_type,
                    event_type=event_type,
                    detail=detail,
                    source="docker",
                )
                _maybe_send_email_for_events(
                    db,
                    oauth_user_id=oauth_uid,
                    email=email,
                    host_id=host_id,
                    subject=subject,
                    body=body,
                    events=[ev_row],
                    html=True,
                )
            elif event_type in (
                "disk_soft_limit_exceeded",
                "disk_soft_grace_ending",
                "disk_soft_grace_expired",
                "disk_hard_limit_reached",
                "disk_back_to_ok",
            ):
                # Collect non-Docker disk quota events for batching per (user, email).
                key = (oauth_uid, email)
                if key not in disk_events_by_user:
                    disk_events_by_user[key] = []
                ev_row = _create_notification_event(
                    db,
                    oauth_user_id=oauth_uid,
                    email=email,
                    host_id=host_id,
                    host_user_name=host_user_name,
                    device_name=detail.get("device_name"),
                    quota_type="unknown",
                    event_type=event_type,
                    detail=detail,
                    source="disk",
                )
                disk_events_by_user[key].append(ev_row)
            else:
                logger.debug(
                    "Unhandled slave event type %s for host_id=%s user=%s detail=%s",
                    event_type,
                    host_id,
                    host_user_name,
                    detail,
                )

        # Second pass: per-user batching for disk quota notifications.
        for (oauth_uid, email), user_events in disk_events_by_user.items():
            if not user_events:
                continue

            sendable_events: list[Any] = []
            host_user_name_example: str | None = None

            # Pre-fetch recent dedupe keys for this user/email to avoid per-event queries.
            from app.models_db import NotificationEmailLog  # local import to avoid cycles

            now_outer = datetime.utcnow()
            window_seconds_outer = int(
                current_app.config.get("QUOTA_NOTIFICATION_DEDUPE_WINDOW_SECONDS", 86400) or 86400
            )
            cutoff_outer = now_outer - timedelta(seconds=window_seconds_outer)

            recent_rows = (
                db.query(NotificationEmailLog.dedupe_key)
                .filter(
                    NotificationEmailLog.email == email,
                    NotificationEmailLog.created_at >= cutoff_outer,
                    NotificationEmailLog.send_status.in_(["success", "skipped"]),
                )
                .all()
            )
            recent_keys: set[str] = {r.dedupe_key for r in recent_rows if r.dedupe_key}

            for ev_row in user_events:
                host_user_name = ev_row.host_user_name or ""
                event_type = ev_row.event_type
                # payload is JSON with {"detail": {...}}
                try:
                    payload_obj = json.loads(ev_row.payload or "{}")
                    detail = payload_obj.get("detail") or {}
                except json.JSONDecodeError:
                    detail = {}
                host_user_name_example = host_user_name_example or host_user_name

                # Per-event throttling based on state_key to avoid spamming for identical states.
                state_key = ev_row.state_key or ""
                if state_key and state_key in recent_keys:
                    # Event is considered already notified; keep it logged but do not include in the email.
                    continue

                # This event should be included in the batched email.
                sendable_events.append(ev_row)

            if not sendable_events:
                # Nothing new to send for this user in this batch.
                continue

            # Build a single bi-lingual HTML email summarizing all events for this user.
            host_user_name_for_email = host_user_name_example or "user"
            unique_event_types = {ev.event_type for ev in sendable_events}
            if len(unique_event_types) == 1:
                (single_type,) = tuple(unique_event_types)
                subject, _ = _disk_event_subject_and_lead(single_type)
            else:
                subject = "[Qman] Disk quota notifications"

            zh_sections: list[str] = []
            en_sections: list[str] = []
            for ev_row in sendable_events:
                host_user_name = ev_row.host_user_name or ""
                try:
                    payload_obj = json.loads(ev_row.payload or "{}")
                    detail = payload_obj.get("detail") or {}
                except json.JSONDecodeError:
                    detail = {}
                _, _, zh_section, en_section = _build_disk_quota_event_section(
                    host_id,
                    host_user_name,
                    ev_row.event_type,
                    detail,
                )
                zh_sections.append(zh_section)
                en_sections.append(en_section)

            my_usage = _my_usage_url()

            body_zh = (
                f"<p>您好 {host_user_name_for_email}，</p>"
                f"<p>这封邮件与您在主机 <code>{host_id}</code> 上的磁盘配额有关。</p>"
                + "".join(zh_sections)
                + f"<p style=\"margin-top:12px;\">查看当前配额使用情况："
                f'<a href="{my_usage}">{my_usage}</a>'
                "</p>"
                "<p>Qman</p>"
            )

            body_en = (
                f"<p>Hello {host_user_name_for_email},</p>"
                f"<p>This email is about your disk quota on host <code>{host_id}</code>.</p>"
                + "".join(en_sections)
                + f"<p style=\"margin-top:12px;\">View your current quota usage: "
                f'<a href="{my_usage}">{my_usage}</a>'
                "</p>"
                "<p>Qman</p>"
            )

            body_html = body_zh + '<hr style="margin:16px 0;"/>' + body_en

            _maybe_send_email_for_events(
                db,
                oauth_user_id=oauth_uid,
                email=email,
                host_id=host_id,
                subject=subject,
                body=body_html,
                events=sendable_events,
                html=True,
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
