"""对本机 Ollama 的最小封装，只用 Python 标准库，不访问外网。"""

import json
import urllib.error
import urllib.request
import socket

from . import config

# 本机地址不走系统代理
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LLMError(RuntimeError):
    """Ollama 不可用、模型未下载或返回异常时抛出。"""


class LLMTimeout(LLMError):
    """The server may still be generating: do not immediately start another call."""


class LLMProtocolError(LLMError):
    """A response is not the declared JSON protocol."""


def _post_url(base: str, path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(request, timeout=config.TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"本地模型后端返回 {e.code}：{e.read().decode('utf-8', 'replace')}") from e
    except (TimeoutError, socket.timeout) as e:
        raise LLMTimeout("模型调用超时，后台状态未知，请恢复本地模型后端并重启本服务") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise LLMTimeout("模型调用超时，后台状态未知，请恢复本地模型后端并重启本服务") from e
        raise LLMError(f"连不上本地模型后端（{base}）") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise LLMProtocolError("模型返回了无效 JSON") from e


def chat(messages: list[dict], schema: dict | None = None, think: bool = False,
         temperature: float = 0, model: str | None = None, num_predict: int | None = None) -> str:
    """调用模型，返回回复文本。

    messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
    schema:   传入 JSON Schema 时，模型输出保证是符合该结构的 JSON 字符串
    think:    是否开启 Qwen3 思考模式（更慢，复杂推理时可开）
    """
    selected = model or config.MODEL
    if config.BACKEND == "ollama":
        body = {"model": selected, "messages": messages, "think": think, "stream": False,
                "options": {"temperature": temperature, "num_predict": num_predict or config.NUM_PREDICT},
                "keep_alive": config.KEEP_ALIVE}
        if schema is not None:
            body["format"] = schema
        response = _post_url(config.OLLAMA_HOST, "/api/chat", body)
        getter = lambda value: value["message"]["content"]
    else:
        msgs = messages
        if not think:
            # qwen3 默认走 thinking，输出进 reasoning_content，正式答案 content 为空。
            # 与 Ollama 分支的 think=False 保持一致：显式加 /no_think 禁用思考。
            msgs = [dict(m) for m in messages]
            for m in reversed(msgs):
                if m["role"] == "user":
                    m["content"] = f"{m['content']}\n/no_think"
                    break
        body = {"model": selected, "messages": msgs, "stream": False,
                "temperature": temperature, "max_tokens": num_predict or config.NUM_PREDICT}
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "offline_ai_ops_response", "strict": True, "schema": schema}}
        response = _post_url(config.LLAMA_CPP_CHAT_HOST, "/v1/chat/completions", body)
        getter = lambda value: value["choices"][0]["message"]["content"]
    try:
        result = getter(response)
        if not isinstance(result, str):
            raise TypeError()
        return result
    except (KeyError, TypeError) as exc:
        raise LLMProtocolError("模型回复缺少文本内容") from exc


def list_models(component: str = "chat") -> list[str]:
    backend = config.BACKEND if component == "chat" else config.EMBED_BACKEND
    if backend == "ollama":
        base, path = config.OLLAMA_HOST, "/api/tags"
    else:
        base = config.LLAMA_CPP_CHAT_HOST if component == "chat" else config.LLAMA_CPP_EMBED_HOST
        path = "/v1/models"
    request = urllib.request.Request(f"{base}{path}")
    with _OPENER.open(request, timeout=5) as response:
        payload = json.loads(response.read())
    return ([m["name"] for m in payload["models"]] if backend == "ollama"
            else [m["id"] for m in payload["data"]])


def embed(texts: list[str], model: str) -> list[list[float]]:
    """调用向量模型，把每段文本变成一个向量。"""
    if config.EMBED_BACKEND == "ollama":
        return _post_url(config.OLLAMA_HOST, "/api/embed", {"model": model, "input": texts})["embeddings"]
    payload = _post_url(config.LLAMA_CPP_EMBED_HOST, "/v1/embeddings", {"model": model, "input": texts})
    return [item["embedding"] for item in sorted(payload["data"], key=lambda item: item.get("index", 0))]
