# offline-ai-ops：离线 AI 机房运维助手

GGboys · HacKU 2026 · Deep Technology Problem Statement 4（The Capability That Hasn't Travelled）

在断网、资料不能外传的机房里，让现场人员拥有一位「带着厂商手册的资深同事」：
根据故障描述选出排查技能包、在手册里检索依据并给出带出处的回答。模型与知识库全部在本机运行。

## 目录

| 目录 | 内容 | 状态 |
|---|---|---|
| [`engine/`](engine/) | 白名单只读执行、技能加载、规则树、AI 补充与带出处报告 | 可用 |
| [`llm/`](llm/) | 模型、问答、混合检索、不可变知识库快照和 Ollama/llama.cpp 适配 | 可用 |
| [`ui/`](ui/) | 本地 Web UI、问答 REST、诊断运行与 SSE、技能沉淀 | 可用 |
| [`skills/`](skills/) | 网络、磁盘、服务、日志审计 4 个种子技能和现场沉淀技能 | 可用 |
| [`eval/`](eval/) | 技能路由、检索和 P0 问答质量门禁 | 可用 |
| [`tests/`](tests/) | LLM、引擎、安全、HTTP/SSE、双后端与便携包测试 | 可用 |
| [`docs/`](docs/) | 需求文档、前端方案、RAG 技术路线与交接说明 | — |
| [`packaging/`](packaging/) | 无下载便携包构建和四平台/后端实机验收说明 | 待目标机验收 |
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

### 4. 启动 Offline 助手

以下操作均在项目根目录执行。首次使用前，请先按照“快速开始”完成 Python 虚拟环境、项目依赖和知识库索引的初始化；后续启动可直接执行本节步骤。

#### 4.1 确认 Ollama 服务正在运行

通过 Ollama 桌面应用安装时，请保持应用处于运行状态。通过命令行安装时，可在单独的终端窗口中启动服务：

```bash
ollama serve
```

如果系统提示端口 `11434` 已被占用，通常表示 Ollama 已经在后台运行，无需重复启动。

#### 4.2 检查运行环境

macOS / Linux：

```bash
.venv/bin/python -m llm health
```

Windows PowerShell：

```powershell
.venv\Scripts\python -m llm health
```

检查结果中的 `backend_ready`、`model`、`embed_model`、`index` 和 `rag_ready` 应均为 `true`。如果存在未就绪项目，请先根据输出信息检查 Ollama、模型文件或知识库索引。

#### 4.3 启动 Web 服务

macOS / Linux：

```bash
.venv/bin/python -m ui.server --host 127.0.0.1 --port 8765
```

Windows PowerShell：

```powershell
.venv\Scripts\python -m ui.server --host 127.0.0.1 --port 8765
```

服务启动后，在浏览器中访问 [http://127.0.0.1:8765](http://127.0.0.1:8765)。启动终端需要保持运行；如需停止服务，请在该终端中按 `Ctrl+C`。

服务仅监听本机回环地址 `127.0.0.1`，不会向局域网或公网开放。

Offline 助手采用本地 Web 操作台形式运行，静态资源由 Python 服务直接托管，不依赖 Node.js、CDN 或外部网络资源。主对话区域提供以下两种工作模式：

- **手册问答**：连接本地 RAG，从已经建立索引的设备手册中检索答案，并展示对应的文件、章节和页码。
- **故障诊断**：连接本地 `SkillEngine`，根据故障描述匹配排查技能，并执行经过白名单校验的只读采集命令。

执行故障诊断时，需要明确选择“本机只读执行”或“模拟器固定输出”。真实执行失败时，系统不会自动切换到模拟模式。技能包中的修复命令仅作为建议展示，不会由系统自动执行。

诊断完成后，可通过“存为技能”功能将本次流程保存到本机 `skills/` 目录。后端仅接受当前服务生成且已经完成的诊断运行，并会在写入前重新校验命令、规则和出处。

技能包格式参见 [`docs/skill-authoring.md`](docs/skill-authoring.md)；启动参数、目标限制与错误恢复说明参见 [`docs/operations-runbook.md`](docs/operations-runbook.md)。

#### 4.4 处理端口占用

如果端口 `8765` 已被其他程序占用，可指定其他本机端口，例如 `8877`。

macOS / Linux：

```bash
.venv/bin/python -m ui.server --host 127.0.0.1 --port 8877
```

Windows PowerShell：

```powershell
.venv\Scripts\python -m ui.server --host 127.0.0.1 --port 8877
```

更换端口后，请访问 [http://127.0.0.1:8877](http://127.0.0.1:8877)。

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

# 3. 启动完整项目
.venv/bin/python -m ui.server --host 127.0.0.1 --port 8765

# 4. 也可从命令行试用模型/RAG
.venv/bin/python -m llm route "nginx 起不来"
.venv/bin/python -m llm search "怎么检查光模块是不是坏了"
.venv/bin/python -m llm ask "交换机 CPU 占用率高怎么处理"
```

Windows 上把命令里的 `.venv/bin/python` 换成 `.venv\Scripts\python`。

没有模型时可以先用 mock 模式开发界面：`LLM_MOCK=1 .venv/bin/python -m llm ask "随便问"`。
接口的参数、返回格式和配置见 [`llm/README.md`](llm/README.md)。

## 便携离线包

仓库提供 macOS/Windows 启动器，以及 Ollama/llama.cpp 两种后端的无下载组装和 SHA-256 校验脚本。构建过程必须显式传入已准备好的对应平台 Python 运行时、模型后端、模型和已发布知识库：

```bash
python scripts/build_portable.py --help
python scripts/verify_portable.py /path/to/assembled-package
```

详见 [`packaging/README.md`](packaging/README.md)。脚本与本机测试通过不等于 FR-10 已通过；仍需在干净 Windows 10+ / macOS 12+ 上分别验证 Ollama 与 llama.cpp 共四组无网启动。

## 当前结果

| 项目 | 结果 | 条件 |
|---|---|---|
| 技能路由准确率 | 97.7%（85/87），JSON 合法率 100% | Qwen3-8B 基座 + 提示词（Ollama），不微调；MacBook Air M4 16GB |
| 技能路由耗时 | 平均 0.70 秒/条 | 同上 |
| 手册检索 | Hit@1 77%，Hit@3 94%（口语题 Hit@3 91%，FR-2 预设题 100%）；只用 BM25 时为 58% / 74%（口语题 45%） | 《华为 S 系列园区交换机维护宝典》第 25 版，BM25 + bge-m3 混合检索，36 题测试集 |
| 手册检索耗时 | 约 0.05 秒/次 | MacBook Air M4 16GB |
| 浏览器真实手册问答 | 本次验收样例 25.2 秒，返回已核验回答和真实 PDF 出处 | 同上，qwen3:8b；单样例不替代完整性能门禁 |
| 诊断闭环 | 真实白名单采集与 simulation 固件均已接入；规则路径、分级报告、出处和技能沉淀可用 | 本机 macOS 验证 |
| 自动化测试 | 见 `python -m unittest discover -v` 的最新结果 | 不需要外网 |

技能路由的测试集为模板生成的 87 条（测试集中的说法训练与调试时未出现）。手册检索的测试集是调参用的同一批题，没有独立的留出集。两者样本量都小，不代表真实场景的普遍准确率。

## 仍需外部环境完成的验收

- 干净 Windows/macOS × Ollama/llama.cpp 四组无网、非管理员、U 盘路径启动记录。
- 8GB CPU-only 目标机的质量和 30 秒最大耗时复验；若换用 4B/量化模型，必须重跑 `eval/eval_p0_quality.py`。
- FR-1 的物理断网/关 Wi-Fi、出站连接记录，以及 FR-7 的至少 5 条人工逐结论原手册核对。

RAG 的现状、已知问题和接手方法见 [`docs/rag-handoff.md`](docs/rag-handoff.md)。
