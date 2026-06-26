#!/usr/bin/env python3
"""
v0.1 验收脚本：从所有已配置邮箱抓取最近 24 小时邮件，打印标题列表。

用法：
    python scripts/fetch_and_print.py
    python scripts/fetch_and_print.py --hours 48
"""

import sys
import argparse
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage import load_accounts
from core.mail_fetcher import fetch_recent_mails


def main():
    parser = argparse.ArgumentParser(description="抓取最近邮件并打印列表")
    parser.add_argument("--hours", type=int, default=24, help="抓取最近 N 小时（默认 24）")
    args = parser.parse_args()

    accounts = load_accounts()
    print(f"已加载 {len(accounts)} 个账号，抓取最近 {args.hours} 小时邮件…\n")

    total = 0
    for acc in accounts:
        provider = acc["provider"]
        address = acc["address"]
        print(f"── {address} ({provider}) ──")
        try:
            mails = fetch_recent_mails(
                provider_name=provider,
                address=address,
                password=acc["password"],
                hours=args.hours,
            )
            if not mails:
                print("  （该时间段内无新邮件）")
            for m in mails:
                date_str = m.date.strftime("%m-%d %H:%M")
                print(f"  [{date_str}] {m.subject}")
                print(f"           发件人：{m.sender}")
            total += len(mails)
        except Exception as e:
            print(f"  [错误] {e}")
        print()

    print(f"共抓取 {total} 封邮件。")


if __name__ == "__main__":
    main()
