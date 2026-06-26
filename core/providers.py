"""已知邮箱服务商的连接参数注册表。"""

PROVIDERS = {
    "gmail": {
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "auth_type": "password_or_authcode",
        "hint": (
            "Gmail 请在「Google 账户 → 安全 → 应用专用密码」生成 16 位密码，"
            "并确保已开启 IMAP（Gmail 设置 → 转发和 POP/IMAP）。"
        ),
    },
    "qq": {
        "imap_host": "imap.qq.com",
        "imap_port": 993,
        "smtp_host": "smtp.qq.com",
        "smtp_port": 587,
        "auth_type": "password_or_authcode",
        "hint": (
            "QQ 邮箱请在「邮箱设置 → 账户 → IMAP/SMTP 服务」开启后生成授权码，"
            "授权码为 16 位，不是 QQ 密码。"
        ),
    },
    "163": {
        "imap_host": "imap.163.com",
        "imap_port": 993,
        "smtp_host": "smtp.163.com",
        "smtp_port": 465,
        "smtp_use_ssl": True,
        "auth_type": "password_or_authcode",
        "hint": (
            "163 邮箱请在「设置 → POP3/SMTP/IMAP → 客户端授权密码」开启并生成授权码。"
        ),
    },
    "126": {
        "imap_host": "imap.126.com",
        "imap_port": 993,
        "smtp_host": "smtp.126.com",
        "smtp_port": 465,
        "smtp_use_ssl": True,
        "auth_type": "password_or_authcode",
        "hint": (
            "126 邮箱请在「设置 → POP3/SMTP/IMAP → 客户端授权密码」开启并生成授权码。"
        ),
    },
    "outlook": {
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "auth_type": "oauth2",
        "hint": (
            "Outlook 自 2026 年 4 月起强制使用 OAuth2，"
            "密码登录方式已失效，请等待后续版本支持。"
        ),
    },
}


def get_provider(name: str) -> dict:
    """返回服务商配置，未知服务商抛出 ValueError。"""
    key = name.lower()
    if key not in PROVIDERS:
        raise ValueError(
            f"未知服务商 '{name}'，已支持：{', '.join(PROVIDERS)}"
        )
    return PROVIDERS[key]
