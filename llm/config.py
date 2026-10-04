"""llm 包的全部配置，都可以用环境变量覆盖。"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ollama 地址与模型
OLLAMA_HOST = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
LLAMA_CPP_CHAT_HOST = os.environ.get("LLAMA_CPP_CHAT_HOST", "http://127.0.0.1:8080")
LLAMA_CPP_EMBED_HOST = os.environ.get("LLAMA_CPP_EMBED_HOST", "http://127.0.0.1:8081")
BACKEND = os.environ.get("LLM_BACKEND", "ollama").lower()
EMBED_BACKEND = os.environ.get("LLM_EMBED_BACKEND", BACKEND).lower()
if BACKEND not in {"ollama", "llama.cpp"} or EMBED_BACKEND not in {"ollama", "llama.cpp"}:
    raise ValueError("LLM_BACKEND/LLM_EMBED_BACKEND 只允许 ollama 或 llama.cpp")
MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")

# 手册 PDF 放在 DOCS_DIR，建索引后生成 INDEX_PATH（SQLite，随项目/SSD 一起走）
DOCS_DIR = Path(os.environ.get("LLM_DOCS_DIR", ROOT / "kb" / "docs"))
INDEX_PATH = Path(os.environ.get("LLM_INDEX_PATH", ROOT / "kb" / "index.db"))
KB_ROOT = Path(os.environ.get("LLM_KB_ROOT", ROOT / "kb"))

# LLM_MOCK=1：不调用 Ollama，返回固定的假数据，方便队友在没有模型的电脑上开发界面
MOCK = os.environ.get("LLM_MOCK", "0") == "1"

# 单次请求超时（秒）
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))
NUM_PREDICT = int(os.environ.get("LLM_NUM_PREDICT", "512"))
QA_NUM_PREDICT = int(os.environ.get("LLM_QA_NUM_PREDICT", "256"))
KEEP_ALIVE = os.environ.get("LLM_KEEP_ALIVE", "15m")

# 向量模型（通过 Ollama 调用）；设为空字符串则关闭向量检索，只用 BM25
EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "bge-m3")

# 检索方式：hybrid（BM25 + 向量，默认）/ vector / bm25；向量不可用时自动退回 bm25
RETRIEVE_MODE = os.environ.get("LLM_RETRIEVE_MODE", "hybrid")
