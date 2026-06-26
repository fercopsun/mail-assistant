"""IMAP 已读标记：独立的写操作连接，与只读抓取层完全隔离。"""

import imaplib
from core.providers import get_provider

_IMAP_TIMEOUT = 60


def mark_as_read(
    provider_name: str,
    address: str,
    password: str,
    uids: list[str],
    folder: str = "INBOX",
) -> tuple[int, list[str]]:
    """
    将指定序列号列表对应的邮件标记为已读（+\\Seen 标志位）。

    使用独立的 readonly=False 连接，与 mail_fetcher.py 的 readonly=True 连接
    完全隔离。除此函数外，项目其他部分不会产生任何 IMAP 写操作。

    返回 (成功数量, 失败的序列号列表)。
    """
    if not uids:
        return 0, []

    prov = get_provider(provider_name)
    success_count = 0
    failed: list[str] = []

    with imaplib.IMAP4_SSL(
        prov["imap_host"], prov["imap_port"], timeout=_IMAP_TIMEOUT
    ) as imap:
        imap.login(address, password)
        imap.select(folder, readonly=False)  # 明确非只读，仅此函数使用

        for uid in uids:
            try:
                status, _ = imap.store(uid, "+FLAGS", "\\Seen")
                if status == "OK":
                    success_count += 1
                else:
                    failed.append(uid)
            except Exception:
                failed.append(uid)

    return success_count, failed
