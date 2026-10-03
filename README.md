# offline-ai-ops：离线 AI 机房运维助手

GGboys · HacKU 2026 · Deep Technology Problem Statement 4（The Capability That Hasn't Travelled）

在断网、资料不能外传的机房里，让现场人员拥有一位「带着厂商手册的资深同事」：
根据故障描述选出排查技能包、在手册里检索依据并给出带出处的回答。模型与知识库全部在本机运行。

## 目录

| 目录 | 内容 | 状态 |
|---|---|---|
| [`llm/`](llm/) | **模型与知识库接口**：`route` / `retrieve` / `ask` / `chat` / `health`，供引擎和界面调用 | 可用 |
| [`eval/`](eval/) | 技能路由评测、手册检索评测 | 可用 |
| [`tests/`](tests/) | `llm` 接口的单元测试（不需要 Ollama） | 22 项通过 |
| [`docs/`](docs/) | 需求文档、前端方案、RAG 技术路线与交接说明 | — |
| `kb/docs/` | 厂商手册放这里（不进 git） | — |
| `kb/index.db` | 手册索引（不进 git，可以直接拷给队友） | — |

## 安装 Ollama 和下载模型

Ollama 是在本机运行大模型的工具。安装和下载模型时需要联网，**之后全程离线可用**。

### 1. 安装 Ollama

| 系统 | 安装方法 |
|---|---|
| macOS | 方法一：到 [ollama.com/download](https://ollama.com/download) 下载安装包，拖进「应用程序」后打开，它会在后台运行（菜单栏出现羊驼图标）<br>方法二：`brew install ollama`，再运行 `brew services start ollama` 让它在后台运行并开机自启 |
| Windows | 到 [ollama.com/download](https://ollama.com/download) 下载 `OllamaSetup.exe` 并安装，装好后自动在后台运行（任务栏右下角出现图标） |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |

验证是否装好（能显示版本号即可）：

```bash
ollama --version
```

### 2. 下载模型

```bash
ollama pull qwen3:8b      # 约 5.2GB，回答用；建议 16GB 内存或 8GB 显存以上
ollama pull bge-m3        # 约 1.2GB，手册向量检索用
```

电脑配置较低（8GB 内存、没有独显）时，改用 4B 模型，并通过环境变量告诉程序：

```bash
ollama pull qwen3:4b      # 约 2.5GB
export LLM_MODEL=qwen3:4b # Windows PowerShell：$env:LLM_MODEL="qwen3:4b"
```

### 3. 确认可用

```bash
ollama list                       # 列表里应出现 qwen3:8b 和 bge-m3
ollama run qwen3:8b "你好"         # 能正常回答即可，第一次加载需要十几秒
```

### 常见问题

| 现象 | 解决方法 |
|---|---|
| 提示连不上 Ollama（`127.0.0.1:11434`） | Ollama 没在运行：macOS 打开 Ollama App 或运行 `brew services start ollama`；Windows 从开始菜单打开 Ollama；也可以另开一个终端运行 `ollama serve` |
| 下载很慢或中断 | 重新运行 `ollama pull qwen3:8b`，会从中断处继续 |
| 想把模型放到 SSD 或其他盘 | 安装后设置环境变量 `OLLAMA_MODELS` 指向新目录，再重启 Ollama |
| 想给没有网络的电脑用 | 在联网电脑上下载好，把模型目录（macOS / Linux：`~/.ollama/models`；Windows：`C:\Users\<用户名>\.ollama\models`）整个复制到对方电脑的同一位置 |

## 快速开始

装好 Ollama 和模型之后：

```bash
# 1. Python 环境
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# 2. 索引：向队友要 kb/index.db 放到 kb/ 下（推荐）；
#    或者把手册放进 kb/docs/ 后自己建（约 20 分钟）
.venv/bin/python -m llm ingest
.venv/bin/python -m llm health      # ollama、model、embed_model、index 都为 true，vectors 等于 chunks 即可

# 3. 试用
.venv/bin/python -m llm route "nginx 起不来"
.venv/bin/python -m llm search "怎么检查光模块是不是坏了"
.venv/bin/python -m llm ask "交换机 CPU 占用率高怎么处理"
```

Windows 上把命令里的 `.venv/bin/python` 换成 `.venv\Scripts\python`。

没有模型时可以先用 mock 模式开发界面：`LLM_MOCK=1 .venv/bin/python -m llm ask "随便问"`。
接口的参数、返回格式和配置见 [`llm/README.md`](llm/README.md)。

## 启动前端操作台

前端是本地 Web 操作台，静态资源由 Python 服务托管，不需要 Node、CDN 或外网请求。

```bash
LLM_MOCK=1 .venv/bin/python -m ui.server
```

打开 `http://127.0.0.1:8765` 即可使用。已有 Ollama、模型和索引时，可以去掉 `LLM_MOCK=1` 连接真实 `llm` 接口；采集、规则树、报告和存技能在 `engine/` 接入前使用本地演示流。

## 当前结果

| 项目 | 结果 | 条件 |
|---|---|---|
| 技能路由准确率 | 97.7%（85/87），JSON 合法率 100% | Qwen3-8B 基座 + 提示词（Ollama），不微调；MacBook Air M4 16GB |
| 技能路由耗时 | 平均 0.70 秒/条 | 同上 |
| 手册检索 | Hit@1 77%，Hit@3 94%（口语题 Hit@3 91%，FR-2 预设题 100%）；只用 BM25 时为 58% / 74%（口语题 45%） | 《华为 S 系列园区交换机维护宝典》第 25 版，BM25 + bge-m3 混合检索，36 题测试集 |
| 手册检索耗时 | 约 0.05 秒/次 | MacBook Air M4 16GB |
| 手册问答（`ask`）耗时 | 15 到 50 秒/次，**还没达到每轮 30 秒以内** | 同上，qwen3:8b |

技能路由的测试集为模板生成的 87 条（测试集中的说法训练与调试时未出现）。手册检索的测试集是调参用的同一批题，没有独立的留出集。两者样本量都小，不代表真实场景的普遍准确率。

## 下一步

- 手册问答提速（目标每轮 30 秒以内）
- 检索阶段的拒答：手册里没有的问题直接返回「未找到」，不用等模型
- 端到端问答评测：检查回答里的命令是否正确、统计误拒率
- 在 8GB 内存 + qwen3:4b 的配置下测一次

RAG 的现状、已知问题和接手方法见 [`docs/rag-handoff.md`](docs/rag-handoff.md)。
