# eval：评测

两部分：

- [技能路由评测](#技能路由评测)：`llm.route()` 能否根据故障描述选对技能包
- [手册检索评测](#手册检索评测)：`llm.retrieve()` 能否把正确的章节排在前面
- [调度器评测](#调度器评测)：`llm.answer()` 的第一步能否分清打招呼、超出范围、太笼统和手册问题

## 技能路由评测

评测 `llm.route()` 能否根据用户对故障的描述选对技能包。

| 用户说 | 输出 |
|---|---|
| MES 连不上数据库了，网关能 ping 通 | `{"skill": "net-unreachable"}` |
| df -h 看到 /var 用了 98% | `{"skill": "disk-full"}` |
| nginx 起不来 | `{"skill": "service-down"}` |
| 帮我看看最近有没有异常登录 | `{"skill": "log-audit"}` |
| 打印机卡纸了 | `{"skill": null}` |

### 结果

| 模型 | 准确率（87 条） | JSON 合法率 | 平均耗时 |
|---|---|---|---|
| Qwen3-8B 基座 + 提示词（Ollama） | **97.7%** | 100% | 0.70 秒 |

在 MacBook Air M4 16GB 上测得。准确率已超过事先定的 90% 门槛，因此**不做微调**，只用提示词。
错的 2 条是同一句话（「应用日志一直报连接数据库失败，mysql 进程不见了」被选成 `log-audit`），这句话本身也有歧义。

### 运行

需要本机 Ollama 已运行并下载 `qwen3:8b`（见项目根目录 README）。

```bash
.venv/bin/python eval/gen_data.py      # 生成测试数据到 eval/data/
.venv/bin/python eval/eval_route.py    # 评测，结果写入 eval/results/qwen3-8b.json
```

换模型对比：`.venv/bin/python eval/eval_route.py --model qwen3:4b --tag qwen3-4b`。

### 测试数据

- 每个技能 26 到 30 个「基础说法」（普通话、粤语、英文、中英混杂），替换 IP、服务名、分区等槽位，再加上「急！」「点算」之类的前后缀。
- 按基础说法划分数据集：测试集里的说法不会出现在其他数据中，测出来的准确率代表对新说法的泛化能力。
- 测试题由模板生成，比真实用户的说法规整，样本量也小，实际准确率可能更低。

补充说法或技能：编辑 `gen_data.py` 的 `TEMPLATES`；技能列表和提示词的唯一来源是 `llm/router.py` 的 `SKILLS` 和 `SYSTEM_PROMPT`。改完后重新生成数据并评测。

## 手册检索评测

评测 `llm.retrieve()` 在《华为 S 系列园区交换机维护宝典》上的检索效果。不调用大模型，几秒钟跑完。

### 测试集 `retrieval_cases.jsonl`

36 道题，每道题的标准答案写的是手册章节号（如 `"8"`、`"22.46"`），脚本按 PDF 书签换成页码范围；检索结果里任意一段的页码落在范围内就算命中。

| 类型 | 数量 | 例子 |
|---|---|---|
| `fr2` 需求文档 FR-2 的预设题 | 5 | S5700 上怎么把 GE0/0/1 配成 trunk 口？ |
| `agent` Agent 在排障循环里发出的查询 | 5 | S5700 端口 VLAN 配置 排障 |
| `formal` 书面说法 | 10 | 接口物理状态 DOWN 的常见原因和处理步骤 |
| `colloquial` 口语说法（前 10 道和书面题逐题对应） | 11 | 网口灯不亮，网线插上也没反应 |
| `unanswerable` 手册里没有的 | 5 | Windows 电脑怎么重装系统（不计入命中率） |

### 结果（31 道可回答的题）

| 检索方式 | Hit@1 | Hit@3 | Hit@5 | MRR | 口语题 Hit@3 | FR-2 Hit@3 | 耗时 p50 |
|---|---|---|---|---|---|---|---|
| 只用 BM25 | 58% | 74% | 81% | 0.68 | 45% | 80% | 0.006 秒 |
| **混合（BM25 + bge-m3，向量权重 2，默认）** | **77%** | **94%** | **97%** | **0.86** | **91%** | **100%** | 0.045 秒 |

注意：

- 这是**调参用的同一批题**：向量权重、切块方式都是看这批题的结果选的，部分标准答案（SSH 题、光模块题）也是看到检索结果后补充的，没有独立的留出集，实际效果可能更低。
- 标准答案由 Claude 按手册目录起草，尚未由人逐题核对。
- 题量小，一道题就是约 3 个百分点。

### 运行

需要索引已建好、`bge-m3` 已下载（见 [`llm/README.md`](../llm/README.md)）。

```bash
.venv/bin/python eval/eval_retrieval.py --tag hybrid --mode hybrid     # 默认方式
.venv/bin/python eval/eval_retrieval.py --tag bm25 --mode bm25         # 只用关键词，对照
```

终端会列出每道题排第几（「未中」表示前 10 名都没有），最后是汇总；完整结果（每道题的前 3 名）写入 `eval/results/retrieval-<tag>.json`（不进 git）。

加题：在 `retrieval_cases.jsonl` 里加一行，`gold` 写手册章节号。真实用户问过、答错的问题最值得加。

## 调度器评测

`llm.qa.dispatch()` 把问句分成四类：`greet`（打招呼）、`reject`（和交换机无关）、`clarify`（太笼统，要追问）、`answer`（去手册里查）。

测试集 `dispatch_cases.jsonl` 共 51 道：检索测试集里的 36 道（能回答的应判为 `answer`，手册里没有的应判为 `reject`），加上打招呼 6 道、太笼统 6 道、实际测试中遇到的 3 道。

| 类别 | 正确 |
|---|---|
| 手册问题 → `answer` | 33/33（**没有手册问题被误拦**） |
| 超出范围 → `reject` | 6/6 |
| 打招呼 → `greet` | 5/6（「你是哪家公司做的」判成了 `reject`） |
| 太笼统 → `clarify` | 6/6 |
| 总计 | 50/51（98%），平均 2.2 秒/条（Qwen3-8B，MacBook Air M4） |

最要紧的是「手册问题被误拦」（判成 `reject` / `clarify` / `greet`），脚本单独统计为 `answer_blocked`。题量小，打招呼和太笼统的题是自己写的，没有留出集。

```bash
.venv/bin/python eval/eval_dispatch.py      # 需要 Ollama 和 qwen3:8b，约 2 分钟
```
