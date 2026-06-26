"""Streamlit UI：设置页 + 分流视图（v0.4）"""

import sys
import urllib.parse
from pathlib import Path
from datetime import datetime

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.storage import (
    load_accounts, save_accounts,
    load_llm_config, save_llm_config,
    load_settings, save_settings,
)
from core.mail_fetcher import fetch_recent_mails, MailItem
from core.mail_marker import mark_as_read
from core.classifier import classify_mails, generate_brief, ClassifiedMail, CATEGORIES
from core.providers import PROVIDERS


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _mail_link(m: ClassifiedMail) -> str:
    """为邮件构造 webmail 跳转链接。Gmail 可精确定位；其他品牌跳收件箱。"""
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


def _do_mark_as_read(
    mails: list[ClassifiedMail],
    accounts_map: dict[str, dict],
) -> tuple[int, list[str]]:
    """按账号分组批量调用 mark_as_read，汇总成功/失败数。"""
    by_account: dict[str, list[ClassifiedMail]] = {}
    for m in mails:
        by_account.setdefault(m.account, []).append(m)

    total_ok = 0
    total_failed: list[str] = []

    for addr, acc_mails in by_account.items():
        acc = accounts_map.get(addr)
        if not acc:
            total_failed.extend(m.uid for m in acc_mails)
            continue
        try:
            ok, failed = mark_as_read(
                provider_name=acc["provider"],
                address=addr,
                password=acc["password"],
                uids=[m.uid for m in acc_mails],
            )
            total_ok += ok
            total_failed.extend(failed)
        except Exception as e:
            total_failed.extend(m.uid for m in acc_mails)
            st.session_state.setdefault("mark_errors", []).append(str(e))

    return total_ok, total_failed


# ── 抓取 + 分类 + 简报 ────────────────────────────────────────────────────────

def _run_fetch(hours: int) -> None:
    """抓取所有账号并分类；同时生成简报；若开关开启则自动标已读。"""
    try:
        accounts = load_accounts()
        llm = load_llm_config()
    except (FileNotFoundError, ValueError) as e:
        st.session_state.fetch_error = str(e)
        st.session_state.results = None
        return

    st.session_state.fetch_error = None
    st.session_state.account_warnings = {}
    st.session_state.brief = ""
    st.session_state.mark_errors = []
    st.session_state.auto_mark_result = None
    st.session_state.mark_confirm = False

    all_mails: list[MailItem] = []
    fetch_errors: list[str] = []
    accounts_map = {acc["address"]: acc for acc in accounts}

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
        progress.progress(0.80, text="正在调用 LLM 分类…")
        classified = classify_mails(
            mails=all_mails,
            api_key=llm["api_key"],
            base_url=llm["base_url"],
            model=llm["model"],
        )
        st.session_state.results = classified

        # 对「需要处理（非回复）」组生成行动简报（独立 LLM 调用）
        action_mails = [m for m in classified if m.category == "需要处理（非回复）"]
        if action_mails:
            progress.progress(0.92, text="正在生成行动简报…")
            try:
                st.session_state.brief = generate_brief(
                    mails=action_mails,
                    api_key=llm["api_key"],
                    base_url=llm["base_url"],
                    model=llm["model"],
                )
            except Exception as e:
                st.session_state.brief = f"（简报生成失败：{e}）"

        # 若设置了自动标已读，对「广告/可忽略」组执行
        settings = load_settings()
        if settings.get("auto_mark_read", False):
            ad_mails = [m for m in classified if m.category == "广告/可忽略"]
            if ad_mails:
                progress.progress(0.97, text="正在自动标记广告邮件为已读…")
                try:
                    ok, failed = _do_mark_as_read(ad_mails, accounts_map)
                    st.session_state.auto_mark_result = (ok, failed)
                except Exception as e:
                    st.session_state.mark_errors.append(str(e))
    else:
        st.session_state.results = []

    st.session_state.fetch_hours = hours
    st.session_state.fetch_time = datetime.now().strftime("%H:%M")
    progress.empty()


# ── 卡片渲染 ──────────────────────────────────────────────────────────────────

def _render_reply_item(m: ClassifiedMail) -> None:
    """需要回复：标题链接 + 占位回复按钮（v0.5 实现前为禁用）。"""
    link = _mail_link(m)
    col_info, col_btn = st.columns([8, 1])
    with col_info:
        title = f"[{m.subject}]({link})" if link else m.subject
        st.markdown(f"**{title}**")
        st.caption(f"🕐 {m.date.strftime('%m-%d %H:%M')}　📬 {m.sender}")
        st.text(m.reason)
    with col_btn:
        st.button(
            "回复",
            key=f"reply_{m.uid}",
            disabled=True,
            help="草稿生成功能将在 v0.5 中实现",
            use_container_width=True,
        )
        if link:
            st.link_button("打开", link, use_container_width=True)
    st.divider()


def _render_action_item(m: ClassifiedMail) -> None:
    """需要处理（非回复）：带本地「已解决」标记按钮。"""
    resolved: set = st.session_state.setdefault("resolved_uids", set())
    is_done = m.uid in resolved

    link = _mail_link(m)
    col_info, col_btn = st.columns([8, 1])
    with col_info:
        title = f"[{m.subject}]({link})" if link else m.subject
        prefix = "~~" if is_done else ""
        suffix = "~~" if is_done else ""
        st.markdown(f"{prefix}**{title}**{suffix}")
        st.caption(f"🕐 {m.date.strftime('%m-%d %H:%M')}　📬 {m.sender}")
        if not is_done:
            st.text(m.reason)
    with col_btn:
        if is_done:
            if st.button("撤销", key=f"undo_{m.uid}", use_container_width=True):
                resolved.discard(m.uid)
                st.rerun()
        else:
            if st.button("✓ 已解决", key=f"done_{m.uid}", use_container_width=True):
                resolved.add(m.uid)
                st.rerun()
        if link:
            st.link_button("打开", link, use_container_width=True)
    st.divider()


def _render_info_item(m: ClassifiedMail) -> None:
    """记录/公告：纯展示，无操作。"""
    link = _mail_link(m)
    col_info, col_btn = st.columns([9, 1])
    with col_info:
        title = f"[{m.subject}]({link})" if link else m.subject
        st.markdown(f"**{title}**")
        st.caption(f"🕐 {m.date.strftime('%m-%d %H:%M')}　📬 {m.sender}")
    with col_btn:
        if link:
            st.link_button("打开", link, use_container_width=True)
    st.divider()


def _render_ad_item(m: ClassifiedMail) -> None:
    """广告/可忽略：紧凑展示，勾选操作在外层处理。"""
    link = _mail_link(m)
    title = f"[{m.subject}]({link})" if link else m.subject
    st.markdown(f"**{title}**")
    st.caption(f"🕐 {m.date.strftime('%m-%d %H:%M')}　📬 {m.sender}")
    st.divider()


# ── 摘要视图 ──────────────────────────────────────────────────────────────────

def summary_page() -> None:
    st.title("📬 分流视图")

    col_sel, col_btn, _ = st.columns([2, 1, 6])
    with col_sel:
        hours = st.selectbox(
            "时间范围",
            [24, 48, 72],
            format_func=lambda h: f"最近 {h} 小时",
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("刷新", type="primary", use_container_width=True):
            _run_fetch(hours)
            st.rerun()

    if "results" not in st.session_state:
        st.info("点击「刷新」开始抓取并分流邮件。")
        return

    if st.session_state.get("fetch_error"):
        st.error(st.session_state.fetch_error)

    results: list[ClassifiedMail] | None = st.session_state.get("results")
    if results is None:
        return

    fetch_time = st.session_state.get("fetch_time", "")
    fetch_hours = st.session_state.get("fetch_hours", hours)
    if fetch_time:
        st.caption(f"最后更新：{fetch_time}　覆盖最近 {fetch_hours} 小时")

    # ── 截断警告横幅 ─────────────────────────────────────────────────────────
    for account, wlist in st.session_state.get("account_warnings", {}).items():
        for w in wlist:
            st.warning(f"⚠️ **{account}**：{w}")

    if not results:
        st.success("该时间段内无新邮件。")
        return

    # 分组
    groups: dict[str, list[ClassifiedMail]] = {cat: [] for cat in CATEGORIES}
    for m in results:
        groups.setdefault(m.category, []).append(m)

    accounts_map = {acc["address"]: acc for acc in load_accounts()}

    # ── 需要回复 ─────────────────────────────────────────────────────────────
    reply_items = groups["需要回复"]
    with st.expander(
        f"✉️ **需要回复**（{len(reply_items)} 封）",
        expanded=len(reply_items) > 0,
    ):
        if not reply_items:
            st.caption("（无）")
        else:
            for m in reply_items:
                _render_reply_item(m)

    # ── 需要处理（非回复） ────────────────────────────────────────────────────
    action_items = groups["需要处理（非回复）"]
    with st.expander(
        f"🔔 **需要处理（非回复）**（{len(action_items)} 封）",
        expanded=len(action_items) > 0,
    ):
        if not action_items:
            st.caption("（无）")
        else:
            brief = st.session_state.get("brief", "")
            if brief:
                st.info(f"📋 **行动简报**\n\n{brief}")
            for m in action_items:
                _render_action_item(m)

    # ── 记录/公告 ─────────────────────────────────────────────────────────────
    info_items = groups["记录/公告"]
    with st.expander(
        f"📄 **记录/公告**（{len(info_items)} 封）",
        expanded=False,
    ):
        if not info_items:
            st.caption("（无）")
        else:
            for m in info_items:
                _render_info_item(m)

    # ── 广告/可忽略 ───────────────────────────────────────────────────────────
    ad_items = groups["广告/可忽略"]
    settings = load_settings()
    auto_mark = settings.get("auto_mark_read", False)

    with st.expander(
        f"🗑️ **广告/可忽略**（{len(ad_items)} 封）",
        expanded=False,
    ):
        if not ad_items:
            st.caption("（无）")
        else:
            # 自动标已读的执行结果
            auto_result = st.session_state.get("auto_mark_result")
            if auto_result is not None:
                ok, failed = auto_result
                if failed:
                    st.warning(f"已自动标记 {ok} 封为已读，{len(failed)} 封失败。")
                else:
                    st.success(f"✅ 已自动标记 {ok} 封广告邮件为已读。")

            mark_errors = st.session_state.get("mark_errors", [])
            for err in mark_errors:
                st.error(f"标记失败：{err}")

            if not auto_mark:
                _render_mark_confirm_ui(ad_items, accounts_map)

            for m in ad_items:
                _render_ad_item(m)


def _render_mark_confirm_ui(
    ad_items: list[ClassifiedMail],
    accounts_map: dict[str, dict],
) -> None:
    """手动批量标记已读的两步确认 UI。"""
    if not st.session_state.get("mark_confirm", False):
        if st.button(
            f"批量标记已读（{len(ad_items)} 封）",
            key="mark_read_btn",
        ):
            st.session_state.mark_confirm = True
            st.rerun()
    else:
        st.warning(f"确认将这 **{len(ad_items)} 封**广告邮件标记为已读？此操作会修改邮箱状态。")
        col_cancel, col_ok, _ = st.columns([1, 1, 5])
        with col_cancel:
            if st.button("取消", key="mark_cancel"):
                st.session_state.mark_confirm = False
                st.rerun()
        with col_ok:
            if st.button("确认标记", key="mark_ok", type="primary"):
                with st.spinner("正在标记…"):
                    ok, failed = _do_mark_as_read(ad_items, accounts_map)
                st.session_state.mark_confirm = False
                if failed:
                    st.warning(f"已标记 {ok} 封，{len(failed)} 封失败。")
                else:
                    st.success(f"✅ 已将 {ok} 封广告邮件标记为已读。")
                st.rerun()


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

    # ── 应用行为 ─────────────────────────────────────────────────────────────
    st.subheader("应用行为")

    settings = load_settings()

    new_auto_mark = st.toggle(
        "广告/可忽略邮件：刷新后自动标记为已读",
        value=settings.get("auto_mark_read", False),
        help="开启后，每次刷新分流结果时，「广告/可忽略」类的邮件会自动在邮箱里标为已读，无需手动确认。",
    )

    if new_auto_mark != settings.get("auto_mark_read", False):
        settings["auto_mark_read"] = new_auto_mark
        save_settings(settings)
        state_text = "已开启" if new_auto_mark else "已关闭"
        st.success(f"设置已保存：自动标已读{state_text}。")


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
            ["📬 分流视图", "⚙️ 设置"],
            label_visibility="collapsed",
        )

    if page == "📬 分流视图":
        summary_page()
    else:
        settings_page()


if __name__ == "__main__":
    main()
