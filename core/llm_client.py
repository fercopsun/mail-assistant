"""OpenAI 兼容 chat completions 调用封装。"""

from openai import OpenAI


def call_llm(
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
) -> str:
    """调用一次 chat completions，返回助手回复文本。"""
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""
