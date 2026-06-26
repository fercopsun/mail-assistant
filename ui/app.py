"""Streamlit UI：设置页 + 分流视图（v0.4，只读）"""

import sys
import urllib.parse
from pathlib import Path
from datetime import datetime

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage import load_accounts, save_accounts, load_llm_config, save_llm_config
from core.mail_fetcher import fetch_recent_mails, MailItem
from core.classifier import classify_mails, ClassifiedMail, CATEGORIES
from core.providers import PROVIDERS


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _mail_link(m: ClassifiedMail) -> str:
    """为邮件构造 webmail 跳转链接。Gmail 可精确定位到该封邮件；其他品牌跳收件箱。"""
    if m.message_id and "@gmail.com" in m.account:
        return (
            "https://mail.google.com/mail/#search/rfc822msgid:"
            + urllib.parse.quote(m.message_id, safe="")
        )
    if "@qq.com" in m.account:
        return "https://mail.qq.com/"
    if "@163.com" in m.account:
        return "https://mail.163.com/"
    if "@126.com" in m.account:
        return "https://mail.126.com/"
    return ""


def _render_mail(m: ClassifiedMail) -> None:
    date_str = m.date.strftime("%m-%d %H:%M")
    link = _mail_link(m)
    col_main, col_btn = st.columns([8, 1])
    with col_main:
        title = f"[{m.subject}]({link})" if link else m.subject
        st.markdown(f"**{title}**")
        st.caption(f"🕐 {date_str}　📬 {m.sender}")
        st.text(m.reason)
    with col_btn:
        if link:
            st.link_button("打开", link, use_container_width=True)
    st.divider()


# ── 抓取 + 分类 ───────────────────────────────────────────────────────────────

def _run_fetch(hours: int) -> None:
    """抓取所有账号并分类；结果写入 st.session_state。"""
    try:
        accounts = load_accounts()
        llm = load_llm_config()
    except (FileNotFoundError, ValueError) as e:
        st.session_state.fetch_error = str(e)
        st.session_state.results = None
        return

    st.session_state.fetch_error = None
    st.session_state.account_warnings = {}

    all_mails = []
    fetch_errors = []

    progress = st.progress(0, text="正在准备…")

    for idx, acc in enumerate(accounts):
        progress.progress(
            idx / max(len(accounts), 1),
            text=f"正在抓取 {acc['address']}…",
        )
        try:
            mails, warnings = fetch_recent_mails(
                provider_name=acc["provider"],
                address=acc["address"],
                password=acc["password"],
                hours=hours,
                verbose=False,
            )
            all_mails.extend(mails)
            if warnings:
                st.session_state.account_warnings[acc["address"]] = warnings
        except Exception as e:
            fetch_errors.append(f"{acc['address']}：{e}")

    if fetch_errors:
        st.session_state.fetch_error = "\n\n".join(fetch_errors)

    if all_mails:
        progress.progress(0.95, text="正在调用 LLM 分类…")
        classified = classify_mails(
            mails=all_mails,
            api_key=llm["api_key"],
            base_url=llm["base_url"],
            model=llm["model"],
        )
        st.session_state.results = classified
    else:
        st.session_state.results = []

    st.session_state.fetch_hours = hours
    st.session_state.fetch_time = datetime.now().strftime("%H:%M")
    progress.empty()


# ── 摘要视图 ──────────────────────────────────────────────────────────────────

def summary_page() -> None:
    st.title("📬 邮件摘要")

    col_sel, col_btn, _ = st.columns([2, 1, 6])
    with col_sel:
        hours = st.selectbox(
            "时间范围",
            [24, 48, 72],
            format_func=lambda h: f"最近 {h} 小时",
            label_visibility="collapsed",
        )
    with col_btn:
        fetch_btn = st.button("刷新", type="primary", use_container_width=True)

    if fetch_btn:
        _run_fetch(hours)
        st.rerun()

    if "results" not in st.session_state:
        st.info("点击「刷新」开始抓取并分类邮件。")
        return

    if st.session_state.get("fetch_error"):
        st.error(st.session_state.fetch_error)

    results = st.session_state.get("results")
    if results is None:
        return

    fetch_time = st.session_state.get("fetch_time", "")
    fetch_hours = st.session_state.get("fetch_hours", hours)
    if fetch_time:
        st.caption(f"最后更新：{fetch_time}　覆盖最近 {fetch_hours} 小时")

    # ── 截断警告横幅（来自 mail_fetcher 的 was_truncated 检测）───────────────
    warnings_map: dict[str, list[str]] = st.session_state.get("account_warnings", {})
    for account, wlist in warnings_map.items():
        for w in wlist:
            st.warning(f"⚠️ **{account}**：{w}")

    if not results:
        st.success("该时间段内没有需要关注的邮件。")
        return

    # ── 四组展示 ─────────────────────────────────────────────────────────────
    groups: dict[str, list[ClassifiedMail]] = {cat: [] for cat in CATEGORIES}
    for m in results:
        groups.setdefault(m.category, []).append(m)

    icons = {
        "今天必须处理": "🔴",
        "本周跟进": "🟡",
        "仅供参考": "🔵",
        "可忽略": "⚪",
    }
    # 紧急分组默认展开，其余折叠
    auto_expand = {"今天必须处理", "本周跟进"}

    for cat in CATEGORIES:
        items = groups.get(cat, [])
        icon = icons.get(cat, "")
        with st.expander(
            f"{icon} **{cat}**（{len(items)} 封）",
            expanded=(cat in auto_expand and len(items) > 0),
        ):
            if not items:
                st.caption("（无）")
            else:
                for m in items:
                    _render_mail(m)


# ── 设置页 ────────────────────────────────────────────────────────────────────

def settings_page() -> None:
    st.title("⚙️ 设置")

    # ── 邮箱账号 ─────────────────────────────────────────────────────────────
    st.subheader("邮箱账号")

    try:
        accounts: list[dict] = load_accounts()
    except FileNotFoundError:
        accounts = []
    except ValueError as e:
        st.error(str(e))
        accounts = []

    if accounts:
        to_delete: int | None = None
        for i, acc in enumerate(accounts):
            c1, c2, c3 = st.columns([4, 4, 1])
            with c1:
                st.text(f"{acc.get('provider', '?').upper()}   {acc['address']}")
            with c2:
                st.text("••••••••••••")
            with c3:
                if st.button("删除", key=f"del_{i}"):
                    to_delete = i
        if to_delete is not None:
            accounts.pop(to_delete)
            save_accounts(accounts)
            st.rerun()
    else:
        st.caption("暂无账号，请在下方添加。")

    st.markdown("---")

    # outlook 尚不支持（OAuth2），不在下拉列表里展示
    provider_opts = [k for k in PROVIDERS if k != "outlook"]

    with st.form("add_account", clear_on_submit=True):
        st.write("**添加账号**")
        c1, c2 = st.columns(2)
        with c1:
            provider = st.selectbox("服务商", provider_opts)
        with c2:
            address = st.text_input("邮箱地址")
        password = st.text_input("密码 / 授权码", type="password")
        st.info(PROVIDERS[provider]["hint"])

        if st.form_submit_button("添加", type="primary"):
            if not address.strip() or not password:
                st.error("邮箱地址和密码不能为空。")
            else:
                accounts.append({
                    "provider": provider,
                    "address": address.strip(),
                    "password": password,
                })
                save_accounts(accounts)
                st.success(f"已添加 {address.strip()}")
                st.rerun()

    # ── LLM 配置 ─────────────────────────────────────────────────────────────
    st.subheader("LLM 配置")

    try:
        llm = load_llm_config()
    except (FileNotFoundError, ValueError):
        llm = {}

    with st.form("llm_config"):
        api_key = st.text_input(
            "API Key",
            value=llm.get("api_key", ""),
            type="password",
            help="必填。OpenAI 兼容格式（sk-xxx 或 DeepSeek key 等）。",
        )
        base_url = st.text_input(
            "Base URL",
            value=llm.get("base_url", ""),
            placeholder="https://api.openai.com/v1",
            help="可选。留空则使用官方 OpenAI 接口。",
        )
        model = st.text_input(
            "模型名称",
            value=llm.get("model", ""),
            placeholder="gpt-4o 或 deepseek-v4-flash 等",
            help="必填。",
        )

        if st.form_submit_button("保存", type="primary"):
            if not api_key.strip() or not model.strip():
                st.error("API Key 和模型名称为必填项。")
            else:
                cfg: dict = {"api_key": api_key.strip(), "model": model.strip()}
                if base_url.strip():
                    cfg["base_url"] = base_url.strip()
                save_llm_config(cfg)
                st.success("LLM 配置已保存。")


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="邮件助手",
        page_icon="📬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    with st.sidebar:
        st.title("📬 邮件助手")
        st.caption("v0.4 · 本地运行")
        st.divider()
        page = st.radio(
            "导航",
            ["📬 摘要", "⚙️ 设置"],
            label_visibility="collapsed",
        )

    if page == "📬 摘要":
        summary_page()
    else:
        settings_page()


if __name__ == "__main__":
    main()
