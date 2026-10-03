"""对本机 Ollama 的最小封装，只用 Python 标准库，不访问外网。"""

import json
import urllib.error
import urllib.request

from . import config

# 本机地址不走系统代理
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LLMError(RuntimeError):
    """Ollama 不可用、模型未下载或返回异常时抛出。"""


def _post(path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{config.OLLAMA_HOST}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(request, timeout=config.TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"Ollama 返回 {e.code}：{e.read().decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"连不上 Ollama（{config.OLLAMA_HOST}），请先运行 ollama serve") from e


def chat(messages: list[dict], schema: dict | None = None, think: bool = False,
         temperature: float = 0, model: str | None = None) -> str:
    """调用模型，返回回复文本。

    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    schema:   传入 JSON Schema 时，模型输出保证是符合该结构的 JSON 字符串
    think:    是否开启 Qwen3 思考模式（更慢，复杂推理时可开）
    """
    body = {
        "model": model or config.MODEL,
        "messages": messages,
        "think": think,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if schema is not None:
        body["format"] = schema
    return _post("/api/chat", body)["message"]["content"]


def list_models() -> list[str]:
    request = urllib.request.Request(f"{config.OLLAMA_HOST}/api/tags")
    with _OPENER.open(request, timeout=5) as response:
        return [m["name"] for m in json.loads(response.read())["models"]]
