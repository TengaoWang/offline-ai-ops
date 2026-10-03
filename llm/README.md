# llm：模型与知识库接口

给引擎、界面等模块调用的统一入口。全部在本机运行（Ollama + SQLite），准备完成后不需要联网。

```python
from llm import route, retrieve, ask, chat, health
```

| 函数 | 作用 | 返回 |
|---|---|---|
| `route(描述)` | 根据故障描述选技能包 | `{"skill": "disk-full" 或 None, "latency_s", "raw"}` |
| `retrieve(问题, k=5)` | 在手册里检索最相关的 k 段（不调用模型） | `[{"id", "text", "file", "page", "section", "score"}]` |
| `ask(问题, k=5)` | 根据手册回答并附出处；找不到依据就明确说没找到 | `{"answer", "found", "citations": [{"n", "file", "page", "section", "label", "text"}], "latency_s"}` |
| `chat(messages, schema=None, think=False)` | 通用模型调用，例如规则树未覆盖时的「AI 补充推理」 | 回复文本（传 `schema` 时为 JSON 字符串） |
| `health()` | 检查 Ollama、模型、索引是否就绪 | `{"mock", "ollama", "model", "index", "chunks"}` |

- `route` 的 `skill` 只会是 `net-unreachable` / `disk-full` / `service-down` / `log-audit` / `None`。`None` 表示不属于任何技能包，交给人工。
- `ask` 的出处由程序根据检索结果生成，模型只负责选编号，所以页码和章节不会被编造。`found` 为 `False` 时，`answer` 固定为「手册中未找到依据。」，`citations` 为空。
- `citations[].label` 是可以直接显示的出处，例如 `《S5700产品文档》3 VLAN 配置 > 3.2 配置链路类型 P47`。来自 Markdown / TXT 的片段没有页码，`page` 为 `None`。
- Ollama 没启动或模型没下载时，`route` / `ask` / `chat` 会抛出 `llm.LLMError`，界面可以捕获后提示用户。

## 准备（只需一次，需要联网）

```bash
# 1. Ollama
brew install ollama            # Windows：从 ollama.com 下载安装包
ollama serve                   # 保持运行
ollama pull qwen3:8b           # 约 5GB

# 2. Python 依赖
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# 3. 把手册（PDF / Markdown / TXT）放进 kb/docs/，然后建索引
.venv/bin/python -m llm ingest
.venv/bin/python -m llm health   # 全部为 true 即可
```

## 命令行快速试用

```bash
.venv/bin/python -m llm route "nginx 起不来"
.venv/bin/python -m llm search "trunk 配置"
.venv/bin/python -m llm ask "S5700 怎么把接口配成 trunk"
```

## 没有模型时先开发：mock 模式

设置环境变量 `LLM_MOCK=1`，所有函数返回固定的假数据，不需要 Ollama 和索引，适合先搭界面：

```bash
LLM_MOCK=1 .venv/bin/python -m llm ask "随便问"
```

Windows PowerShell：`$env:LLM_MOCK="1"`。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_MODEL` | `qwen3:8b` | 低配电脑可改为 `qwen3:4b` |
| `OLLAMA_HOST_URL` | `http://127.0.0.1:11434` | Ollama 地址 |
| `LLM_DOCS_DIR` | `kb/docs` | 手册目录 |
| `LLM_INDEX_PATH` | `kb/index.db` | 索引文件 |
| `LLM_MOCK` | `0` | `1` 为 mock 模式 |
| `LLM_TIMEOUT` | `120` | 单次请求超时（秒） |

## 目前的限制（简单版）

- 检索只用 BM25 关键词（jieba 分词），还没有向量检索、同义词扩展和重排序。在维护宝典上试测 7 个问题，5 个的正确章节排第 1；「接口一直是 down 状态」这类说法排第 4 到第 7，`ask` 可能答到 OSPF 等其他章节上。
- 还没有带标准答案的检索测试集，上面的数字只是试测。
- `ask` 每次把 5 段（每段至多 600 字）交给模型，较长的回答约 25 秒。
- `page` 是 PDF 阅读器里的页码（封面为第 1 页），不是手册页脚印的页码。
- 建索引时会跳过目录页（引导点「......」占比超过 30% 的页）。
- `route` 用的是基座模型 + 提示词，没有微调；评测结果见 [`finetune/README.md`](../finetune/README.md)。
