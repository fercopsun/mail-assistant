"""Local persistence for mail processing state.

- unprocessed: shown forever until user explicitly processes
- processed: shown grayed-out for 3 days then cleaned
- marked_read: ad emails already sent to IMAP, filtered from next refresh (7-day TTL)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

_BASE = Path(__file__).parent.parent / "config"
_STATE_FILE = _BASE / "mail_state.yaml"

_PROCESSED_TTL_DAYS = 3
_MARKED_READ_TTL_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s) -> datetime:
    dt = datetime.fromisoformat(str(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_state() -> dict:
    if not _STATE_FILE.exists():
        return {"unprocessed": [], "processed": [], "marked_read": []}
    with open(_STATE_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "unprocessed": data.get("unprocessed") or [],
        "processed":   data.get("processed")   or [],
        "marked_read": data.get("marked_read") or [],
    }


def save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(state, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def clean_expired(state: dict) -> dict:
    """Remove processed entries older than 3 days and marked_read entries older than 7 days."""
    now = datetime.now(timezone.utc)
    cutoff_p = now - timedelta(days=_PROCESSED_TTL_DAYS)
    cutoff_m = now - timedelta(days=_MARKED_READ_TTL_DAYS)
    state["processed"] = [
        e for e in state["processed"]
        if _parse_iso(e["processed_at"]) > cutoff_p
    ]
    state["marked_read"] = [
        e for e in state["marked_read"]
        if _parse_iso(e["marked_at"]) > cutoff_m
    ]
    return state


def _msg_key(item: dict) -> str | None:
    """Stable cross-session identifier using Message-ID header."""
    mid = (item.get("message_id") or "").strip()
    return mid if mid else None


def _uid_pair(e: dict) -> tuple[str, str]:
    return (str(e.get("uid", "")), e.get("account", ""))


def is_marked_read(state: dict, item: dict) -> bool:
    """Return True if this item was previously ad-marked-read (for next-refresh filtering)."""
    key = _msg_key(item)
    if not key:
        return False
    return any(
        e.get("message_id") == key and e.get("account") == item.get("account")
        for e in state["marked_read"]
    )


def update_unprocessed(state: dict, new_items: list[dict]) -> dict:
    """Merge newly classified non-ad items into unprocessed, preserving old entries."""
    now = _now_iso()
    new_keys  = {_uid_pair(e) for e in new_items}
    proc_keys = {_uid_pair(e) for e in state["processed"]}

    # Keep existing unprocessed entries not covered by new fetch and not processed
    kept = [
        e for e in state["unprocessed"]
        if _uid_pair(e) not in new_keys and _uid_pair(e) not in proc_keys
    ]

    added = []
    for item in new_items:
        if _uid_pair(item) in proc_keys:
            continue
        entry = item if "first_seen" in item else {**item, "first_seen": now}
        added.append(entry)

    state["unprocessed"] = kept + added
    return state


def mark_item_processed(state: dict, uid: str, account: str) -> dict:
    """Move uid+account from unprocessed to processed, timestamping now."""
    key = (str(uid), account)
    entry = next((e for e in state["unprocessed"] if _uid_pair(e) == key), None)
    state["unprocessed"] = [e for e in state["unprocessed"] if _uid_pair(e) != key]
    already_proc = any(_uid_pair(e) == key for e in state["processed"])
    if not already_proc:
        base = entry if entry else {"uid": uid, "account": account}
        state["processed"].append({**base, "processed_at": _now_iso()})
    return state


def mark_items_processed(state: dict, items: list[dict]) -> dict:
    for item in items:
        state = mark_item_processed(state, item["uid"], item["account"])
    return state


def add_items_marked_read(state: dict, items: list[dict]) -> dict:
    """Add ad emails to marked_read so they're excluded from next refresh display."""
    for item in items:
        key = _msg_key(item)
        if not key:
            continue
        exists = any(
            e.get("message_id") == key and e.get("account") == item.get("account")
            for e in state["marked_read"]
        )
        if not exists:
            state["marked_read"].append({
                "message_id": key,
                "account": item.get("account", ""),
                "marked_at": _now_iso(),
            })
    return state
