# RAG 交接说明

写给要调用或接手手册检索 / 问答（`llm/` 里的 `retrieve`、`ask`）的队友。读完这一份就能用、能改；想知道每一步为什么这么做，再看 [`rag-plan.md`](rag-plan.md)。

| 项目 | 内容 |
|---|---|
| 负责人 | 陈文韬 |
| 代码 | 已合进 `main`；开发分支 `dev-rag-v2` |
| 更新日期 | 2026-10-03 |

---

## 1. 一句话说明

在《华为 S 系列园区交换机维护宝典》（2504 页）里，用**关键词（BM25）+ 向量（bge-m3）混合检索**找到相关段落；问答时让本地的 Qwen3-8B 只根据这些段落回答，**出处由程序生成，回答里的命令逐条核对原文，没有依据就拒答**。全部离线运行。

## 2. 现在做到哪了

| 能力 | 状态 |
|---|---|
| 检索准确率（36 题测试集） | Hit@1 77%，Hit@3 94%；口语题 Hit@3 91%；FR-2 预设题 100% |
| 出处 | 章节和页码由程序生成，按章节切块后章节名准确 |
| 手册里没有的问题 | `ask` 能拒答（测过 Windows、MySQL、AR2200、Linux 等） |
| 编造的命令 | `ask` 会拦下（命令在出处原文里找不到就拒答） |
| 检索耗时 | 约 0.05 秒 |
| **问答耗时** | **15 到 50 秒，还没达到「每轮 30 秒以内」** |

数字的前提：测试集也是调参用的那批题（没有留出集），标准答案由 Claude 起草、尚未由人逐题核对，题量小。**当作趋势看，不要当作精确值。**

## 3. 队友怎么用

**Agent（成员 B）**：在排障循环里用 `retrieve()`，不要用 `ask()`（太慢）。

```python
from llm import retrieve

hits = retrieve("S5700 端口 VLAN 配置 排障", k=3)
for h in hits:
    step = {"type": "rag_hit", "source": h["label"], "snippet": h["text"][:300]}
```

**界面（成员 D）**：手册问答用 `ask()`；先用 `health()` 判断环境是否就绪。

```python
from llm import ask, health, LLMError

try:
    r = ask("S5700 上怎么把 GE0/0/1 配成 trunk 口？")
    # r["answer"]、r["citations"][i]["label"]；r["found"] 为 False 时 answer 是「手册中未找到依据。」
except LLMError as e:
    ...  # Ollama 没启动或模型没下载，提示用户
```

**可选：完整问答流程 `answer()`**（新增，`ask()` 不变）。先判断问题类型：打招呼就自我介绍、和交换机无关就说明范围、太笼统就追问（约 1 到 4 秒）；手册问题先截取原文（约 1 秒），再给模型整理的回答，没通过核对就退回原文。支持多轮对话。

```python
from llm import answer

history = []
for q in ["s5700", "型号规格"]:      # 第二句会被理解为「S5700 的型号规格」
    r = answer(q, history)
    history.append(r)
    # r["answer_type"]：intro / out_of_scope / clarify / generated / extracted / not_found
```

界面要不要从 `ask()` 换成 `answer()`，由界面负责人决定；不换不影响现有功能。

完整的参数和返回字段见 [`llm/README.md`](../llm/README.md)。

## 4. 上手清单

1. 拉代码：在 `main` 上 `git pull`
2. 装依赖（新增了 numpy）：`uv pip install --python .venv/bin/python -r requirements.txt`
3. 下模型：`ollama pull qwen3:8b`、`ollama pull bge-m3`
4. 拿索引：向陈文韬要 `kb/index.db`（约 50MB），放到 `kb/` 下。也可以把手册 PDF 放进 `kb/docs/` 后运行 `.venv/bin/python -m llm ingest` 自己建（约 20 分钟）
5. 检查：`.venv/bin/python -m llm health`，应该是 `ollama`、`model`、`embed_model`、`index` 都为 `true`，`chunks` 和 `vectors` 都是 7091
6. 试一下：`.venv/bin/python -m llm search "怎么检查光模块是不是坏了"`，再加 `--json`，确认结果里 `"mode": "hybrid"`

**最常见的坑**：`mode` 是 `bm25` 而不是 `hybrid`。原因是没下载 `bge-m3`、Ollama 没启动，或者 `index.db` 是旧的（没有向量）。这时功能还能用，但口语问题的准确率会从 91% 掉到 45% 左右，而且**不会报错**，所以第 5、6 步一定要做。

## 5. 代码地图

| 文件 | 内容 | 要改什么时看这里 |
|---|---|---|
| `llm/rag.py` | 解析、切块、建索引、检索、问答、出处核对，全部在这里 | 几乎所有 RAG 改动 |
| `llm/qa.py` | 完整问答流程 `answer()`：调度器、原文截取、审核、多轮对话 | 改问题分类、追问、截取规则 |
| `llm/__main__.py` | 命令行（`search` / `ask` / `answer` 的显示格式、看全文、连续对话） | 只影响命令行显示 |
| `llm/config.py` | 环境变量配置 | 换模型、换索引路径 |
| `llm/client.py` | 调用 Ollama（`chat`、`embed`），只用标准库 | 一般不用动 |
| `llm/__init__.py` | 对外接口、`health()` | 加新接口 |
| `tests/test_llm.py` | 36 项单元测试，不需要 Ollama | 每次改完都跑 |
| `eval/eval_retrieval.py`、`eval/retrieval_cases.jsonl` | 检索评测和测试集 | 改检索后跑，加新题 |
| `eval/eval_dispatch.py`、`eval/dispatch_cases.jsonl` | 调度器评测（51 题，98%） | 改调度器提示词后跑 |

`llm/rag.py` 按流程从上到下排列：

| 位置 | 函数 | 做什么 |
|---|---|---|
| 开头 | 常量 | 段长 `CHUNK_CHARS=600`、向量权重 `VECTOR_WEIGHT=2`、给模型几段 `ASK_PASSAGES=3`、回答提示词 `ANSWER_PROMPT` 等，**调参先看这里** |
| 建索引 | `_pdf_lines` → `_pdf_sections` → `_chunk_lines` → `ingest` → `build_vectors` | 去页眉页脚 → 按书签切小节 → 切成段 → 写 BM25 索引 → 算向量 |
| 检索 | `_bm25_ranking`、`_vector_ranking` → `retrieve` | 两路各取前 20 → 加权 RRF 合并 → 同一小节只留一段 |
| 问答 | `_with_neighbors` → `ask` → `_unsupported_commands` | 补相邻段 → 模型回答 → 核对命令、修正或拒答 |

## 6. 改完怎么验证

```bash
.venv/bin/python -m unittest discover -s tests -t .                  # 1. 单元测试，几秒
.venv/bin/python eval/eval_retrieval.py --tag 我的改动 --mode hybrid   # 2. 检索评测，几秒
.venv/bin/python -m llm ask "S5700 上怎么把 GE0/0/1 配成 trunk 口？"   # 3. 抽几道题手动看回答
```

改了检索就对比第 2 步的 Hit@1、Hit@3 和口语题，不能比当前差（77% / 94% / 91%）。

**改了切块（`CHUNK_CHARS`、`_pdf_sections` 等）要重建索引并重算向量（约 20 分钟）**。建议用 `LLM_INDEX_PATH=kb/index-test.db .venv/bin/python -m llm ingest` 建到另一个文件，评测时也带上同样的环境变量，确认更好再替换 `kb/index.db`。

## 7. 已知问题和限制

| 问题 | 影响 | 说明 |
|---|---|---|
| `ask` 慢（15 到 50 秒） | 超过需求文档的 30 秒 | 模型读 3 段资料（每段可能上千字）；模型冷启动还要再加十几秒 |
| 检索不会返回「没有」 | 手册里没有的问题，`retrieve` 也会返回最接近的几段 | 拒答靠 `ask` 里的模型和命令核对。向量相似度单独分不开两类题（无答案题最高 0.623，可回答题最低 0.620），所以不能只用阈值 |
| 文字建议查不出来 | 回答里没有出处的文字（例如「去使能 STP」）拦不住 | 命令核对只检查命令 |
| 命令核对的盲区 | 整行英文、以大写字母开头的内容会被当作设备输出跳过；只有一个词的命令（如 `save`、`quit`）不检查 | — |
| 模型有时过于保守 | 「光模块插上了但是端口不亮」检索找到了相关内容，模型却拒答 | 误拒率还没统计 |
| 问句里的虚词 | 「是不是」「了」等会当成关键词，偶尔带来噪音 | 还没做停用词 |
| 8GB 机器没测过 | 需求文档的目标机器（8GB 内存，qwen3:4b + bge-m3 同时运行）效果未知 | — |
| 只支持这一本手册的书签结构 | 其他手册的页眉页脚、书签格式可能不同 | 换手册要先检查切块结果 |

## 8. 下一步（按优先级）

1. **提速**：先测时间花在哪（检索、模型加载、模型生成）；可以试 `num_predict` 限制回答长度、`keep_alive` 让模型常驻内存、截短每段资料、改用 qwen3:4b。
2. **检索阶段拒答**：只有关键词命中、没有向量支持的结果降权；补 5 到 10 道无答案题，再定阈值。
3. **端到端问答评测**：给每道题写「回答里必须包含的命令」（例如 trunk 题必须有 `port link-type trunk`），跑 `ask` 统计正确率、误拒率、耗时。
4. 问句停用词；向量缓存（重建索引时只算变了的段）。
5. 在 8GB 内存 + qwen3:4b 的配置下测一次。

## 9. 更多资料

| 文档 | 内容 |
|---|---|
| [`rag-plan.md`](rag-plan.md) | 技术路线：每个环节怎么做、为什么 |
| [`llm/README.md`](../llm/README.md) | 接口说明、配置、命令行 |
| [`eval/README.md`](../eval/README.md) | 评测方法和结果 |
| `rag-notes` 分支的 `docs/rag-worklog.md`、`docs/rag-issues.md` | 开发过程的逐条记录（每次改动和评测结果）、遇到的问题和解决办法 |
