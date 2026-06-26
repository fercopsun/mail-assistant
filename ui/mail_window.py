"""邮件助手 — 原生 macOS 窗口（AppKit + WKWebView）阶段 A：静态假数据展示"""

import html
import objc
from Foundation import NSObject, NSURL
from AppKit import (
    NSWindow,
    NSColor,
    NSWorkspace,
    NSTitledWindowMask,
    NSClosableWindowMask,
    NSMiniaturizableWindowMask,
    NSResizableWindowMask,
    NSBackingStoreBuffered,
)
from WebKit import WKWebView, WKWebViewConfiguration

# ---------------------------------------------------------------------------
# Fake data — fields match ClassifiedMail exactly
# ---------------------------------------------------------------------------

_FAKE_BRIEF = (
    "Anthropic 订阅付款失败 £18.00，需在 3 天内更新支付方式；"
    "域名 fercopsun.com 将于 2026-07-01 到期，需续费；"
    "GitHub Actions 配额用尽，CI 已暂停，需升级套餐。"
)

_FAKE_RESULTS = {
    "需要回复": [
        {
            "uid": "1001",
            "account": "chengsun2001@gmail.com",
            "subject": "Re: 展览合作意向 — 想了解更多细节",
            "sender": "gallery@artspace.cn",
            "date_str": "2026-06-26 09:15",
            "snippet": "您好，我们看了您的作品集非常感兴趣，能否方便时间通话详聊合作方式？期待您的回复。",
            "reason": "发件人明确期待回信，商量合作事宜",
            "message_id": "<abc123@artspace.cn>",
        },
        {
            "uid": "1002",
            "account": "chengsun2001@gmail.com",
            "subject": "关于投稿截止时间的确认",
            "sender": "editor@designmagazine.com",
            "date_str": "2026-06-25 18:30",
            "snippet": "Hi，请问您的稿件能在本周五前提交吗？我们需要提前排版，麻烦回复确认一下，谢谢！",
            "reason": "编辑需要确认截止前能否提交稿件",
            "message_id": "<xyz456@designmagazine.com>",
        },
    ],
    "需要处理（非回复）": [
        {
            "uid": "1003",
            "account": "chengsun2001@gmail.com",
            "subject": "Your Anthropic payment failed — action required",
            "sender": "billing@anthropic.com",
            "date_str": "2026-06-26 07:00",
            "snippet": "We were unable to charge £18.00 to your card ending in 4242. Please update your payment method within 3 days to avoid service interruption.",
            "reason": "付款失败，需在3天内更新支付方式",
            "message_id": "<bill001@anthropic.com>",
        },
        {
            "uid": "1004",
            "account": "chengsun2001@gmail.com",
            "subject": "域名 fercopsun.com 即将到期",
            "sender": "noreply@namecheap.com",
            "date_str": "2026-06-25 10:00",
            "snippet": "您的域名 fercopsun.com 将于 2026-07-01 到期，请登录控制台续费，否则域名将被释放。",
            "reason": "域名5天后到期，需登录续费",
            "message_id": "<domain001@namecheap.com>",
        },
        {
            "uid": "1005",
            "account": "chengsun2001@gmail.com",
            "subject": "GitHub Actions 配额已用尽",
            "sender": "noreply@github.com",
            "date_str": "2026-06-24 22:00",
            "snippet": "Your GitHub Actions minutes for this month have been exhausted. CI workflows are now paused. Upgrade your plan to continue.",
            "reason": "CI配额用尽，需升级套餐才能继续运行",
            "message_id": "<gh001@github.com>",
        },
    ],
    "记录/公告": [
        {
            "uid": "1006",
            "account": "chengsun2001@gmail.com",
            "subject": "您的 iCloud 订阅已成功续费",
            "sender": "no_reply@email.apple.com",
            "date_str": "2026-06-26 06:00",
            "snippet": "感谢您的订阅！您的 iCloud+ 50GB 计划已于 2026-06-26 成功续费，金额 ¥6.00。下次续费日期：2026-07-26。",
            "reason": "iCloud成功扣款的收据，纯记录",
            "message_id": "<apple001@apple.com>",
        },
        {
            "uid": "1007",
            "account": "chengsun2001@gmail.com",
            "subject": "您已被加入项目协作者名单",
            "sender": "notifications@github.com",
            "date_str": "2026-06-25 14:22",
            "snippet": "You have been added as a collaborator to the repository design-system/tokens by user @teammate.",
            "reason": "系统通知，被加入协作者，无需操作",
            "message_id": "<gh002@github.com>",
        },
    ],
    "广告/可忽略": [
        {
            "uid": "1008",
            "account": "chengsun2001@gmail.com",
            "subject": "🔥 618 大促最后3天！设计素材全场5折",
            "sender": "promo@iconfont.cn",
            "date_str": "2026-06-25 08:00",
            "snippet": "618年中大促进行中，精选字体、图标包、UI组件全场5折起，限时48小时，先到先得！",
            "reason": "营销推送，限时优惠活动",
            "message_id": "<promo001@iconfont.cn>",
        },
        {
            "uid": "1009",
            "account": "chengsun2001@gmail.com",
            "subject": "This week in design — Typography trends 2026",
            "sender": "newsletter@smashingmagazine.com",
            "date_str": "2026-06-25 07:30",
            "snippet": "In this week's issue: variable fonts go mainstream, the return of slab serifs, AI-generated typefaces debate, and more.",
            "reason": "订阅周刊，无需操作",
            "message_id": "<sm001@smashingmagazine.com>",
        },
    ],
}


def _he(s: str) -> str:
    return html.escape(str(s), quote=True)


def _mail_link(item: dict) -> str:
    account = item.get("account", "")
    message_id = item.get("message_id", "")
    if "@gmail.com" in account and message_id:
        import urllib.parse
        q = urllib.parse.quote(f"rfc822msgid:{message_id}")
        return f"https://mail.google.com/mail/u/0/#search/{q}"
    if "@qq.com" in account:
        return "https://mail.qq.com"
    if "@163.com" in account or "@126.com" in account:
        return "https://mail.163.com"
    return "#"


# ---------------------------------------------------------------------------
# Main window class
# ---------------------------------------------------------------------------

class MailWindow(NSObject):

    @objc.python_method
    def init(self):
        self = objc.super(MailWindow, self).init()
        if self is None:
            return None
        self._window = None
        self._webview = None
        return self

    @objc.python_method
    def show(self):
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
            NSTitledWindowMask
            | NSClosableWindowMask
            | NSMiniaturizableWindowMask
            | NSResizableWindowMask
        )
        from Foundation import NSMakeRect
        rect = NSMakeRect(0, 0, 960, 720)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        win.setTitle_("邮件助手")
        win.setMinSize_((760, 500))

        cfg = WKWebViewConfiguration.alloc().init()
        wv = WKWebView.alloc().initWithFrame_configuration_(rect, cfg)
        wv.setAutoresizingMask_(18)  # NSViewWidthSizable | NSViewHeightSizable
        wv.setNavigationDelegate_(self)
        wv.setUIDelegate_(self)

        win.contentView().addSubview_(wv)
        self._window = win
        self._webview = wv

    @objc.python_method
    def _load_html(self, html_str: str):
        self._webview.loadHTMLString_baseURL_(html_str, None)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @objc.python_method
    def _render_main(self):
        sidebar_html = self._render_sidebar(_FAKE_RESULTS)
        panels_html = self._render_panels(_FAKE_RESULTS, _FAKE_BRIEF)
        page = self._build_page(sidebar_html, panels_html)
        self._load_html(page)

    @objc.python_method
    def _build_page(self, sidebar_html: str, panels_html: str) -> str:
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
      <button class="nav-settings" onclick="xdNav('mail://settings')">
        <span>⚙️</span><span>设置</span>
      </button>
    </div>
  </aside>
  <div class="content-area">
    <div class="content-header">
      <span class="content-title" id="content-title">需要回复</span>
      <button class="btn btn-refresh" onclick="xdNav('mail://refresh')">刷新收件箱</button>
    </div>
    <div class="content-scroll">
      {panels_html}
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
  --card-bg: #fff;
  --border: 2.5px solid #111;
  --shadow: 4px 4px 0 #111;
  --shadow-lg: 6px 6px 0 #111;
  --shadow-sm: 3px 3px 0 #111;
  --transition: transform 150ms ease, box-shadow 150ms ease;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
  background: var(--bg);
  color: var(--black);
  font-size: 14px;
  line-height: 1.5;
  height: 100vh;
  overflow: hidden;
}

/* ---- Layout ---- */
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  border: 3px solid #111;
  border-radius: 20px;
}

/* ---- Sidebar ---- */
.sidebar {
  width: 204px;
  flex-shrink: 0;
  border-right: 2.5px solid #111;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  overflow-y: auto;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 16px 14px;
  border-bottom: 2.5px solid #111;
  flex-shrink: 0;
}
.logo-icon { font-size: 20px; }
.logo-text { font-size: 15px; font-weight: 900; letter-spacing: -0.5px; }

.sidebar-nav {
  display: flex;
  flex-direction: column;
  padding: 12px 10px;
  gap: 10px;
  flex: 1;
}

/* Nav items: full saturated color block */
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border: 2.5px solid #111;
  border-radius: 12px;
  box-shadow: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  text-align: left;
  color: #111;
  opacity: 0.58;
  transition: var(--transition), opacity 0.12s;
}
.nav-item.active {
  opacity: 1;
  box-shadow: 4px 4px 0 #111;
}
.nav-item:hover:not(.active) {
  opacity: 0.88;
  transform: translate(-2px, -2px);
  box-shadow: 6px 6px 0 #111;
}
.nav-item:active {
  transform: translate(1px, 1px);
  box-shadow: 2px 2px 0 #111;
  opacity: 1;
}

.nav-icon  { font-size: 15px; flex-shrink: 0; }
.nav-label { flex: 1; }

.nav-badge {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 2px solid #111;
  background: #fff;
  font-size: 11px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sidebar-sep {
  height: 2px;
  background: #111;
  margin: 2px 10px 6px;
  opacity: 0.15;
  flex-shrink: 0;
}

.sidebar-footer { padding: 0 10px 14px; flex-shrink: 0; }
.nav-settings {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: #777;
  transition: background 0.12s, color 0.12s;
}
.nav-settings:hover { background: rgba(0,0,0,0.07); color: #111; }

/* ---- Content area ---- */
.content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 2.5px solid #111;
  background: var(--bg);
  flex-shrink: 0;
}
.content-title {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.3px;
}

.content-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 14px 14px 32px;
}

/* ---- Panels ---- */
.panel { display: none; }
.panel.active { display: block; }

/* ---- Buttons ---- */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 2px solid #111;
  border-radius: 10px;
  box-shadow: 3px 3px 0 #111;
  background: var(--bg);
  color: #111;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: var(--transition);
  white-space: nowrap;
}
.btn:hover:not(:disabled) {
  transform: translate(-2px, -2px) rotate(-1deg);
  box-shadow: 5px 5px 0 #111;
}
.btn:active:not(:disabled) {
  transform: translate(1px, 1px) rotate(0deg);
  box-shadow: 1px 1px 0 #111;
}
.btn:disabled {
  opacity: 0.38;
  cursor: not-allowed;
  box-shadow: none;
}
.btn-refresh  { background: #111; color: #FBF3E3; }
.btn-reply    { background: #FF6FA5; }
.btn-resolve  { background: #FFD93D; }
.btn-resolved { background: #B8EDBE; }
.btn-mark-read { background: #7CE38B; }
.btn-danger   { background: #FF6FA5; }

/* ---- Star button — inline with subject line ---- */
.card-subject-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.card-subject-row .card-subject { margin-bottom: 0; flex: 1; min-width: 0; }

.star-btn {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border: 1.5px solid transparent;
  border-radius: 5px;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  color: #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  line-height: 1;
  transition: color 0.12s, background 0.12s, border-color 0.12s, box-shadow 0.12s;
}
.star-btn:hover { color: #f5a623; border-color: #111; background: #fff8d0; }
.star-btn.starred {
  color: #a06000;
  background: #FFD93D;
  border: 1.5px solid #111;
  box-shadow: 2px 2px 0 #111;
}

/* ---- Brief banner ---- */
.brief-banner {
  padding: 12px 16px;
  background: #FFF8D0;
  border: 2.5px solid #111;
  border-radius: 12px;
  box-shadow: 3px 3px 0 #111;
  font-size: 13px;
  line-height: 1.6;
  color: #5a4800;
  margin-bottom: 14px;
}
.brief-label {
  font-weight: 800;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
  color: #8a6800;
}

/* ---- Batch bar (ads panel) ---- */
.batch-bar {
  padding: 10px 14px;
  border: 2.5px solid #111;
  border-radius: 12px;
  box-shadow: 3px 3px 0 #111;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #C8F1CC;
  margin-bottom: 14px;
}

/* ---- Mail cards: independent rounded cards, not list rows ---- */
.card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: #fff;
  border: 2.5px solid #111;
  border-radius: 14px;
  box-shadow: 4px 4px 0 #111;
  margin-bottom: 12px;
  transition: var(--transition);
}
.card:last-child { margin-bottom: 0; }
.card:hover {
  transform: translate(-2px, -2px);
  box-shadow: 6px 6px 0 #111;
}
.card:active {
  transform: translate(1px, 1px);
  box-shadow: 2px 2px 0 #111;
}
.card.resolved {
  opacity: 0.38;
  transform: none !important;
  box-shadow: 4px 4px 0 #111 !important;
  pointer-events: none;
}

.card-left { flex: 1; min-width: 0; }

.card-subject {
  font-weight: 700;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-subject a { color: #111; text-decoration: none; }
.card-subject a:hover { text-decoration: underline; }

.card-meta { font-size: 12px; color: #666; margin-bottom: 5px; }

.card-snippet {
  font-size: 13px;
  color: #444;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-reason { margin-top: 5px; font-size: 11.5px; color: #888; font-style: italic; }

.card-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
  align-self: center;
}

/* ---- Empty state ---- */
.empty-state {
  padding: 36px 18px;
  text-align: center;
  font-size: 13px;
  color: #aaa;
  font-style: italic;
  display: none;
}
.empty-state.visible { display: block; }

/* ---- Toast ---- */
#toast {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%) translateY(20px);
  background: #111;
  color: #FBF3E3;
  padding: 9px 20px;
  border: 2px solid #111;
  border-radius: 10px;
  box-shadow: 3px 3px 0 #111;
  font-size: 13px;
  font-weight: 600;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s, transform 0.2s;
  z-index: 999;
}
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

/* ---- Confirm overlay ---- */
#confirm-overlay {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.38);
  z-index: 500;
  align-items: center;
  justify-content: center;
}
#confirm-overlay.show { display: flex; }
.confirm-box {
  background: var(--bg);
  border: 2.5px solid #111;
  box-shadow: 6px 6px 0 #111;
  border-radius: 16px;
  padding: 24px 28px;
  max-width: 360px;
  width: 90%;
}
.confirm-msg { font-size: 14px; font-weight: 600; margin-bottom: 18px; line-height: 1.5; }
.confirm-btns { display: flex; gap: 10px; justify-content: flex-end; }
"""

    @objc.python_method
    def _build_shared_js(self) -> str:
        return """<script>
function xdNav(url) { window.location.href = url; }

// ---- Toast ----
function showToast(msg) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._tid);
  t._tid = setTimeout(function(){ t.classList.remove('show'); }, 2400);
}

// ---- Confirm overlay ----
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

// ---- Sidebar tab switching ----
var _TAB_LABELS = {
  reply:  '需要回复',
  action: '需要处理（非回复）',
  info:   '记录 / 公告',
  ad:     '广告 / 可忽略'
};
var _currentTab = 'reply';

function switchTab(id) {
  if (id === _currentTab) return;
  document.getElementById('panel-' + _currentTab).classList.remove('active');
  document.getElementById('nav-' + _currentTab).classList.remove('active');
  _currentTab = id;
  document.getElementById('panel-' + id).classList.add('active');
  document.getElementById('nav-' + id).classList.add('active');
  document.getElementById('content-title').textContent = _TAB_LABELS[id];
}

// ---- Star / pin (reply panel only) ----
var _starredTimes = {};

function toggleStar(uid) {
  var btn = document.getElementById('star-' + uid);
  if (_starredTimes[uid]) {
    delete _starredTimes[uid];
    btn.textContent = '☆';
    btn.classList.remove('starred');
  } else {
    _starredTimes[uid] = Date.now();
    btn.textContent = '★';
    btn.classList.add('starred');
  }
  _reorderReplyCards();
}

function _reorderReplyCards() {
  var body = document.getElementById('group-reply-body');
  if (!body) return;
  var cards = Array.from(body.querySelectorAll('.card[data-uid]'));
  var starred = cards
    .filter(function(c){ return !!_starredTimes[c.dataset.uid]; })
    .sort(function(a, b){ return _starredTimes[a.dataset.uid] - _starredTimes[b.dataset.uid]; });
  var unstarred = cards.filter(function(c){ return !_starredTimes[c.dataset.uid]; });
  var emptyDiv = body.querySelector('.empty-state');
  starred.concat(unstarred).forEach(function(c){ body.insertBefore(c, emptyDiv || null); });
}

// ---- Resolve (action panel) ----
var resolvedUids = {};
function markResolved(uid, groupId) {
  resolvedUids[uid] = true;
  var card = document.getElementById('card-' + uid);
  if (card) card.classList.add('resolved');
  var btn = document.getElementById('btn-resolve-' + uid);
  if (btn) {
    btn.textContent = '↩ 撤销';
    btn.className = 'btn btn-resolved';
    btn.onclick = function(){ undoResolved(uid, groupId); };
  }
  _updateEmpty(groupId);
}
function undoResolved(uid, groupId) {
  delete resolvedUids[uid];
  var card = document.getElementById('card-' + uid);
  if (card) card.classList.remove('resolved');
  var btn = document.getElementById('btn-resolve-' + uid);
  if (btn) {
    btn.textContent = '✓ 已解决';
    btn.className = 'btn btn-resolve';
    btn.onclick = function(){ markResolved(uid, groupId); };
  }
  _updateEmpty(groupId);
}

function _updateEmpty(groupId) {
  var body = document.getElementById(groupId + '-body');
  if (!body) return;
  var cards = body.querySelectorAll('.card');
  var empty = body.querySelector('.empty-state');
  var allResolved = Array.from(cards).every(function(c){ return c.classList.contains('resolved'); });
  if (empty) empty.classList.toggle('visible', allResolved);
}

// ---- Ads bulk mark-read ----
function markAllAdRead(count) {
  xdConfirm('将 ' + count + ' 封广告邮件标记为已读？（阶段A仅本地演示）', function(){
    var body = document.getElementById('group-ad-body');
    if (!body) return;
    body.querySelectorAll('.card').forEach(function(c){ c.classList.add('resolved'); });
    _updateEmpty('group-ad');
    showToast('已标记 ' + count + ' 封广告邮件为已读');
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
    # Sidebar — saturated candy colors as specified
    # ------------------------------------------------------------------

    @objc.python_method
    def _render_sidebar(self, results: dict) -> str:
        rc = len(results.get("需要回复", []))
        ac = len(results.get("需要处理（非回复）", []))
        ic = len(results.get("记录/公告", []))
        dc = len(results.get("广告/可忽略", []))

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
            _item("reply",  "💬", "需要回复",     "#FF6FA5", rc, " active"),
            _item("action", "⚡", "需要处理",      "#FFD93D", ac),
            _item("info",   "📋", "记录 / 公告",   "#5BC8FF", ic),
            _item("ad",     "🗑", "广告 / 可忽略", "#7CE38B", dc),
        ])

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------

    @objc.python_method
    def _render_panels(self, results: dict, brief: str) -> str:
        reply_items  = results.get("需要回复", [])
        action_items = results.get("需要处理（非回复）", [])
        info_items   = results.get("记录/公告", [])
        ad_items     = results.get("广告/可忽略", [])

        reply_cards = "".join(self._build_reply_card(m) for m in reply_items)
        reply_panel = self._wrap_panel("reply", "active", "", "group-reply", reply_cards)

        action_top = ""
        if brief and action_items:
            action_top = (
                f'<div class="brief-banner">'
                f'<div class="brief-label">行动简报</div>'
                f'{_he(brief)}'
                f'</div>'
            )
        action_cards = "".join(self._build_action_card(m) for m in action_items)
        action_panel = self._wrap_panel("action", "", action_top, "group-action", action_cards)

        info_cards = "".join(self._build_info_card(m) for m in info_items)
        info_panel = self._wrap_panel("info", "", "", "group-info", info_cards)

        ad_top = self._build_batch_bar(len(ad_items)) if ad_items else ""
        ad_cards = "".join(self._build_ad_card(m) for m in ad_items)
        ad_panel = self._wrap_panel("ad", "", ad_top, "group-ad", ad_cards)

        return "\n".join([reply_panel, action_panel, info_panel, ad_panel])

    @objc.python_method
    def _wrap_panel(
        self,
        tab_id: str,
        extra_cls: str,
        top_html: str,
        group_id: str,
        cards_html: str,
    ) -> str:
        cls = f"panel {extra_cls}".strip()
        if cards_html:
            body_content = cards_html + '\n<div class="empty-state">这一类暂无需要处理的邮件</div>'
        else:
            body_content = '<div class="empty-state visible">这一类暂无需要处理的邮件</div>'
        return (
            f'<div id="panel-{tab_id}" class="{cls}">'
            f'{top_html}'
            f'<div id="{group_id}-body">{body_content}</div>'
            f'</div>'
        )

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------

    @objc.python_method
    def _build_reply_card(self, item: dict) -> str:
        link = _mail_link(item)
        uid = _he(item["uid"])
        # Star button lives inside card-left, inline with the subject line
        return (
            f'<div class="card" id="card-{uid}" data-uid="{uid}">'
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
            f'<button class="btn btn-reply" disabled title="v0.5 实现草稿功能">回复（v0.5）</button>'
            f'<button class="btn" onclick="xdNav(\'{_he(link)}\')">查看原信</button>'
            f'</div>'
            f'</div>'
        )

    @objc.python_method
    def _build_action_card(self, item: dict) -> str:
        link = _mail_link(item)
        uid = _he(item["uid"])
        return (
            f'<div class="card" id="card-{uid}">'
            f'<div class="card-left">'
            f'<div class="card-subject"><a href="{_he(link)}" onclick="xdNav(\'{_he(link)}\');return false;">{_he(item["subject"])}</a></div>'
            f'<div class="card-meta">{_he(item["sender"])} · {_he(item["date_str"])} · {_he(item["account"])}</div>'
            f'<div class="card-snippet">{_he(item["snippet"])}</div>'
            f'<div class="card-reason">分类理由：{_he(item["reason"])}</div>'
            f'</div>'
            f'<div class="card-actions">'
            f'<button class="btn btn-resolve" id="btn-resolve-{uid}" onclick="markResolved(\'{uid}\', \'group-action\')">✓ 已解决</button>'
            f'<button class="btn" onclick="xdNav(\'{_he(link)}\')">查看原信</button>'
            f'</div>'
            f'</div>'
        )

    @objc.python_method
    def _build_info_card(self, item: dict) -> str:
        link = _mail_link(item)
        uid = _he(item["uid"])
        return (
            f'<div class="card" id="card-{uid}">'
            f'<div class="card-left">'
            f'<div class="card-subject"><a href="{_he(link)}" onclick="xdNav(\'{_he(link)}\');return false;">{_he(item["subject"])}</a></div>'
            f'<div class="card-meta">{_he(item["sender"])} · {_he(item["date_str"])} · {_he(item["account"])}</div>'
            f'<div class="card-snippet">{_he(item["snippet"])}</div>'
            f'<div class="card-reason">分类理由：{_he(item["reason"])}</div>'
            f'</div>'
            f'<div class="card-actions">'
            f'<button class="btn" onclick="xdNav(\'{_he(link)}\')">查看原信</button>'
            f'</div>'
            f'</div>'
        )

    @objc.python_method
    def _build_ad_card(self, item: dict) -> str:
        link = _mail_link(item)
        uid = _he(item["uid"])
        return (
            f'<div class="card" id="card-{uid}">'
            f'<div class="card-left">'
            f'<div class="card-subject"><a href="{_he(link)}" onclick="xdNav(\'{_he(link)}\');return false;">{_he(item["subject"])}</a></div>'
            f'<div class="card-meta">{_he(item["sender"])} · {_he(item["date_str"])} · {_he(item["account"])}</div>'
            f'<div class="card-snippet">{_he(item["snippet"])}</div>'
            f'<div class="card-reason">分类理由：{_he(item["reason"])}</div>'
            f'</div>'
            f'</div>'
        )

    @objc.python_method
    def _build_batch_bar(self, count: int) -> str:
        return (
            f'<div class="batch-bar">'
            f'<span style="font-size:13px;color:#1a4a1a;">共 <strong>{count}</strong> 封广告邮件</span>'
            f'<button class="btn btn-mark-read" onclick="markAllAdRead({count})">批量标记已读</button>'
            f'</div>'
        )

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
            handler(0)
            self._handle_action(url)
        elif scheme in ("http", "https"):
            handler(0)
            NSWorkspace.sharedWorkspace().openURL_(url)
        else:
            handler(1)

    @objc.python_method
    def _handle_action(self, url):
        host = url.host() or ""
        if host == "refresh":
            self._render_main()

    # ------------------------------------------------------------------
    # WKUIDelegate
    # ------------------------------------------------------------------

    def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(
        self, webview, message, frame, handler
    ):
        from AppKit import NSAlert
        alert = NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.runModal()
        handler()

    def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(
        self, webview, message, frame, handler
    ):
        from AppKit import NSAlert, NSAlertFirstButtonReturn
        alert = NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.addButtonWithTitle_("确认")
        alert.addButtonWithTitle_("取消")
        result = alert.runModal()
        handler(result == NSAlertFirstButtonReturn)
