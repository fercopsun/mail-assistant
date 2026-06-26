"""通用 IMAP 邮件抓取层，对上层屏蔽服务商差异。"""

import re
import imaplib
import email
import email.header
import email.utils
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from core.providers import get_provider

_HEADER_BATCH  = 500  # 每次批量拉取头部的邮件数
_BODY_BATCH    = 100  # 每次批量拉取正文的邮件数
_IMAP_TIMEOUT  = 60   # IMAP 连接/操作超时秒数（兜底网络故障）
_MAX_CANDIDATE = 500  # 候选邮件上限：只取最新 N 封
                      # QQ 等服务商不支持 SINCE 时会返回整个收件箱，
                      # 此上限避免拉取几万封头部。个人账号每天收到的
                      # 邮件远少于此值，500 已足够安全。


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


def _safe_charset(charset: str | None) -> str:
    """把非标准 charset（如 unknown-8bit）统一转为可用的解码器名称。"""
    if not charset:
        return "utf-8"
    try:
        "".encode().decode(charset)
        return charset
    except LookupError:
        return "latin-1"


def _extract_text(msg: email.message.Message) -> str:
    """从 MIME 结构中提取纯文本，截取前 300 字。"""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = _safe_charset(part.get_content_charset())
                payload = part.get_payload(decode=True)
                if payload:
                    text = payload.decode(charset, errors="replace")
                    break
    else:
        charset = _safe_charset(msg.get_content_charset())
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(charset, errors="replace")
    return text[:300].strip()


def _parse_date(raw: str) -> datetime | None:
    """解析 Date 头，返回 aware datetime；失败返回 None。"""
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            # -0000 时区（QQ 常见）视为 UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _seq_num(meta: bytes) -> str | None:
    """从 IMAP fetch 响应元数据中提取序列号，如 b'42 (BODY...)' → '42'。"""
    m = re.match(rb"(\d+)\s", meta)
    return m.group(1).decode() if m else None


def fetch_recent_mails(
    provider_name: str,
    address: str,
    password: str,
    hours: int = 24,
    folder: str = "INBOX",
    verbose: bool = False,
) -> list[MailItem]:
    """
    两步流程：
    1. 批量拉取头部（Date/From/Subject），客户端过滤出最近 `hours` 小时内的邮件。
    2. 只对通过过滤的邮件批量拉取完整正文。

    这样即使 IMAP 服务器不支持 SINCE 过滤（如 QQ），也不会把整个收件箱
    的完整正文全部下载下来。
    """
    def log(msg: str) -> None:
        if verbose:
            print(f"    [{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    prov = get_provider(provider_name)
    since_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_str = since_dt.strftime("%d-%b-%Y")

    t0 = time.time()
    log(f"正在连接 {prov['imap_host']}:{prov['imap_port']}…")

    with imaplib.IMAP4_SSL(
        prov["imap_host"], prov["imap_port"], timeout=_IMAP_TIMEOUT
    ) as imap:
        log(f"连接完成（{time.time()-t0:.1f}s），正在登录…")
        t1 = time.time()

        imap.login(address, password)
        log(f"登录完成（{time.time()-t1:.1f}s），正在选择文件夹…")
        t2 = time.time()

        imap.select(folder, readonly=True)
        log(f"文件夹 OK（{time.time()-t2:.1f}s），正在搜索 SINCE {since_str}…")
        t3 = time.time()

        _, data = imap.search(None, f'(SINCE "{since_str}")')
        all_uids = data[0].split() if data[0] else []

        # 部分服务商（如 QQ）不支持 SINCE，会返回整个收件箱。
        # IMAP 序列号按时间升序排列，截取末尾 N 封即为最新邮件。
        if len(all_uids) > _MAX_CANDIDATE:
            log(
                f"搜索完成（{time.time()-t3:.1f}s），"
                f"SINCE 返回 {len(all_uids)} 封（服务商未过滤），"
                f"截取最新 {_MAX_CANDIDATE} 封…"
            )
            all_uids = all_uids[-_MAX_CANDIDATE:]
        else:
            log(
                f"搜索完成（{time.time()-t3:.1f}s），"
                f"候选 {len(all_uids)} 封，批量拉取头部…"
            )

        # ── 第一步：批量拉头部，客户端过滤日期 ──────────────────────────
        t4 = time.time()
        passing: list[bytes] = []

        for i in range(0, len(all_uids), _HEADER_BATCH):
            chunk = all_uids[i : i + _HEADER_BATCH]
            seq_set = b",".join(chunk).decode()
            _, hdr_data = imap.fetch(
                seq_set, "(BODY[HEADER.FIELDS (DATE FROM SUBJECT)])"
            )
            for item in hdr_data:
                if not isinstance(item, tuple):
                    continue
                seq = _seq_num(item[0])
                if seq is None:
                    continue
                hdr_msg = email.message_from_bytes(item[1])
                dt = _parse_date(hdr_msg.get("Date", ""))
                # 日期无法解析时保守地纳入（避免漏掉真实近期邮件）
                if dt is None or dt >= since_dt:
                    passing.append(seq.encode())

        log(
            f"头部阶段完成（{time.time()-t4:.1f}s），"
            f"{len(passing)} 封在 {hours}h 内，拉取正文…"
        )

        # ── 第二步：只对通过过滤的邮件批量拉完整正文 ────────────────────
        t5 = time.time()
        mails: list[MailItem] = []

        for i in range(0, len(passing), _BODY_BATCH):
            chunk = passing[i : i + _BODY_BATCH]
            seq_set = b",".join(chunk).decode()
            _, body_data = imap.fetch(seq_set, "(RFC822)")
            for item in body_data:
                if not isinstance(item, tuple):
                    continue
                raw = item[1]
                if not isinstance(raw, bytes):
                    continue
                msg = email.message_from_bytes(raw)
                uid = _seq_num(item[0]) or "?"
                subject = _decode_header(msg.get("Subject", "(无主题)"))
                sender  = _decode_header(msg.get("From", ""))
                dt = _parse_date(msg.get("Date", "")) or datetime.now(timezone.utc)
                if dt < since_dt:
                    continue  # 二次精确过滤（头部阶段仅按天过滤时的残余）
                snippet = _extract_text(msg)
                mails.append(
                    MailItem(
                        uid=uid,
                        account=address,
                        subject=subject,
                        sender=sender,
                        date=dt,
                        snippet=snippet,
                    )
                )

        log(
            f"正文阶段完成（{time.time()-t5:.1f}s），"
            f"有效 {len(mails)} 封，总耗时 {time.time()-t0:.1f}s"
        )

    mails.sort(key=lambda m: m.date, reverse=True)
    return mails
