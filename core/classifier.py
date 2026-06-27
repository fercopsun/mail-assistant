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
- 需要回复：真实的人直接写信给收件人，明确期待收件人写邮件回复（提问、请求协助、需要确认或同意等）
- 需要处理（非回复）：不需要回信，但收件人需要去做某件具体的事（付款、续费、填写表单、点链接操作账户等）
- 记录/公告：服务商针对收件人这个具体账号发来的一对一事务性通知，不能取消订阅。
  典型例子：账号安全提醒（登录异常、新设备登录）、付款/订单收据、密码变更确认、
  订阅续费成功或失败、服务条款/隐私政策变更通知、物流状态更新。
  发件人通常是 security/billing/service/noreply@某服务商自己的域名（不是邮件列表平台）。
- 广告/可忽略：任何可以取消订阅（unsubscribe）的群发内容，不论内容读起来多正式。
  包括：商业促销/营销/newsletter、活动邀请、社区平台内容摘要（Nextdoor、Reddit等）、
  志愿者团体/组织/协会的周报或群发更新、任何以"Dear all"/"Hi everyone"等群发问候语
  开头的内容——这类邮件本质上都是邮件列表，有 unsubscribe 机制，均归此类。

"记录/公告"与"广告/可忽略"的判断核心——遇到边界情况时按顺序检查：
1. 这封邮件能不能取消订阅？
   - 正文或页脚有 unsubscribe / 退订 / 取消订阅 → 广告/可忽略
2. 发件人域名是邮件列表服务商（含 mail / list / newsletter / campaign / send 等词的发信域名）？
   - 是（如 volunteer2mail.com、mailchimp.com、sendgrid.net 等）→ 广告/可忽略
3. 内容是否用"Dear all"/"Hi everyone"等群发问候语，而非针对收件人个人的称呼？
   - 是 → 广告/可忽略
4. 经过以上三条仍不确定时，最后问：这是不是该服务商只会发给"你这个具体账号"的通知？
   - 是（账号操作、交易记录、密码变更等）→ 记录/公告
   - 否（群发给所有用户或订阅者的内容）→ 广告/可忽略

判断"需要回复"的强排除信号——凡是命中以下任意一条，必须排除"需要回复"：
1. 发件人地址包含 no-reply、noreply、do-not-reply、donotreply（含变体）：
   这类地址是单向通知，回复无法到达任何真实收件人。
2. 发件人名称或邮件内容表明这是平台自动聚合推送（"Your XXX neighbors"、"XXX Digest"、
   内容格式为"帖子摘要 + 多个发帖人"等）：不是真人直接发给收件人的信件。
3. 内容是他人帖子的转载/摘要（Posts: 列表、社区通知聚合等）：
   帖子里的"问题"不是在问收件人，收件人无需回复这封邮件。

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
