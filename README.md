# 多邮箱 AI 邮件助手

把你的多个邮箱汇总到一起，用自选的 LLM 每天自动分类邮件、辅助起草回信。完全跑在本地，密钥不离开你的电脑。

## 功能

- **每日摘要**：定时抓取最近邮件，按「今天必须处理 / 本周跟进 / 仅供参考 / 可忽略」四级分类，每条带优先级标注。
- **辅助回信**：选中一封邮件，输入你想表达的要点，AI 结合邮件上下文生成得体回复草稿，你可以编辑后再手动确认发送。

## 支持的邮箱

| 邮箱 | 认证方式 | 备注 |
|------|----------|------|
| Gmail | IMAP + 应用专用密码 | 在 Google 账户安全设置里生成 |
| QQ 邮箱 | IMAP + 授权码（16位） | 在邮箱设置 → 账户里开启并生成，不是 QQ 密码 |
| 163 / 126 邮箱 | IMAP + 客户端授权密码 | 在邮箱设置里开启后生成 |
| Outlook | OAuth2（计划支持） | 2026年4月后密码登录已全面失效 |

## 技术栈

- Python 3.11+
- Streamlit（本地网页界面）
- `imaplib` / `smtplib`（标准库）
- 任意 OpenAI 兼容 LLM（DeepSeek、OpenAI 等，填入 `api_key` / `base_url` / `model` 即可切换）
- `cron`（macOS/Linux）或任务计划程序（Windows）触发定时任务

## 快速开始

```bash
git clone https://github.com/fercopsun/mail-assistant.git
cd mail-assistant
pip install -r requirements.txt

cp config/accounts.example.yaml config/accounts.yaml
cp config/llm.example.yaml config/llm.yaml
# 编辑两个配置文件，填入邮箱授权码和 LLM API key

python scripts/fetch_and_print.py   # 验证邮箱连接
```

## 安全说明

- 所有密码和 API key 只存在本地 `config/accounts.yaml` 和 `config/llm.yaml`，这两个文件已在 `.gitignore` 中排除，不会被上传。
- 发送邮件前默认需要手动二次确认，AI 不会自动发出任何邮件。
