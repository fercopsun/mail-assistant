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


def load_llm_config() -> dict:
    path = _BASE / "llm.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"找不到 {path}，请复制 llm.example.yaml 并填入 API key。"
        )
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    for field in ("api_key", "base_url", "model"):
        if not data.get(field):
            raise ValueError(f"llm.yaml 缺少字段：{field}")
    return data
