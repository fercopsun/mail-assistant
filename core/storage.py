"""读取本地配置文件，带基本格式校验。"""

import yaml
from pathlib import Path

_BASE = Path(__file__).parent.parent / "config"


def load_accounts() -> list[dict]:
    path = _BASE / "accounts.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"找不到 {path}，请复制 accounts.example.yaml 并填入账号信息。"
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    accounts = (data or {}).get("accounts", [])
    for i, acc in enumerate(accounts):
        for field in ("provider", "address", "password"):
            if not acc.get(field):
                raise ValueError(f"accounts[{i}] 缺少字段：{field}")
    return accounts


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def load_llm_config() -> dict:
    path = _BASE / "llm.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"找不到 {path}，请复制 llm.example.yaml 并填入 API key。"
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    for field in ("api_key", "model"):
        if not data.get(field):
            raise ValueError(f"llm.yaml 缺少字段：{field}")

    if not data.get("base_url"):
        data["base_url"] = _DEFAULT_BASE_URL

    return data


def save_accounts(accounts: list[dict]) -> None:
    path = _BASE / "accounts.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({"accounts": accounts}, f, allow_unicode=True, default_flow_style=False)


def save_llm_config(config: dict) -> None:
    path = _BASE / "llm.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


_SETTINGS_DEFAULTS: dict = {
    "auto_mark_read": False,
}


def load_settings() -> dict:
    """加载 UI 行为开关，文件不存在时返回默认值（不抛错）。"""
    path = _BASE / "settings.yaml"
    if not path.exists():
        return dict(_SETTINGS_DEFAULTS)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {**_SETTINGS_DEFAULTS, **data}


def save_settings(settings: dict) -> None:
    path = _BASE / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(settings, f, allow_unicode=True, default_flow_style=False)
