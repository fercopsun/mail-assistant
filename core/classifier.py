"""邮件分流分类：四种性质类型 + 「需要处理」组的汇总简报。"""

import json
import re
from dataclasses import dataclass

from core.llm_client import call_llm
from core.mail_fetcher import MailItem

CATEGORIES = ["需要回复", "需要处理（非回复）", "记录/公告", "广告/可忽略"]

_SYSTEM_PROMPT = """\
你是一个邮件分流助手。根据邮件的实际性质，将每封邮件分入以下四种类型之一：

类型定义：
- 需要回复：发件人明确期待收信人写邮件回复（提问、请求协助、需要确认或同意等）
- 需要处理（非回复）：不需要回信，但收信人需要去做某件具体的事（付款、续费、填写表单、点链接操作账户等）
- 记录/公告：收据、成功确认、系统通知、抄送知会等，纯记录用途，不需要任何动作
- 广告/可忽略：营销推送、订阅邮件、活动宣传、社区噪音等

输出要求：
- 严格返回 JSON 数组，不要有任何其他文字
- 每个元素格式：{"uid": "...", "category": "...", "reason": "一句话，不超过30字"}
- category 必须是以下之一：需要回复、需要处理（非回复）、记录/公告、广告/可忽略
"""


@dataclass
class ClassifiedMail:
    uid: str
    account: str
    subject: str
    sender: str
    date: object   # datetime
    snippet: str
    category: str
    reason: str
    message_id: str = ""


def classify_mails(
    mails: list[MailItem],
    api_key: str,
    base_url: str,
    model: str,
) -> list[ClassifiedMail]:
    """
    批量分类邮件，一次 LLM 调用处理所有邮件。
    返回列表顺序与输入一致，解析失败的邮件默认归入「记录/公告」。
    """
    if not mails:
        return []

    mail_list_text = "\n".join(
        f'- uid:{m.uid} 主题:{m.subject} 发件人:{m.sender} '
        f'时间:{m.date.strftime("%Y-%m-%d %H:%M")} 摘要:{m.snippet[:100]}'
        for m in mails
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"请对以下邮件进行分流分类：\n\n{mail_list_text}"},
    ]

    raw = call_llm(api_key=api_key, base_url=base_url, model=model, messages=messages)
    results_by_uid = _parse_json(raw)

    classified = []
    for m in mails:
        entry = results_by_uid.get(str(m.uid), {})
        classified.append(
            ClassifiedMail(
                uid=m.uid,
                account=m.account,
                subject=m.subject,
                sender=m.sender,
                date=m.date,
                snippet=m.snippet,
                category=entry.get("category", "记录/公告"),
                reason=entry.get("reason", "（分类结果解析失败）"),
                message_id=m.message_id,
            )
        )
    return classified


def generate_brief(
    mails: list,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    对「需要处理（非回复）」这一组邮件做汇总，生成一段话形式的行动简报。
    提炼关键信息：每件事是什么、涉及金额（如有）、截止时间（如有）、需要做什么。

    独立于分类调用，单独调用一次 LLM。
    接受 MailItem 或 ClassifiedMail，只访问 subject / sender / date / snippet 字段。
    """
    if not mails:
        return ""

    mail_list_text = "\n".join(
        f'- 主题：{m.subject}  发件人：{m.sender}  '
        f'时间：{m.date.strftime("%Y-%m-%d %H:%M")}  摘要：{m.snippet[:150]}'
        for m in mails
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个助手，负责把多封「需要处理」的邮件提炼成一段话的行动简报，"
                "用中文，简洁列出：每件事是什么、涉及金额（如有）、截止时间（如有）、"
                "需要做什么动作。不超过 150 字，不要逐条编号，写成自然段落。"
            ),
        },
        {
            "role": "user",
            "content": f"以下邮件都需要我处理，请汇总：\n\n{mail_list_text}",
        },
    ]

    return call_llm(api_key=api_key, base_url=base_url, model=model, messages=messages)


def _parse_json(text: str) -> dict[str, dict]:
    """提取 JSON 数组并转为 uid → entry 字典，解析失败返回空字典。"""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return {}
    try:
        items = json.loads(match.group())
        return {str(item["uid"]): item for item in items if "uid" in item}
    except (json.JSONDecodeError, TypeError):
        return {}
