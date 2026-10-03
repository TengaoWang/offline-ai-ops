"""llm 包的全部配置，都可以用环境变量覆盖。"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ollama 地址与模型
OLLAMA_HOST = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")

# 手册 PDF 放在 DOCS_DIR，建索引后生成 INDEX_PATH（SQLite，随项目/SSD 一起走）
DOCS_DIR = Path(os.environ.get("LLM_DOCS_DIR", ROOT / "kb" / "docs"))
INDEX_PATH = Path(os.environ.get("LLM_INDEX_PATH", ROOT / "kb" / "index.db"))

# LLM_MOCK=1：不调用 Ollama，返回固定的假数据，方便队友在没有模型的电脑上开发界面
MOCK = os.environ.get("LLM_MOCK", "0") == "1"

# 单次请求超时（秒）
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))
