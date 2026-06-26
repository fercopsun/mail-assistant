"""通用 IMAP 邮件抓取层，对上层屏蔽服务商差异。"""

import imaplib
import email
import email.header
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass, field

from core.providers import get_provider


@dataclass
class MailItem:
    uid: str
    account: str          # 所属邮箱地址
    subject: str
    sender: str
    date: datetime
    snippet: str          # 正文前 300 字
    raw_link: str = ""    # 占位，UI 层可用于跳转


def _decode_header(value: str) -> str:
    parts = email.header.decode_header(value)
    result = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            result.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(raw)
    return "".join(result)


def _extract_text(msg: email.message.Message) -> str:
    """从 MIME 结构中提取纯文本，截取前 300 字。"""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    text = payload.decode(charset, errors="replace")
                    break
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(charset, errors="replace")
    return text[:300].strip()


def fetch_recent_mails(
    provider_name: str,
    address: str,
    password: str,
    hours: int = 24,
    folder: str = "INBOX",
) -> list[MailItem]:
    """
    连接 IMAP，返回最近 `hours` 小时内收到的邮件列表。
    出错时抛出异常，由调用方决定如何处理。
    """
    prov = get_provider(provider_name)
    since_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_str = since_dt.strftime("%d-%b-%Y")

    with imaplib.IMAP4_SSL(prov["imap_host"], prov["imap_port"]) as imap:
        imap.login(address, password)
        imap.select(folder, readonly=True)

        _, data = imap.search(None, f'(SINCE "{since_str}")')
        uids = data[0].split() if data[0] else []

        mails: list[MailItem] = []
        for uid in uids:
            _, msg_data = imap.fetch(uid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, bytes):
                continue

            msg = email.message_from_bytes(raw)

            subject = _decode_header(msg.get("Subject", "(无主题)"))
            sender = _decode_header(msg.get("From", ""))
            date_str = msg.get("Date", "")
            try:
                date = email.utils.parsedate_to_datetime(date_str)
            except Exception:
                date = datetime.now(timezone.utc)

            # 二次过滤：parsedate 可能返回比 since_dt 更早的邮件
            if date < since_dt:
                continue

            snippet = _extract_text(msg)
            mails.append(
                MailItem(
                    uid=uid.decode(),
                    account=address,
                    subject=subject,
                    sender=sender,
                    date=date,
                    snippet=snippet,
                )
            )

    mails.sort(key=lambda m: m.date, reverse=True)
    return mails
