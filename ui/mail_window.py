"""邮件助手 — 原生 macOS 窗口（AppKit + WKWebView）Phase B + C（标记已读 + 持久化状态）"""

import html
import json
import threading
import urllib.parse
import objc
from Foundation import NSObject
from AppKit import (
    NSWindow,
    NSWorkspace,
    NSTitledWindowMask,
    NSClosableWindowMask,
    NSMiniaturizableWindowMask,
    NSResizableWindowMask,
    NSBackingStoreBuffered,
)
from WebKit import WKWebView, WKWebViewConfiguration

from core.mail_fetcher import fetch_recent_mails
from core.classifier import classify_mails, generate_brief
from core.mail_marker import mark_as_read
from core.storage import load_accounts, load_llm_config, load_settings, save_settings
from core.state import (
    load_state, save_state, clean_expired,
    update_unprocessed, is_marked_read,
    mark_item_processed, mark_items_processed,
    add_items_marked_read,
)

# ---------------------------------------------------------------------------
# Fake data — shown on initial launch
# ---------------------------------------------------------------------------

_FAKE_BRIEF = (
    "Anthropic 订阅付款失败 £18.00，需在 3 天内更新支付方式；"
    "域名 fercopsun.com 将于 2026-07-01 到期，需续费；"
    "GitHub Actions 配额用尽，CI 已暂停，需升级套餐。"
)

_FAKE_RESULTS = {
    "需要回复": [
        {
            "uid": "1001", "account": "chengsun2001@gmail.com",
            "subject": "Re: 展览合作意向 — 想了解更多细节", "sender": "gallery@artspace.cn",
            "date_str": "2026-06-26 09:15",
            "snippet": "您好，我们看了您的作品集非常感兴趣，能否方便时间通话详聊合作方式？",
            "reason": "发件人明确期待回信，商量合作事宜",
            "message_id": "<abc123@artspace.cn>", "resolved": False,
        },
    ],
    "需要处理（非回复）": [
        {
            "uid": "1003", "account": "chengsun2001@gmail.com",
            "subject": "Your Anthropic payment failed — action required",
            "sender": "billing@anthropic.com",
            "date_str": "2026-06-26 07:00",
            "snippet": "We were unable to charge £18.00. Please update your payment method within 3 days.",
            "reason": "付款失败，需在3天内更新支付方式",
            "message_id": "<bill001@anthropic.com>", "resolved": False,
        },
    ],
    "记录/公告": [
        {
            "uid": "1006", "account": "chengsun2001@gmail.com",
            "subject": "您的 iCloud 订阅已成功续费", "sender": "no_reply@email.apple.com",
            "date_str": "2026-06-26 06:00",
            "snippet": "感谢您的订阅！iCloud+ 50GB 已于 2026-06-26 成功续费，金额 ¥6.00。",
            "reason": "iCloud成功扣款的收据，纯记录",
            "message_id": "<apple001@apple.com>", "resolved": False,
        },
    ],
    "广告/可忽略": [
        {
            "uid": "1008", "account": "chengsun2001@gmail.com",
            "subject": "🔥 618 大促最后3天！设计素材全场5折", "sender": "promo@iconfont.cn",
            "date_str": "2026-06-25 08:00",
            "snippet": "618年中大促进行中，精选字体、图标包、UI组件全场5折起，限时48小时。",
            "reason": "营销推送，限时优惠活动",
            "message_id": "<promo001@iconfont.cn>", "resolved": False,
        },
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _he(s: str) -> str:
    return html.escape(str(s), quote=True)


def _mail_link(item: dict) -> str:
    account    = item.get("account", "")
    message_id = item.get("message_id", "")
    if "@gmail.com" in account and message_id:
        q = urllib.parse.quote(f"rfc822msgid:{message_id}")
        return f"https://mail.google.com/mail/u/0/#search/{q}"
    if "@qq.com" in account:
        return "https://mail.qq.com"
    if "@163.com" in account or "@126.com" in account:
        return "https://mail.163.com"
    return "#"


def _classified_to_state_item(m) -> dict:
    """ClassifiedMail → dict for local state storage (includes date_iso for sorting)."""
    date_str = m.date.strftime("%Y-%m-%d %H:%M") if hasattr(m.date, "strftime") else str(m.date)
    date_iso = m.date.isoformat() if hasattr(m.date, "isoformat") else str(m.date)
    return {
        "uid": str(m.uid), "account": m.account,
        "subject": m.subject, "sender": m.sender,
        "date_str": date_str, "date_iso": date_iso,
        "snippet": m.snippet, "reason": m.reason,
        "message_id": getattr(m, "message_id", ""),
        "category": m.category,
    }


class _BriefMail:
    """Lightweight adapter so generate_brief can consume state dict items."""
    def __init__(self, d: dict):
        from datetime import datetime
        self.subject = d.get("subject", "")
        self.sender  = d.get("sender", "")
        self.snippet = d.get("snippet", "")
        try:
            self.date = datetime.strptime(d.get("date_str", ""), "%Y-%m-%d %H:%M")
        except Exception:
            from datetime import datetime as dt_cls
            self.date = dt_cls.now()


def _sort_items(items: list[dict]) -> list[dict]:
    """Unresolved items first (date desc), resolved items after (date desc)."""
    unresolved = sorted(
        [i for i in items if not i.get("resolved")],
        key=lambda x: x.get("date_iso") or x.get("date_str") or "",
        reverse=True,
    )
    resolved = sorted(
        [i for i in items if i.get("resolved")],
        key=lambda x: x.get("processed_at") or x.get("date_iso") or "",
        reverse=True,
    )
    return unresolved + resolved


# ---------------------------------------------------------------------------
# Main window class
# ---------------------------------------------------------------------------

class MailWindow(NSObject):

    @objc.python_method
    def init(self):
        self = objc.super(MailWindow, self).init()
        if self is None:
            return None
        self._window   = None
        self._webview  = None
        self._refreshing = False
        self._refresh_results  = {}
        self._refresh_brief    = ""
        self._refresh_warnings = []
        self._refresh_errors   = []
        self._accounts         = []
        self._uid_to_account   = {}
        self._settings         = {}
        self._state            = {}
        return self

    @objc.python_method
    def show(self):
        self._settings = load_settings()
        self._build_window()
        self._render_main()
        self._window.makeKeyAndOrderFront_(None)
        self._window.center()

    # ------------------------------------------------------------------
    # Window / WebView setup
    # ------------------------------------------------------------------

    @objc.python_method
    def _build_window(self):
        style = (
            NSTitledWindowMask | NSClosableWindowMask
            | NSMiniaturizableWindowMask | NSResizableWindowMask
        )
        from Foundation import NSMakeRect
        rect = NSMakeRect(0, 0, 960, 720)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        win.setTitle_("邮件助手")
        win.setMinSize_((760, 500))

        cfg = WKWebViewConfiguration.alloc().init()
        wv  = WKWebView.alloc().initWithFrame_configuration_(rect, cfg)
        wv.setAutoresizingMask_(18)
        wv.setNavigationDelegate_(self)
        wv.setUIDelegate_(self)

        win.contentView().addSubview_(wv)
        self._window  = win
        self._webview = wv

    @objc.python_method
    def _load_html(self, html_str: str):
        self._webview.loadHTMLString_baseURL_(html_str, None)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @objc.python_method
    def _render_main(self):
        self._render_page(_FAKE_RESULTS, _FAKE_BRIEF)

    @objc.python_method
    def _render_page(self, results: dict, brief: str,
                     warnings: list = None, errors: list = None):
        notices_html  = self._build_notices(warnings or [], errors or [])
        sidebar_html  = self._render_sidebar(results)
        panels_html   = self._render_panels(results, brief)
        settings_html = self._render_settings_panel()
        page = self._build_page(sidebar_html, panels_html, settings_html, notices_html)
        self._load_html(page)

    @objc.python_method
    def _build_page(self, sidebar_html: str, panels_html: str,
                    settings_html: str = "", notices_html: str = "") -> str:
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>邮件助手</title>
<style>
{self._build_page_css()}
</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-logo">
      <span class="logo-icon">📬</span>
      <span class="logo-text">邮件助手</span>
    </div>
    <nav class="sidebar-nav">
      {sidebar_html}
    </nav>
    <div class="sidebar-sep"></div>
    <div class="sidebar-footer">
      <button class="nav-settings" onclick="switchTab('settings')">
        <span>⚙️</span><span>设置</span>
      </button>
    </div>
  </aside>
  <div class="content-area">
    <div class="content-header">
      <span class="content-title" id="content-title">需要回复</span>
      <button id="btn-refresh" class="btn btn-refresh"
              onclick="xdNav('mail://refresh')">刷新收件箱</button>
    </div>
    <div id="progress-area">
      <span class="progress-dot">●</span>
      <span id="progress-msg"></span>
    </div>
    {notices_html}
    <div class="content-scroll">
      {panels_html}
      {settings_html}
    </div>
  </div>
</div>
{self._build_shared_js()}
</body>
</html>"""

    @objc.python_method
    def _build_page_css(self) -> str:
        return """
:root {
  --black: #111;
  --bg: #FBF3E3;
  --border: 2.5px solid #111;
  --shadow: 4px 4px 0 #111;
  --transition: transform 150ms ease, box-shadow 150ms ease;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
  background: var(--bg); color: var(--black);
  font-size: 14px; line-height: 1.5;
  height: 100vh; overflow: hidden;
}

.layout {
  display: flex; height: 100vh; overflow: hidden;
  border: 3px solid #111; border-radius: 20px;
}

.sidebar {
  width: 204px; flex-shrink: 0;
  border-right: 2.5px solid #111;
  display: flex; flex-direction: column;
  background: var(--bg); overflow-y: auto;
}
.sidebar-logo {
  display: flex; align-items: center; gap: 9px;
  padding: 16px 14px; border-bottom: 2.5px solid #111; flex-shrink: 0;
}
.logo-icon { font-size: 20px; }
.logo-text { font-size: 15px; font-weight: 900; letter-spacing: -0.5px; }

.sidebar-nav { display: flex; flex-direction: column; padding: 12px 10px; gap: 10px; flex: 1; }

.nav-item {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 10px 12px; border: 2.5px solid #111; border-radius: 12px;
  box-shadow: none; cursor: pointer; font-size: 13px; font-weight: 700;
  text-align: left; color: #111; opacity: 0.58;
  transition: var(--transition), opacity 0.12s;
}
.nav-item.active { opacity: 1; box-shadow: 4px 4px 0 #111; }
.nav-item:hover:not(.active) { opacity: 0.88; transform: translate(-2px,-2px); box-shadow: 6px 6px 0 #111; }
.nav-item:active { transform: translate(1px,1px); box-shadow: 2px 2px 0 #111; opacity: 1; }
.nav-icon  { font-size: 15px; flex-shrink: 0; }
.nav-label { flex: 1; }
.nav-badge {
  width: 24px; height: 24px; border-radius: 50%;
  border: 2px solid #111; background: #fff;
  font-size: 11px; font-weight: 800;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}

.sidebar-sep { height: 2px; background: #111; margin: 2px 10px 6px; opacity: 0.15; flex-shrink: 0; }
.sidebar-footer { padding: 0 10px 14px; flex-shrink: 0; }
.nav-settings {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 9px 12px;
  background: transparent; border: none; border-radius: 8px;
  cursor: pointer; font-size: 13px; font-weight: 600; color: #777;
  transition: background 0.12s, color 0.12s;
}
.nav-settings:hover { background: rgba(0,0,0,0.07); color: #111; }

.content-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
.content-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; border-bottom: 2.5px solid #111; background: var(--bg); flex-shrink: 0;
}
.content-title { font-size: 16px; font-weight: 800; letter-spacing: -0.3px; }

#progress-area {
  display: none; padding: 9px 20px; align-items: center; gap: 10px;
  background: #FFD93D; border-bottom: 2.5px solid #111;
  font-size: 13px; font-weight: 700; color: #111; flex-shrink: 0;
}
#progress-area.active { display: flex; }
.progress-dot { animation: pulse 0.9s infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.15; } }

#notices-area { padding: 12px 14px 0; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
.notice { padding: 10px 14px; border: 2px solid #111; border-radius: 10px; font-size: 13px; font-weight: 600; box-shadow: 3px 3px 0 #111; line-height: 1.5; }
.notice-warn  { background: #FFF8D0; color: #5a4800; }
.notice-error { background: #FFE8E8; color: #7a0000; }

.content-scroll { flex: 1; overflow-y: auto; padding: 14px 14px 32px; }
.panel { display: none; }
.panel.active { display: block; }

.btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 14px; border: 2px solid #111; border-radius: 10px;
  box-shadow: 3px 3px 0 #111; background: var(--bg); color: #111;
  font-size: 13px; font-weight: 700; cursor: pointer;
  transition: var(--transition); white-space: nowrap;
}
.btn:hover:not(:disabled) { transform: translate(-2px,-2px) rotate(-1deg); box-shadow: 5px 5px 0 #111; }
.btn:active:not(:disabled) { transform: translate(1px,1px) rotate(0deg); box-shadow: 1px 1px 0 #111; }
.btn:disabled { opacity: 0.38; cursor: not-allowed; box-shadow: none; }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.btn-refresh   { background: #111; color: #FBF3E3; }
.btn-reply     { background: #FF6FA5; }
.btn-resolve   { background: #FFD93D; }
.btn-resolved  { background: #B8EDBE; }
.btn-mark-read { background: #7CE38B; }
.btn-danger    { background: #FF6FA5; }

.card-subject-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.card-subject-row .card-subject { margin-bottom: 0; flex: 1; min-width: 0; }
.star-btn {
  flex-shrink: 0; width: 20px; height: 20px;
  border: 1.5px solid transparent; border-radius: 5px;
  background: transparent; cursor: pointer; font-size: 13px; color: #ccc;
  display: flex; align-items: center; justify-content: center;
  padding: 0; line-height: 1;
  transition: color 0.12s, background 0.12s, border-color 0.12s, box-shadow 0.12s;
}
.star-btn:hover { color: #f5a623; border-color: #111; background: #fff8d0; }
.star-btn.starred { color: #a06000; background: #FFD93D; border: 1.5px solid #111; box-shadow: 2px 2px 0 #111; }

.brief-banner {
  padding: 12px 16px; background: #FFF8D0;
  border: 2.5px solid #111; border-radius: 12px;
  box-shadow: 3px 3px 0 #111; font-size: 13px; line-height: 1.6;
  color: #5a4800; margin-bottom: 14px;
}
.brief-banner.empty { color: #9a8050; font-style: italic; }
.brief-label {
  font-weight: 800; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 4px; color: #8a6800;
}

.batch-bar {
  padding: 10px 14px; border: 2.5px solid #111; border-radius: 12px;
  box-shadow: 3px 3px 0 #111;
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px;
}
.batch-bar-ad   { background: #C8F1CC; }
.batch-bar-info { background: #C8E8FF; }

.card {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 14px 16px; background: #fff;
  border: 2.5px solid #111; border-radius: 14px;
  box-shadow: 4px 4px 0 #111; margin-bottom: 12px;
  transition: var(--transition);
}
.card:last-child { margin-bottom: 0; }
.card:hover { transform: translate(-2px,-2px); box-shadow: 6px 6px 0 #111; }
.card:active { transform: translate(1px,1px); box-shadow: 2px 2px 0 #111; }
.card.resolved {
  opacity: 0.38; background: #f5f5f5;
  transform: none !important; box-shadow: 4px 4px 0 #aaa !important;
  border-color: #aaa !important;
}
.card.resolved:hover { transform: none !important; }

.card-left { flex: 1; min-width: 0; }
.card-subject {
  font-weight: 700; font-size: 14px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.card-subject a { color: #111; text-decoration: none; }
.card-subject a:hover { text-decoration: underline; }
.card-meta    { font-size: 12px; color: #666; margin-bottom: 5px; }
.card-snippet {
  font-size: 13px; color: #444;
  display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden;
}
.card-reason { margin-top: 5px; font-size: 11.5px; color: #888; font-style: italic; }
.card-resolved-badge {
  margin-top: 6px; display: inline-block;
  padding: 2px 8px; background: #B8EDBE;
  border: 1.5px solid #4a8a4a; border-radius: 6px;
  font-size: 11px; font-weight: 700; color: #1a4a1a;
}
.card-actions { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; align-self: center; }

.empty-state { padding: 36px 18px; text-align: center; font-size: 13px; color: #aaa; font-style: italic; display: none; }
.empty-state.visible { display: block; }

.settings-section {
  background: #fff; border: 2.5px solid #111; border-radius: 14px;
  box-shadow: 4px 4px 0 #111; padding: 20px; margin-bottom: 16px;
}
.settings-section-title {
  font-size: 13px; font-weight: 800; letter-spacing: 0.4px;
  text-transform: uppercase; color: #666; margin-bottom: 14px;
  padding-bottom: 10px; border-bottom: 1.5px solid #eee;
}
.setting-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 0; border-bottom: 1px solid #f2f2f2;
}
.setting-row:last-child { border-bottom: none; padding-bottom: 0; }
.setting-label { font-size: 13px; font-weight: 600; color: #222; }
.setting-desc  { font-size: 11.5px; color: #888; margin-top: 2px; }
.toggle-btn {
  padding: 5px 14px; border-radius: 20px; border: 2px solid #111;
  font-size: 12px; font-weight: 700; cursor: pointer;
  box-shadow: 2px 2px 0 #111; transition: var(--transition); flex-shrink: 0;
}
.toggle-btn.off { background: #eee; color: #666; }
.toggle-btn.on  { background: #7CE38B; color: #1a4a1a; }
.toggle-btn:hover  { transform: translate(-1px,-1px); box-shadow: 3px 3px 0 #111; }
.toggle-btn:active { transform: translate(1px,1px); box-shadow: 1px 1px 0 #111; }

#toast {
  position: fixed; bottom: 28px; left: 50%;
  transform: translateX(-50%) translateY(20px);
  background: #111; color: #FBF3E3;
  padding: 9px 20px; border: 2px solid #111; border-radius: 10px;
  box-shadow: 3px 3px 0 #111; font-size: 13px; font-weight: 600;
  opacity: 0; pointer-events: none;
  transition: opacity 0.2s, transform 0.2s; z-index: 999;
}
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

#confirm-overlay {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.38); z-index: 500;
  align-items: center; justify-content: center;
}
#confirm-overlay.show { display: flex; }
.confirm-box {
  background: var(--bg); border: 2.5px solid #111;
  box-shadow: 6px 6px 0 #111; border-radius: 16px;
  padding: 24px 28px; max-width: 360px; width: 90%;
}
.confirm-msg  { font-size: 14px; font-weight: 600; margin-bottom: 18px; line-height: 1.5; }
.confirm-btns { display: flex; gap: 10px; justify-content: flex-end; }
"""

    @objc.python_method
    def _build_shared_js(self) -> str:
        return """<script>
function xdNav(url) { window.location.href = url; }

function showProgress(msg) {
  var pa = document.getElementById('progress-area');
  var pm = document.getElementById('progress-msg');
  if (pa) pa.classList.add('active');
  if (pm) pm.textContent = msg;
  var btn = document.getElementById('btn-refresh');
  if (btn) { btn.disabled = true; btn.textContent = '刷新中…'; }
}

function showToast(msg) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._tid);
  t._tid = setTimeout(function(){ t.classList.remove('show'); }, 2800);
}

function setToggleState(id, active) {
  var btn = document.getElementById(id);
  if (!btn) return;
  btn.textContent = active ? '已开启' : '已关闭';
  btn.className = 'toggle-btn ' + (active ? 'on' : 'off');
}

var _confirmCb = null;
function xdConfirm(msg, onConfirm) {
  _confirmCb = onConfirm;
  document.getElementById('confirm-msg').textContent = msg;
  document.getElementById('confirm-overlay').classList.add('show');
}
function _confirmOk() {
  document.getElementById('confirm-overlay').classList.remove('show');
  if (_confirmCb) { _confirmCb(); _confirmCb = null; }
}
function _confirmCancel() {
  document.getElementById('confirm-overlay').classList.remove('show');
  _confirmCb = null;
}

var _TAB_LABELS = {
  reply: '需要回复', action: '需要处理（非回复）',
  info: '记录 / 公告', ad: '广告 / 可忽略', settings: '设置'
};
var _CATEGORY_TABS = ['reply', 'action', 'info', 'ad'];
var _currentTab = 'reply';

function switchTab(id) {
  if (id === _currentTab) return;
  document.getElementById('panel-' + _currentTab).classList.remove('active');
  if (_CATEGORY_TABS.indexOf(_currentTab) !== -1)
    document.getElementById('nav-' + _currentTab).classList.remove('active');
  _currentTab = id;
  document.getElementById('panel-' + id).classList.add('active');
  if (_CATEGORY_TABS.indexOf(id) !== -1)
    document.getElementById('nav-' + id).classList.add('active');
  document.getElementById('content-title').textContent = _TAB_LABELS[id] || id;
}

var _starredTimes = {};
function toggleStar(uid) {
  var btn = document.getElementById('star-' + uid);
  if (_starredTimes[uid]) {
    delete _starredTimes[uid]; btn.textContent = '☆'; btn.classList.remove('starred');
  } else {
    _starredTimes[uid] = Date.now(); btn.textContent = '★'; btn.classList.add('starred');
  }
  _reorderReplyCards();
}
function _reorderReplyCards() {
  var body = document.getElementById('group-reply-body');
  if (!body) return;
  var cards = Array.from(body.querySelectorAll('.card[data-uid]'));
  var starred   = cards.filter(function(c){ return !!_starredTimes[c.dataset.uid]; })
                       .sort(function(a,b){ return _starredTimes[a.dataset.uid] - _starredTimes[b.dataset.uid]; });
  var unstarred = cards.filter(function(c){ return !_starredTimes[c.dataset.uid]; });
  var emptyDiv  = body.querySelector('.empty-state');
  starred.concat(unstarred).forEach(function(c){ body.insertBefore(c, emptyDiv || null); });
}

var resolvedUids = {};
function markResolved(uid, account, groupId) {
  resolvedUids[uid] = true;
  var card = document.getElementById('card-' + uid);
  if (card) card.classList.add('resolved');
  var btn = document.getElementById('btn-resolve-' + uid);
  if (btn) {
    btn.textContent = '↩ 撤销';
    btn.className = 'btn btn-sm btn-resolved';
    btn.onclick = function(){ undoResolved(uid, account, groupId); };
  }
  _updateEmpty(groupId);
  xdNav('mail://resolve?uid=' + encodeURIComponent(uid)
        + '&account=' + encodeURIComponent(account));
}
function undoResolved(uid, account, groupId) {
  delete resolvedUids[uid];
  var card = document.getElementById('card-' + uid);
  if (card) card.classList.remove('resolved');
  var btn = document.getElementById('btn-resolve-' + uid);
  if (btn) {
    btn.textContent = '✓ 已解决';
    btn.className = 'btn btn-sm btn-resolve';
    btn.onclick = function(){ markResolved(uid, account, groupId); };
  }
  _updateEmpty(groupId);
}
function _updateEmpty(groupId) {
  var body = document.getElementById(groupId + '-body');
  if (!body) return;
  var cards = body.querySelectorAll('.card');
  var empty = body.querySelector('.empty-state');
  var allResolved = Array.from(cards).every(function(c){ return c.classList.contains('resolved'); });
  if (empty) empty.classList.toggle('visible', cards.length === 0 || allResolved);
}

function markAllAdRead(count) {
  xdConfirm('将 ' + count + ' 封广告邮件标记为已读？', function(){
    var body = document.getElementById('group-ad-body');
    if (body) body.querySelectorAll('.card:not(.resolved)').forEach(function(c){ c.classList.add('resolved'); });
    _updateEmpty('group-ad');
    showToast('正在标记 ' + count + ' 封广告邮件为已读…');
    xdNav('mail://mark_ad_read');
  });
}

function markAllInfoRead(count) {
  xdConfirm('将 ' + count + ' 封记录/公告邮件标记为已读？', function(){
    var body = document.getElementById('group-info-body');
    if (body) body.querySelectorAll('.card:not(.resolved)').forEach(function(c){ c.classList.add('resolved'); });
    _updateEmpty('group-info');
    showToast('正在标记 ' + count + ' 封记录/公告邮件为已读…');
    xdNav('mail://mark_info_read');
  });
}
</script>

<div id="toast"></div>
<div id="confirm-overlay">
  <div class="confirm-box">
    <div class="confirm-msg" id="confirm-msg"></div>
    <div class="confirm-btns">
      <button class="btn" onclick="_confirmCancel()">取消</button>
      <button class="btn btn-danger" onclick="_confirmOk()">确认</button>
    </div>
  </div>
</div>"""

    # ------------------------------------------------------------------
    # Notices
    # ------------------------------------------------------------------

    @objc.python_method
    def _build_notices(self, warnings: list, errors: list) -> str:
        if not warnings and not errors:
            return ""
        parts = []
        for w in warnings:
            parts.append(f'<div class="notice notice-warn">⚠️ {_he(w)}</div>')
        for addr, err in errors:
            parts.append(
                f'<div class="notice notice-error">'
                f'❌ <strong>{_he(addr)}</strong>：{_he(err)}</div>'
            )
        return f'<div id="notices-area">{"".join(parts)}</div>'

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    @objc.python_method
    def _render_sidebar(self, results: dict) -> str:
        def _unresolved(cat):
            return sum(1 for i in results.get(cat, []) if not i.get("resolved"))

        def _item(tab_id, icon, label, color, badge, active=""):
            return (
                f'<button class="nav-item{active}" id="nav-{tab_id}" '
                f'onclick="switchTab(\'{tab_id}\')" style="background:{color}">'
                f'<span class="nav-icon">{icon}</span>'
                f'<span class="nav-label">{label}</span>'
                f'<span class="nav-badge" id="badge-{tab_id}">{badge}</span>'
                f'</button>'
            )

        return "\n      ".join([
            _item("reply",  "💬", "需要回复",     "#FF6FA5", _unresolved("需要回复"), " active"),
            _item("action", "⚡", "需要处理",      "#FFD93D", _unresolved("需要处理（非回复）")),
            _item("info",   "📋", "记录 / 公告",   "#5BC8FF", _unresolved("记录/公告")),
            _item("ad",     "🗑", "广告 / 可忽略", "#7CE38B", _unresolved("广告/可忽略")),
        ])

    # ------------------------------------------------------------------
    # Settings panel
    # ------------------------------------------------------------------

    @objc.python_method
    def _render_settings_panel(self) -> str:
        s = self._settings
        ad_on   = s.get("auto_mark_read_ad",   False)
        info_on = s.get("auto_mark_read_info",  False)

        def _toggle(btn_id, key, active):
            cls  = "toggle-btn on" if active else "toggle-btn off"
            text = "已开启" if active else "已关闭"
            return (
                f'<button id="{btn_id}" class="{cls}" '
                f'onclick="xdNav(\'mail://toggle_setting/{key}\')">'
                f'{text}</button>'
            )

        return f"""<div id="panel-settings" class="panel">
  <div class="settings-section">
    <div class="settings-section-title">刷新后自动标记已读</div>
    <div class="setting-row">
      <div>
        <div class="setting-label">广告 / 可忽略</div>
        <div class="setting-desc">每次刷新完成后，自动将该分类的邮件全部标记为已读</div>
      </div>
      {_toggle("toggle-auto-mark-ad", "auto_mark_read_ad", ad_on)}
    </div>
    <div class="setting-row">
      <div>
        <div class="setting-label">记录 / 公告</div>
        <div class="setting-desc">每次刷新完成后，自动将该分类的邮件全部标记为已读</div>
      </div>
      {_toggle("toggle-auto-mark-info", "auto_mark_read_info", info_on)}
    </div>
  </div>
</div>"""

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------

    @objc.python_method
    def _render_panels(self, results: dict, brief: str) -> str:
        reply_items  = _sort_items(results.get("需要回复", []))
        action_items = _sort_items(results.get("需要处理（非回复）", []))
        info_items   = _sort_items(results.get("记录/公告", []))
        ad_items     = _sort_items(results.get("广告/可忽略", []))

        # ── Reply panel ──
        reply_cards = "".join(self._build_reply_card(m) for m in reply_items)
        reply_panel = self._wrap_panel("reply", "active", "", "group-reply", reply_cards)

        # ── Action panel — brief always shown ──
        unresolved_action = [i for i in action_items if not i.get("resolved")]
        if unresolved_action and brief:
            action_top = (
                f'<div class="brief-banner">'
                f'<div class="brief-label">行动简报</div>'
                f'{_he(brief)}</div>'
            )
        else:
            empty_msg = "暂无需要处理的事项" if not unresolved_action else "行动简报生成中…"
            extra_cls = " empty" if not unresolved_action else ""
            action_top = (
                f'<div class="brief-banner{extra_cls}">'
                f'<div class="brief-label">行动简报</div>'
                f'{empty_msg}</div>'
            )
        action_cards = "".join(self._build_action_card(m) for m in action_items)
        action_panel = self._wrap_panel("action", "", action_top, "group-action", action_cards)

        # ── Info panel ──
        unresolved_info = [i for i in info_items if not i.get("resolved")]
        info_top   = self._build_info_batch_bar(len(unresolved_info)) if unresolved_info else ""
        info_cards = "".join(self._build_info_card(m) for m in info_items)
        info_panel = self._wrap_panel("info", "", info_top, "group-info", info_cards)

        # ── Ad panel ──
        unresolved_ad = [i for i in ad_items if not i.get("resolved")]
        ad_top   = self._build_ad_batch_bar(len(unresolved_ad)) if unresolved_ad else ""
        ad_cards = "".join(self._build_ad_card(m) for m in ad_items)
        ad_panel = self._wrap_panel("ad", "", ad_top, "group-ad", ad_cards)

        return "\n".join([reply_panel, action_panel, info_panel, ad_panel])

    @objc.python_method
    def _wrap_panel(self, tab_id: str, extra_cls: str, top_html: str,
                    group_id: str, cards_html: str) -> str:
        cls = f"panel {extra_cls}".strip()
        if cards_html:
            body = cards_html + '\n<div class="empty-state">这一类暂无邮件</div>'
        else:
            body = '<div class="empty-state visible">这一类暂无邮件</div>'
        return (
            f'<div id="panel-{tab_id}" class="{cls}">'
            f'{top_html}'
            f'<div id="{group_id}-body">{body}</div>'
            f'</div>'
        )

    # ------------------------------------------------------------------
    # Batch bars
    # ------------------------------------------------------------------

    @objc.python_method
    def _build_info_batch_bar(self, unresolved_count: int) -> str:
        return (
            f'<div class="batch-bar batch-bar-info">'
            f'<span style="font-size:13px;color:#0a3055;">共 <strong>{unresolved_count}</strong> 封记录/公告待处理</span>'
            f'<button class="btn btn-mark-read" onclick="markAllInfoRead({unresolved_count})">批量标记已读</button>'
            f'</div>'
        )

    @objc.python_method
    def _build_ad_batch_bar(self, unresolved_count: int) -> str:
        return (
            f'<div class="batch-bar batch-bar-ad">'
            f'<span style="font-size:13px;color:#1a4a1a;">共 <strong>{unresolved_count}</strong> 封广告邮件</span>'
            f'<button class="btn btn-mark-read" onclick="markAllAdRead({unresolved_count})">批量标记已读</button>'
            f'</div>'
        )

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------

    @objc.python_method
    def _build_reply_card(self, item: dict) -> str:
        link = _mail_link(item)
        uid  = _he(item["uid"])
        cls  = ' resolved' if item.get("resolved") else ''
        return (
            f'<div class="card{cls}" id="card-{uid}" data-uid="{uid}">'
            f'<div class="card-left">'
            f'<div class="card-subject-row">'
            f'<button class="star-btn" id="star-{uid}" onclick="toggleStar(\'{uid}\')">☆</button>'
            f'<div class="card-subject"><a href="{_he(link)}" onclick="xdNav(\'{_he(link)}\');return false;">{_he(item["subject"])}</a></div>'
            f'</div>'
            f'<div class="card-meta">{_he(item["sender"])} · {_he(item["date_str"])} · {_he(item["account"])}</div>'
            f'<div class="card-snippet">{_he(item["snippet"])}</div>'
            f'<div class="card-reason">分类理由：{_he(item["reason"])}</div>'
            f'</div>'
            f'<div class="card-actions">'
            f'<button class="btn btn-reply btn-sm" disabled title="v0.5 实现草稿功能">回复（v0.5）</button>'
            f'<button class="btn btn-sm" onclick="xdNav(\'{_he(link)}\')">查看原信</button>'
            f'</div>'
            f'</div>'
        )

    @objc.python_method
    def _build_action_card(self, item: dict) -> str:
        link       = _mail_link(item)
        uid        = _he(item["uid"])
        resolved   = item.get("resolved", False)
        account_js = _he(json.dumps(item["account"]))  # must HTML-escape: json.dumps wraps in " which breaks onclick="..."
        cls        = ' resolved' if resolved else ''

        if resolved:
            action_ctrl = '<span class="card-resolved-badge">✓ 已处理</span>'
        else:
            action_ctrl = (
                f'<button class="btn btn-sm btn-resolve" id="btn-resolve-{uid}" '
                f'onclick="markResolved(\'{uid}\', {account_js}, \'group-action\')">✓ 已解决</button>'
            )

        return (
            f'<div class="card{cls}" id="card-{uid}">'
            f'<div class="card-left">'
            f'<div class="card-subject"><a href="{_he(link)}" onclick="xdNav(\'{_he(link)}\');return false;">{_he(item["subject"])}</a></div>'
            f'<div class="card-meta">{_he(item["sender"])} · {_he(item["date_str"])} · {_he(item["account"])}</div>'
            f'<div class="card-snippet">{_he(item["snippet"])}</div>'
            f'<div class="card-reason">分类理由：{_he(item["reason"])}</div>'
            f'</div>'
            f'<div class="card-actions">'
            f'{action_ctrl}'
            f'<button class="btn btn-sm" onclick="xdNav(\'{_he(link)}\')">查看原信</button>'
            f'</div>'
            f'</div>'
        )

    @objc.python_method
    def _build_info_card(self, item: dict) -> str:
        link     = _mail_link(item)
        uid      = _he(item["uid"])
        resolved = item.get("resolved", False)
        cls      = ' resolved' if resolved else ''
        badge    = '<div class="card-resolved-badge">✓ 已标记已读</div>' if resolved else ''
        return (
            f'<div class="card{cls}" id="card-{uid}">'
            f'<div class="card-left">'
            f'<div class="card-subject"><a href="{_he(link)}" onclick="xdNav(\'{_he(link)}\');return false;">{_he(item["subject"])}</a></div>'
            f'<div class="card-meta">{_he(item["sender"])} · {_he(item["date_str"])} · {_he(item["account"])}</div>'
            f'<div class="card-snippet">{_he(item["snippet"])}</div>'
            f'<div class="card-reason">分类理由：{_he(item["reason"])}</div>'
            f'{badge}'
            f'</div>'
            f'<div class="card-actions">'
            f'<button class="btn btn-sm" onclick="xdNav(\'{_he(link)}\')">查看原信</button>'
            f'</div>'
            f'</div>'
        )

    @objc.python_method
    def _build_ad_card(self, item: dict) -> str:
        link = _mail_link(item)
        uid  = _he(item["uid"])
        cls  = ' resolved' if item.get("resolved") else ''
        return (
            f'<div class="card{cls}" id="card-{uid}">'
            f'<div class="card-left">'
            f'<div class="card-subject"><a href="{_he(link)}" onclick="xdNav(\'{_he(link)}\');return false;">{_he(item["subject"])}</a></div>'
            f'<div class="card-meta">{_he(item["sender"])} · {_he(item["date_str"])} · {_he(item["account"])}</div>'
            f'<div class="card-snippet">{_he(item["snippet"])}</div>'
            f'<div class="card-reason">分类理由：{_he(item["reason"])}</div>'
            f'</div>'
            f'</div>'
        )

    # ------------------------------------------------------------------
    # Refresh — background pipeline
    # ------------------------------------------------------------------

    @objc.python_method
    def _start_refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        self._webview.evaluateJavaScript_completionHandler_(
            'showProgress("正在准备刷新…")', None
        )
        t = threading.Thread(target=self._bg_refresh, daemon=True)
        t.start()

    @objc.python_method
    def _bg_refresh(self):
        results  = {"需要回复": [], "需要处理（非回复）": [], "记录/公告": [], "广告/可忽略": []}
        warnings: list[str] = []
        errors:   list[tuple[str, str]] = []

        # 1. Load + clean local state
        state = load_state()
        state = clean_expired(state)

        try:
            accounts = load_accounts()
            llm_cfg  = load_llm_config()
        except Exception as e:
            self._finish_refresh(results, "", warnings, [("配置加载", str(e))], {}, state)
            return

        self._accounts = accounts
        total     = len(accounts)
        all_mails = []

        # 2. Fetch new mails (24h window)
        for i, acc in enumerate(accounts):
            addr = acc["address"]
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "setProgress:", f"正在连接 {addr} ({i + 1}/{total})…", False
            )
            try:
                mails, acc_warns = fetch_recent_mails(
                    provider_name=acc["provider"],
                    address=addr,
                    password=acc["password"],
                )
                all_mails.extend(mails)
                for w in acc_warns:
                    warnings.append(f"{addr}：{w}")
            except Exception as e:
                errors.append((addr, str(e)))

        # 3. Classify
        classified = []
        if all_mails:
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "setProgress:", "正在分类邮件…", False
            )
            try:
                classified = classify_mails(
                    mails=all_mails,
                    api_key=llm_cfg["api_key"],
                    base_url=llm_cfg["base_url"],
                    model=llm_cfg["model"],
                )
            except Exception as e:
                errors.append(("LLM 分类", str(e)))

        # 4. Separate ads vs non-ads; filter already-marked-read ads
        new_non_ad     = []
        new_ad_display = []
        for m in classified:
            d = _classified_to_state_item(m)
            if m.category == "广告/可忽略":
                if not is_marked_read(state, d):
                    new_ad_display.append({**d, "resolved": False})
            else:
                new_non_ad.append(d)

        # 5. Merge new non-ad items into persistent unprocessed
        state = update_unprocessed(state, new_non_ad)

        # 6. Build display results from state
        for entry in state["unprocessed"]:
            cat = entry.get("category", "")
            if cat in results:
                results[cat].append({**entry, "resolved": False})

        for entry in state["processed"]:
            cat = entry.get("category", "")
            if cat in results and cat != "广告/可忽略":
                results[cat].append({**entry, "resolved": True})

        results["广告/可忽略"] = new_ad_display

        # 7. Build uid→account map
        uid_map: dict[str, str] = {}
        for cat_items in results.values():
            for item in cat_items:
                uid_map[item["uid"]] = item["account"]
        self._uid_to_account = uid_map

        # 8. Generate brief from ALL unresolved action items (current + persisted)
        unresolved_action = [
            i for i in results.get("需要处理（非回复）", []) if not i.get("resolved")
        ]
        brief = ""
        if unresolved_action:
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "setProgress:", "正在生成行动简报…", False
            )
            try:
                brief = generate_brief(
                    mails=[_BriefMail(i) for i in unresolved_action],
                    api_key=llm_cfg["api_key"],
                    base_url=llm_cfg["base_url"],
                    model=llm_cfg["model"],
                )
            except Exception as e:
                errors.append(("简报生成", str(e)))

        # 9. Save state before returning to main thread
        try:
            save_state(state)
        except Exception as e:
            print(f"[state] save failed: {e}")

        self._state = state
        self._finish_refresh(results, brief, warnings, errors, uid_map, state)

    @objc.python_method
    def _finish_refresh(self, results, brief, warnings, errors, uid_map=None, state=None):
        self._refresh_results  = results
        self._refresh_brief    = brief
        self._refresh_warnings = warnings
        self._refresh_errors   = errors
        if uid_map is not None:
            self._uid_to_account = uid_map
        if state is not None:
            self._state = state
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "finishRefresh:", None, False
        )

    # ObjC-visible callbacks

    def setProgress_(self, msg):
        js = f'showProgress({json.dumps(str(msg))})'
        self._webview.evaluateJavaScript_completionHandler_(js, None)

    def finishRefresh_(self, _):
        self._refreshing = False
        self._render_page(
            self._refresh_results,
            self._refresh_brief,
            self._refresh_warnings,
            self._refresh_errors,
        )
        s = self._settings
        # Auto-mark ads (unresolved only)
        if s.get("auto_mark_read_ad"):
            items = [i for i in self._refresh_results.get("广告/可忽略", []) if not i.get("resolved")]
            if items:
                threading.Thread(
                    target=self._mark_category_read,
                    args=(items, "自动标记 {} 封广告邮件为已读"),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=self._persist_ads_marked, args=(items,), daemon=True
                ).start()
        # Auto-mark info (unresolved only)
        if s.get("auto_mark_read_info"):
            items = [i for i in self._refresh_results.get("记录/公告", []) if not i.get("resolved")]
            if items:
                threading.Thread(
                    target=self._mark_category_read,
                    args=(items, "自动标记 {} 封记录/公告邮件为已读"),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=self._persist_batch_processed, args=(items,), daemon=True
                ).start()

    def markReadDone_(self, msg):
        js = f'showToast({json.dumps(str(msg))})'
        self._webview.evaluateJavaScript_completionHandler_(js, None)

    # ------------------------------------------------------------------
    # IMAP mark-as-read helpers
    # ------------------------------------------------------------------

    @objc.python_method
    def _acc_lookup(self, address: str) -> dict | None:
        for acc in self._accounts:
            if acc.get("address") == address:
                return acc
        return None

    @objc.python_method
    def _mark_category_read(self, items: list, msg_template: str):
        from collections import defaultdict
        by_acc: dict[str, list[str]] = defaultdict(list)
        for item in items:
            by_acc[item["account"]].append(item["uid"])

        total_ok = 0
        for address, uids in by_acc.items():
            acc = self._acc_lookup(address)
            if not acc:
                continue
            try:
                ok, _ = mark_as_read(acc["provider"], address, acc["password"], uids)
                total_ok += ok
            except Exception as e:
                print(f"[mark_as_read] {address}: {e}")

        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "markReadDone:", msg_template.format(total_ok), False
        )

    @objc.python_method
    def _mark_single_read(self, uid: str, address: str):
        acc = self._acc_lookup(address)
        if not acc:
            return
        try:
            mark_as_read(acc["provider"], address, acc["password"], [uid])
        except Exception as e:
            print(f"[mark_as_read] single {address} uid={uid}: {e}")

    # ------------------------------------------------------------------
    # Local state persist helpers (background threads)
    # ------------------------------------------------------------------

    @objc.python_method
    def _persist_resolved(self, uid: str, account: str):
        print(f"[persist_resolved] start uid={uid} account={account}")  # temp debug
        try:
            state = load_state()
            state = mark_item_processed(state, uid, account)
            save_state(state)
            print(f"[persist_resolved] done uid={uid}")  # temp debug
        except Exception as e:
            print(f"[state] persist_resolved: {e}")

    @objc.python_method
    def _persist_batch_processed(self, items: list):
        try:
            state = load_state()
            state = mark_items_processed(state, items)
            save_state(state)
        except Exception as e:
            print(f"[state] persist_batch_processed: {e}")

    @objc.python_method
    def _persist_ads_marked(self, items: list):
        try:
            state = load_state()
            state = add_items_marked_read(state, items)
            save_state(state)
        except Exception as e:
            print(f"[state] persist_ads_marked: {e}")

    # ------------------------------------------------------------------
    # Navigation action handler
    # ------------------------------------------------------------------

    @objc.python_method
    def _handle_action(self, url):
        host = url.host() or ""

        if host == "refresh":
            self._start_refresh()

        elif host == "mark_ad_read":
            items = [i for i in self._refresh_results.get("广告/可忽略", []) if not i.get("resolved")]
            if items:
                threading.Thread(
                    target=self._mark_category_read,
                    args=(items, "已标记 {} 封广告邮件为已读"),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=self._persist_ads_marked, args=(items,), daemon=True
                ).start()

        elif host == "mark_info_read":
            items = [i for i in self._refresh_results.get("记录/公告", []) if not i.get("resolved")]
            if items:
                threading.Thread(
                    target=self._mark_category_read,
                    args=(items, "已标记 {} 封记录/公告邮件为已读"),
                    daemon=True,
                ).start()
                threading.Thread(
                    target=self._persist_batch_processed, args=(items,), daemon=True
                ).start()

        elif host == "resolve":
            qs = url.query() or ""
            params  = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
            uid     = urllib.parse.unquote(params.get("uid", ""))
            account = urllib.parse.unquote(params.get("account", ""))
            if uid and account:
                threading.Thread(
                    target=self._mark_single_read, args=(uid, account), daemon=True
                ).start()
                threading.Thread(
                    target=self._persist_resolved, args=(uid, account), daemon=True
                ).start()

        elif host == "toggle_setting":
            key = (url.path() or "").lstrip("/")
            if key in ("auto_mark_read_ad", "auto_mark_read_info"):
                self._settings[key] = not self._settings.get(key, False)
                try:
                    save_settings(self._settings)
                except Exception as e:
                    print(f"[settings] save failed: {e}")
                new_val = self._settings[key]
                btn_id  = "toggle-auto-mark-ad" if key == "auto_mark_read_ad" else "toggle-auto-mark-info"
                js = f'setToggleState({json.dumps(btn_id)}, {json.dumps(new_val)})'
                self._webview.evaluateJavaScript_completionHandler_(js, None)

    # ------------------------------------------------------------------
    # WKNavigationDelegate
    # ------------------------------------------------------------------

    def webView_decidePolicyForNavigationAction_decisionHandler_(
        self, webview, action, handler
    ):
        url = action.request().URL()
        if url is None:
            handler(1)
            return
        scheme = url.scheme()
        if scheme == "mail":
            print(f"[nav] mail intercept: {url.absoluteString()}")  # temp debug
            handler(0)
            self._handle_action(url)
        elif scheme in ("http", "https"):
            handler(0)
            NSWorkspace.sharedWorkspace().openURL_(url)
        else:
            handler(1)

    # ------------------------------------------------------------------
    # WKUIDelegate
    # ------------------------------------------------------------------

    def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(
        self, _webview, message, _frame, handler
    ):
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.runModal()
        handler()

    def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(
        self, _webview, message, _frame, handler
    ):
        from AppKit import NSAlert, NSAlertFirstButtonReturn
        alert = NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.addButtonWithTitle_("确认")
        alert.addButtonWithTitle_("取消")
        result = alert.runModal()
        handler(result == NSAlertFirstButtonReturn)
