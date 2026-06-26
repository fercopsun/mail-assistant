# 模块架构说明

```
mail_assistant/
├── README.md
├── ARCHITECTURE.md
├── ROADMAP.md
├── requirements.txt
├── .gitignore                  # 必须排除 config/accounts.yaml 和任何含密钥的文件
│
├── config/
│   ├── accounts.example.yaml   # 邮箱账号配置模板（不含真实密钥）
│   └── llm.example.yaml        # LLM 提供商配置模板（api_key / base_url / model）
│
├── core/
│   ├── providers.py            # 各邮箱服务商的服务器参数 + 认证方式注册表
│   ├── mail_fetcher.py         # 通用 IMAP 抓取层，对各 provider 统一封装
│   ├── mail_sender.py          # 通用 SMTP 发送层，内置"需确认"开关
│   ├── llm_client.py           # OpenAI 兼容的通用 LLM 调用封装
│   ├── classifier.py           # 调用 llm_client，对邮件做象限分类
│   ├── draft_generator.py      # 调用 llm_client，结合上下文生成回信草稿
│   └── storage.py              # 本地配置/密钥的读写，含基本的存在性校验
│
├── ui/
│   └── app.py                  # Streamlit 入口（设置页 / 摘要视图 / 草稿与发送）
│
└── scripts/
    ├── fetch_and_print.py      # v0.1 验收脚本：抓取并打印邮件列表
    └── run_daily.py            # 被 cron / 任务计划程序调用的入口脚本
```

## 各模块职责详解

### `core/providers.py`
**职责**：维护一份「邮箱品牌 → 连接参数」的注册表，是新增邮箱支持的唯一入口。

每个 provider 至少包含：
- `imap_host`, `imap_port`
- `smtp_host`, `smtp_port`
- `auth_type`：`"password_or_authcode"` 或 `"oauth2"`
- 一段简短说明文字，提示用户去哪里获取授权码（用于设置页面展示）

**为什么单独抽出来**：以后新增邮箱品牌，理论上只改这一个文件，不动其他逻辑。

---

### `core/mail_fetcher.py`
**职责**：给定一个账号配置（品牌 + 地址 + 密码），抓取「最近 N 小时」的邮件，返回统一格式的邮件对象列表（发件人、主题、正文摘要、时间、原始链接/ID、所属账号）。

**关键设计**：不同品牌 IMAP 的细节差异应该在这一层被「抹平」，上层（分类、起草）接触的永远是同一种数据结构，上层代码不需要关心这封邮件来自哪个邮箱品牌。

---

### `core/mail_sender.py`
**职责**：给定账号配置 + 收件人 + 正文，通过 SMTP 发送。

**关键设计**：默认 `require_confirmation=True`，调用方必须显式传入用户的确认动作才会真正发信，该模块本身不做任何「自动判断是否要发」的逻辑，发与不发完全由上层 UI 的人工点击决定。

---

### `core/llm_client.py`
**职责**：把「调用一个 OpenAI 兼容 chat completions 接口」这件事封装成一个函数，输入 `api_key`、`base_url`、`model`、`messages`，返回模型回复文本。

**关键设计**：这是整个项目唯一允许「认识具体品牌」的地方仅限于兼容性微调（比如某些服务商的字段命名差异），核心逻辑必须保持品牌无关——这样用户填别的 API，无需改代码。

---

### `core/classifier.py`
**职责**：输入一批邮件（来自 `mail_fetcher`），调用 `llm_client`，输出每封邮件的分类结果（`今天必须处理 / 本周跟进 / 仅供参考 / 可忽略`）附带一句话的原因。

**关键设计**：分类的 prompt 模板应该是可调的（参见此前讨论的「跑两周根据误判调整规则」的思路），建议把 prompt 模板放在一个独立的常量或配置里，方便迭代，不要硬编码在函数中间。

---

### `core/draft_generator.py`
**职责**：输入「原邮件上下文（含历史往来）」+「用户加入的关键词/草稿」，调用 `llm_client`，输出一段措辞得体的后续回复。

**关键设计**：这个模块只负责「生成文本」，不负责发送，发送动作交给 UI 层调用 `mail_sender`。

---

### `core/storage.py`
**职责**：读写本地配置文件（账号列表、LLM 设置），并做基本的格式校验（必填字段缺失时给出明确报错，而不是静默失败）。

---

### `ui/app.py`
**职责**：Streamlit 界面，包含三个视图：
1. **设置页**：填邮箱账号+密码（可加多个）、填 LLM 的 api_key/base_url/model
2. **摘要视图**：展示 `classifier` 的输出，按四个分组，每条带跳转原邮件的链接
3. **草稿与发送**：选中一封邮件，输入框 + 生成按钮，调用 `draft_generator`；生成结果可编辑，最后点明确的「确认发送」按钮，调用 `mail_sender`

---

### `scripts/run_daily.py`
**职责**：一个无界面的入口脚本——遍历所有已配置的账号，抓取邮件，获取分类，将结果存一份（比如一个 JSON 或直接写入 Streamlit 能读的缓存文件），供用户打开界面时直接看到当天的摘要结果，而不用现场等待。

这是给 `cron` /「任务计划程序」调用的脚本，本身不依赖 Streamlit 运行。

## 模块依赖关系（自底向上）

```
providers.py  →  mail_fetcher.py  ──┐
                                     ├──  classifier.py  ──┐
                  llm_client.py  ────┤                     ├──  ui/app.py
                                     └──  draft_generator.py ──┘   scripts/run_daily.py
providers.py  →  mail_sender.py  ───┘
storage.py   →  （被 ui/app.py 和 run_daily.py 共用）
```

底层：`providers` / `llm_client` / `storage`，完全不依赖上层，方便单独测试。
