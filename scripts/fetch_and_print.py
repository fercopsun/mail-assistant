#!/usr/bin/env python3
"""
v0.2 验收脚本：从所有已配置邮箱抓取最近 24 小时邮件，经 LLM 分类后按四组打印。

用法：
    python scripts/fetch_and_print.py
    python scripts/fetch_and_print.py --hours 48
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage import load_accounts, load_llm_config
from core.mail_fetcher import fetch_recent_mails
from core.classifier import classify_mails, CATEGORIES


def main():
    parser = argparse.ArgumentParser(description="抓取并分类最近邮件")
    parser.add_argument("--hours", type=int, default=24, help="抓取最近 N 小时（默认 24）")
    args = parser.parse_args()

    accounts = load_accounts()
    llm = load_llm_config()
    print(f"已加载 {len(accounts)} 个账号，抓取最近 {args.hours} 小时邮件…\n")

    all_mails = []
    for acc in accounts:
        print(f"正在抓取 {acc['address']}…", end=" ", flush=True)
        try:
            mails, warnings = fetch_recent_mails(
                provider_name=acc["provider"],
                address=acc["address"],
                password=acc["password"],
                hours=args.hours,
                verbose=True,
            )
            for w in warnings:
                print(f"[警告] {w}")
            print(f"{len(mails)} 封")
            all_mails.extend(mails)
        except Exception as e:
            print(f"[错误] {e}")

    if not all_mails:
        print("\n该时间段内无新邮件。")
        return

    print(f"\n共 {len(all_mails)} 封，正在调用 LLM 分类…\n")
    classified = classify_mails(
        mails=all_mails,
        api_key=llm["api_key"],
        base_url=llm["base_url"],
        model=llm["model"],
    )

    # 按四个固定分组打印
    groups = {cat: [] for cat in CATEGORIES}
    for m in classified:
        groups.setdefault(m.category, []).append(m)

    for cat in CATEGORIES:
        items = groups.get(cat, [])
        print(f"{'━' * 40}")
        print(f"  {cat}（{len(items)} 封）")
        print(f"{'━' * 40}")
        if not items:
            print("  （无）\n")
            continue
        for m in items:
            date_str = m.date.strftime("%m-%d %H:%M")
            print(f"  [{date_str}] {m.subject}")
            print(f"  发件人：{m.sender}")
            print(f"  原因：{m.reason}\n")


if __name__ == "__main__":
    main()
