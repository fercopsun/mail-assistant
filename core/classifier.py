"""邮件四象限分类：调用 LLM，批量返回每封邮件的优先级和原因。"""

import json
import re
from dataclasses import dataclass

from core.llm_client import call_llm
from core.mail_fetcher import MailItem

CATEGORIES = ["今天必须处理", "本周跟进", "仅供参考", "可忽略"]

# Prompt 模板放在模块级常量，方便后续根据误判单独调整
_SYSTEM_PROMPT = """\
你是一个邮件优先级助手。对于用户给出的邮件列表，为每封邮件打一个分类标签，并给出一句话原因。

分类规则：
- 今天必须处理：有明确截止日期在今天或已逾期、需要本人决策或回复、紧急事项
- 本周跟进：需要回复但不紧急、正在进行中的项目更新、本周内的会议/任务提醒
- 仅供参考：通知类、抄送类、无需操作的进度更新
- 可忽略：营销推广、订阅通讯、自动化系统通知

输出要求：
- 严格返回 JSON 数组，不要有任何其他文字
- 每个元素格式：{"uid": "...", "category": "...", "reason": "一句话，不超过30字"}
- category 必须是以下之一：今天必须处理、本周跟进、仅供参考、可忽略
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
    返回列表顺序与输入一致，解析失败的邮件默认归入「仅供参考」。
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
        {"role": "user", "content": f"请对以下邮件进行分类：\n\n{mail_list_text}"},
    ]

    raw = call_llm(api_key=api_key, base_url=base_url, model=model, messages=messages)

    # 从回复中提取 JSON，兼容模型在 JSON 前后多输出文字的情况
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
                category=entry.get("category", "仅供参考"),
                reason=entry.get("reason", "（分类结果解析失败）"),
                message_id=m.message_id,
            )
        )
    return classified


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
