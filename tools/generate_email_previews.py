"""Generate sample HTML files for notification email templates.

This script renders example emails for:
- Docker quota exceeded
- Docker container removed
- Each non-Docker disk quota event type

Output HTML files are written into ./tmp-email-previews.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.notifications import _build_docker_quota_email, _build_disk_quota_event_section


OUTPUT_DIR = Path("tmp-email-previews")


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _sample_docker_detail_quota_exceeded() -> dict[str, object]:
    return {
        "uid": 1001,
        "block_current": 50 * 1024 * 1024 * 1024,  # 50 GiB
        "block_hard_limit": 40 * 1024 * 1024,  # 40 GiB in 1K blocks
    }


def _sample_docker_detail_container_removed() -> dict[str, object]:
    return {
        "container_id": "abc123def456",
        "size_bytes": 5 * 1024 * 1024 * 1024,  # 5 GiB
        "new_usage": 30 * 1024 * 1024 * 1024,  # 30 GiB
        "removed_ids": ["abc123def456", "deadbeef0001"],
    }


def _sample_disk_detail_base() -> dict[str, object]:
    # Example detail: both block and inode limits configured, with grace periods ~6 hours from "now".
    now_ts = int(Path("/").stat().st_mtime)  # cheap stand-in; actual value doesn't matter much for previews
    return {
        "uid": 1001,
        "device_name": "/dev/sda1",
        "block_current": 80 * 1024 * 1024 * 1024,  # 80 GiB
        "block_soft_limit": 70 * 1024 * 1024,  # 70 GiB in 1K blocks
        "block_hard_limit": 90 * 1024 * 1024,  # 90 GiB in 1K blocks
        "inode_current": 500_000,
        "inode_soft_limit": 600_000,
        "inode_hard_limit": 800_000,
        "block_time_limit": now_ts + 6 * 3600,
        "inode_time_limit": now_ts + 6 * 3600,
    }


def _render_disk_batch_email(
    host_id: str,
    host_user_name_for_email: str,
    rendered_rows: list[dict[str, object]],
) -> tuple[str, str]:
    """Render the same HTML batch email body as process_slave_events."""
    subject = f"[Qman] Disk quota notifications ({len(rendered_rows)} item(s))"

    zh_sections: list[str] = []
    en_sections: list[str] = []
    for row in rendered_rows:
        d = row["detail"]
        subject, _quota_type, zh_section, en_section = _build_disk_quota_event_section(
            host_id,
            row["host_user_name"],
            row["event_type"],
            d,
        )
        zh_sections.append(zh_section)
        en_sections.append(en_section)

    body_zh = (
        f"<p>你好 {host_user_name_for_email}，</p>"
        f"<p>这封邮件与主机 <code>{host_id}</code> 上的磁盘配额有关。</p>"
        + "".join(zh_sections)
        + "<p style=\"margin-top:12px;\">查看当前配额使用情况："
        '<a href="/my-usage">/my-usage</a>'
        "</p>"
        "<p>Qman</p>"
    )

    body_en = (
        f"<p>Hello {host_user_name_for_email},</p>"
        f"<p>This email is about disk quota on host <code>{host_id}</code>.</p>"
        + "".join(en_sections)
        + "<p style=\"margin-top:12px;\">View your current quota usage: "
        '<a href="/my-usage">/my-usage</a>'
        "</p>"
        "<p>Qman</p>"
    )

    body_html = body_zh + '<hr style="margin:16px 0;"/>' + body_en

    return subject, body_html


def generate_docker_previews() -> None:
    host_id = "host-1"
    user = "alice"

    # Docker quota exceeded
    subject, body_html, _, _ = _build_docker_quota_email(
        host_id,
        user,
        "docker_quota_exceeded",
        _sample_docker_detail_quota_exceeded(),
    )
    (OUTPUT_DIR / "docker_quota_exceeded.html").write_text(
        f"<!doctype html><html><head><meta charset='utf-8'><title>{subject}</title></head><body>{body_html}</body></html>",
        encoding="utf-8",
    )

    # Docker container removed
    subject, body_html, _, _ = _build_docker_quota_email(
        host_id,
        user,
        "docker_container_removed",
        _sample_docker_detail_container_removed(),
    )
    (OUTPUT_DIR / "docker_container_removed.html").write_text(
        f"<!doctype html><html><head><meta charset='utf-8'><title>{subject}</title></head><body>{body_html}</body></html>",
        encoding="utf-8",
    )


def generate_disk_previews() -> None:
    host_id = "host-1"
    user = "alice"
    base_detail = _sample_disk_detail_base()

    disk_event_types = [
        "disk_soft_limit_exceeded",
        "disk_soft_grace_ending",
        "disk_soft_grace_expired",
        "disk_hard_limit_reached",
        "disk_back_to_ok",
    ]

    for event_type in disk_event_types:
        # rendered_rows structure matches what process_slave_events uses when building the batch HTML.
        rendered_rows = [
            {
                "host_user_name": user,
                "device_name": base_detail["device_name"],
                "event_type": event_type,
                "detail": base_detail,
            }
        ]
        subject, body_html = _render_disk_batch_email(host_id, user, rendered_rows)
        filename = f"{event_type}.html"
        (OUTPUT_DIR / filename).write_text(
            f"<!doctype html><html><head><meta charset='utf-8'><title>{subject}</title></head><body>{body_html}</body></html>",
            encoding="utf-8",
        )


def main() -> None:
    from app import create_app

    app = create_app()
    with app.app_context():
        _ensure_output_dir()
        generate_docker_previews()
        generate_disk_previews()
        print(f"Generated email previews in: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    # Ensure the project root is on sys.path when running directly.
    os.chdir(Path(__file__).resolve().parents[1])
    main()

