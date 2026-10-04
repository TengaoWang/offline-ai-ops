# llm：模型与知识库接口

给引擎（Agent）、界面等模块调用的统一入口。全部在本机运行（Ollama 或 llama.cpp + SQLite），准备完成后不需要联网。

```python
from llm import route, retrieve, ask, answer, chat, health
```

| 函数 | 作用 | 返回 |
|---|---|---|
| `route(描述)` | 根据故障描述选技能包 | `{"skill": "disk-full" 或 None, "latency_s", "raw"}` |
| `retrieve(问题, k=5)` | 在手册里检索最相关的 k 段（不调用大模型，约 0.06 秒） | `[{"id", "text", "file", "page", "section", "label", "score", "vec_score", "bm25_rank", "vec_rank", "mode"}]` |
| `ask(问题, k=5)` | 根据手册回答并附出处；找不到依据就明确说没找到（15 到 50 秒） | `{"answer", "found", "citations": [{"n", "file", "page", "section", "label", "text"}], "unsupported_commands", "latency_s"}` |
| `answer(问题, history=None)` | **完整流程（新增，可选）**：先判断问题类型（打招呼 / 超出范围 / 太笼统 / 手册问题），手册问题先截取原文、再让模型整理回答；回答没通过核对就退回原文 | `{"question", "query", "action", "answer_type", "answer", "citations", "extract", "unsupported_commands", "latency_s"}` |
| `cite(sections, query=None)` | **强制溯源（新增）**：手册章节号（如 `"8.2"`）→ 真实出处；章节号找不到时按 `query` 检索；都找不到返回 `[]`（显示「手册中未找到依据」） | `[{"label", "file", "page", "section", "text", "via"}]` |
| `chat(messages, schema=None, think=False)` | 通用模型调用，例如规则树未覆盖时的「AI 补充推理」 | 回复文本（传 `schema` 时为 JSON 字符串） |
| `health()` | 检查模型后端、模型、向量模型、索引和发布修订是否就绪 | `{"backend", "backend_ready", "model", "embed_model", "index", "index_revision", "chunks", "vectors"}` |

## 该用哪个

- **Agent 排障循环里查手册：用 `retrieve()`**。快（约 0.06 秒），返回的 `label` 可以直接作为 `rag_hit` 的出处。不要在循环里用 `ask()`，它每次要 15 到 50 秒，超过「每轮不超过 30 秒」的要求。
- **界面上的手册问答（场景 C）：用 `ask()`**。它会自己检索、让模型回答，并核对出处。
- **想要更友好的问答：可以换成 `answer()`**（新增，不影响 `ask()`）。打招呼、超出范围的问题约 1 秒返回，太笼统的问题会追问；`answer_stream()` 按步骤产出结果，可以先显示手册原文（约 1 秒），模型整理的回答随后再显示。
- **多轮对话**：`answer(问题, history)` 的 `history` 传之前几轮 `answer()` 的返回值（可以不传）。用户回答追问时（例如先问「s5700」，被追问后说「型号规格」），会合成完整的问题（返回值里的 `query`，如「S5700 的型号规格」）再去查。最多追问一次。

```python
history = []
for question in ["s5700", "型号规格"]:
    result = answer(question, history)
    history.append(result)
```

`answer()` 的 `answer_type`：

| 值 | 含义 | 界面建议 |
|---|---|---|
| `intro` | 打招呼，返回自我介绍 | 直接显示 |
| `out_of_scope` | 和交换机无关 | 直接显示 |
| `clarify` | 问题太笼统，`answer` 是追问 | 显示追问，等用户补充 |
| `generated` | 模型整理的回答，已通过出处和命令核对 | 显示回答和出处 |
| `extracted` | 模型的回答没通过核对，`answer` 是手册原文 | 标明「以下为手册原文」，并显示出处 |
| `not_found` | 手册里没找到相关内容 | 直接显示 |

## 对话里排查现场故障、长期记忆（新增）

`answer()` / `python -m llm answer` 的对话里，可以直接让 AI 动手排查，它会记住现场信息和以前的排查经历：

```text
你：记一下，MES 服务器是 192.168.10.20，接在交换机 GE0/0/8，属于 VLAN 10
答：好的，已记住：…                                  ← 写入长期记忆（answer_type: remembered）

你：MES 服务器连不上了，帮我查一下
【记忆·现场信息】MES 服务器是 192.168.10.20 …       ← 先查长期记忆，参数从记忆里取
▶ 执行技能：网络连通排查（本机命令真实执行，交换机命令读回放）
  $ ping -c 2 -t 2 192.168.10.20  [失败 · 真实执行] …   ← engine：白名单命令 → 规则树 → 手册出处
答（已执行排查）：本次问题与 10月04日 那次一样…      ← 模型结合以前的排查记录总结（answer_type: diagnosed）
诊断报告：🔴 端口 GigabitEthernet0/0/8 的 VLAN 划分错误 [1][2] …

你：交换机 SSH 一直登不上                          ← 只描述现象：照常查手册回答
💡 要我现场排查吗？回复「好」…                      ← 回复「好」就执行「交换机登录排查」
```

- **什么时候执行技能**：调度器多了 `diagnose`、`remember` 两类。只有明确要求动手（「帮我查一下」「排查一下」「体检」等）才执行；只描述现象时仍按手册回答，并提示可以现场排查。这样原来的手册问答不受影响（调度器评测带技能时 48/51，不带时 50/51；多错的两题是「华为交换机」「帮我看看交换机」，应追问却分别当成了打招呼和直接回答）。
- **技能参数**：只接受用户这句话或长期记忆里真实出现过的值（接口简写 GE0/0/8 自动换成 GigabitEthernet0/0/8），模型编造的值丢掉；最终命令还要过白名单。
- **长期记忆**：`kb/memory.db`（检索，bge-m3 向量）+ `kb/memory/*.md`（每条一个文件，可以直接改或删，下次运行自动同步）。`python -m llm memory` 查看，`python -m llm memory forget 3` 删除。不进 git。
- `answer()` 的返回值多了 `skill`、`run`（技能执行结果，和界面诊断流的 done 一样）、`remembered`、`suggest_skill`、`suggestion`；`answer_stream()` 多了 `memory`、`remember`、`skill` 事件。原有字段不变。

## 返回值说明

- `retrieve` 结果按可能性从高到低排，同一小节只保留一段。
  - `label`：可以直接显示的出处，例如 `《华为S系列园区交换机维护宝典》22 TechNotes > 22.28 TechNotes：干道链路 P2274`。
  - `mode`：实际用的检索方式。正常应为 `hybrid`；如果是 `bm25`，说明向量模型或向量没准备好（见下方「准备」），效果会变差。
  - `score`：排序用的分数（hybrid 下是两路名次合并的分数，只用来比大小）；`vec_score` 是向量相似度；`bm25_rank` / `vec_rank` 是在关键词 / 向量检索里各排第几（不在前 20 时为 `None`）。
- `ask` 的出处由程序根据检索结果生成，模型只负责选编号，所以页码和章节不会被编造。
  - `found` 为 `False` 时，`answer` 固定为「手册中未找到依据。」，`citations` 为空。
  - 回答里的每条命令都要能在出处原文里找到（忽略接口号、VLAN 号等数字），找不到就判定为没有依据；这些命令放在 `unsupported_commands` 里，方便排查。
  - `k` 是检索的段数；交给模型前会补上同一小节的相邻段并合并，最多给模型 2 段（`rag.ASK_PASSAGES`），以控制本地 CPU 时延。
- `page` 是 PDF 阅读器里的页码（封面为第 1 页），不是手册页脚印的页码。来自 Markdown / TXT 的片段没有页码，`page` 为 `None`。
- Ollama 没启动或模型没下载时，`route` / `ask` / `chat` 会抛出 `llm.LLMError`，界面可以捕获后提示用户。`retrieve` 在向量模型不可用时不报错，自动退回 BM25。

## 准备（只需一次，需要联网）

```bash
# 1. Ollama 和两个模型
ollama pull qwen3:8b      # 回答用，约 5.2GB；低配电脑可用 qwen3:4b，并设置 LLM_MODEL=qwen3:4b
ollama pull bge-m3        # 向量检索用，约 1.2GB

# 2. Python 依赖
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

# 3. 索引（二选一）
#    a. 推荐：向已经建好索引的队友要 kb/index.db（约 50MB），放到 kb/ 下
#    b. 自己建：把手册 PDF 放进 kb/docs/，然后运行（约 20 分钟，会显示进度）
.venv/bin/python -m llm ingest

# 4. 检查
.venv/bin/python -m llm health
```

`health` 的结果里，`ollama`、`model`、`embed_model`、`index` 都为 `true`，并且 `vectors` 等于 `chunks`（维护宝典是 7091），就说明全部就绪。

## 命令行

```bash
.venv/bin/python -m llm route "nginx 起不来"
.venv/bin/python -m llm search "怎么检查光模块是不是坏了"   # 只检索；列出后输入编号可看全文
.venv/bin/python -m llm ask "S5700 上怎么把 GE0/0/1 配成 trunk 口"
.venv/bin/python -m llm answer "你是谁"                    # 完整流程：先显示原文，再显示整理后的回答
.venv/bin/python -m llm answer                             # 连续对话：记得上一轮，可以回答追问
```

- `search` 列出结果后，输入编号可以查看那一条的全文（含同一小节的前后段，和 `ask` 交给模型的资料一样），直接回车退出；加 `--full` 一次显示全部全文。
- `search` / `ask` 加 `--json` 输出原始数据（和 Python 接口的返回值相同）。
- `ingest` 重建整个索引；`embed [向量模型]` 只给现有索引补算向量。

Windows 上把 `.venv/bin/python` 换成 `.venv\Scripts\python`。

## 没有模型时先开发：mock 模式

设置环境变量 `LLM_MOCK=1`，所有函数返回固定的假数据，不需要 Ollama 和索引，适合先搭界面：

```bash
LLM_MOCK=1 .venv/bin/python -m llm ask "随便问"
```

Windows PowerShell：`$env:LLM_MOCK="1"`。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_MODEL` | `qwen3:8b` | 回答用的模型；低配电脑可改为 `qwen3:4b` |
| `LLM_EMBED_MODEL` | `bge-m3` | 向量模型；设为空字符串则只用 BM25 |
| `LLM_RETRIEVE_MODE` | `hybrid` | `hybrid`（BM25 + 向量）/ `vector` / `bm25` |
| `LLM_BACKEND` | `ollama` | 聊天后端：`ollama` / `llama.cpp` |
| `LLM_EMBED_BACKEND` | 同 `LLM_BACKEND` | 向量后端：`ollama` / `llama.cpp` |
| `OLLAMA_HOST_URL` | `http://127.0.0.1:11434` | Ollama 地址 |
| `LLAMA_CPP_CHAT_HOST` | `http://127.0.0.1:8080` | llama.cpp OpenAI 兼容聊天地址 |
| `LLAMA_CPP_EMBED_HOST` | `http://127.0.0.1:8081` | llama.cpp OpenAI 兼容向量地址 |
| `LLM_DOCS_DIR` | `kb/docs` | 手册目录 |
| `LLM_INDEX_PATH` | `kb/index.db` | 索引文件 |
| `LLM_MOCK` | `0` | `1` 为 mock 模式 |
| `LLM_TIMEOUT` | `180` | 单次后端请求硬超时（秒）；不是 30 秒产品性能门禁 |
| `LLM_NUM_PREDICT` | `512` | 通用模型调用的默认最大生成 token |
| `LLM_QA_NUM_PREDICT` | `256` | 手册问答 JSON 最大生成 token，用于控制响应时延；提示词同时限制正文长度 |
| `LLM_KEEP_ALIVE` | `15m` | Ollama 模型驻留时间 |

## 原理和改进记录

- 技术路线（解析、切块、混合检索、出处保护等每一步怎么做、为什么）：[`docs/rag-plan.md`](../docs/rag-plan.md)
- 交接说明（现状、已知问题、下一步）：[`docs/rag-handoff.md`](../docs/rag-handoff.md)
- 检索评测：[`eval/README.md`](../eval/README.md)

## 目前的限制

- 30 秒是浏览器提交到完整结果可见的产品门禁；`LLM_TIMEOUT` 只是防止后端永久挂起，不能用来证明性能达标。
- 手册里没有的问题，`retrieve` 仍会返回最接近的几段（不会返回空）；拒答由 `ask` 里的模型和命令核对完成。检索阶段的拒答阈值还没做。
- 当前问答会核验引用编号与命令原文；普通文字结论仍需通过独立无答案题集和人工逐结论抽查控制，不能只看“有出处”。
- 检索准确率是在调参用的同一批题上测的（36 题，没有独立的留出集），实际效果可能更低。
- 8GB 内存 + qwen3:4b + bge-m3 同时运行的配置（需求文档的目标机器）还没有测过。
- `route` 用的是基座模型 + 提示词，没有微调；评测结果见 [`eval/README.md`](../eval/README.md)。
