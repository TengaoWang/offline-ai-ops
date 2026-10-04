# 给前端：手册问答新接口 `answer()` 接入说明

| 项目 | 内容 |
|---|---|
| 写给 | 负责界面（`ui/`）的同学 |
| 来自 | 陈文韬（模型与知识库 `llm/`） |
| 日期 | 2026-10-03，10-04 更新（第 11 节：和 Haward 的界面合并后的情况） |
| 代码 | `answer()` 已合进 `main`（PR #3）；第 11 节的内容在 `dev-rag-v2` 分支，尚未合并 |

---

## 1. 先说结论

- **现在的界面不用改，也不会坏。** `ui/server.py` 调用的 `ask()`、`route()`、`health()`、`chat()`、`ingest()` 都没变，`/api/ask` 返回的字段和以前完全一样（已启动界面服务实测过）。
- **新增了一个可选接口 `answer()`**，比 `ask()` 体验更好。要不要换、什么时候换，由你决定。
- 如果要换，后端只需在 `ui/server.py` 里加一个接口（约 10 行），前端按 `answer_type` 分几种情况显示即可。下面给了可以直接参考的代码。
- **10-04 更新**：一键体检已经用上陈文韬的技能和引擎（Haward 的界面不用改）；`answer()` 可选打开对话里排查和长期记忆。详见文末第 11 节。

## 2. `answer()` 比 `ask()` 好在哪

| 用户输入 | 现在的 `ask()` | 新的 `answer()` |
|---|---|---|
| 你是谁 | 等 21 秒，回答「手册中未找到依据」 | **约 2 秒**，自我介绍 |
| MySQL 主从复制怎么配置 | 等 20 秒以上，回答「手册中未找到依据」 | **约 2 秒**，说明只能回答交换机问题 |
| s5700（太笼统） | 等 10 秒，回答「手册中未找到依据」 | **约 3 秒**，追问：「想了解配置、故障排查、维护操作还是设备信息？」 |
| 用户接着回「型号规格」 | 当成新问题，接不上 | 理解为「S5700 的型号规格」，直接查手册 |
| 正常的手册问题 | 20 到 40 秒后才有内容 | 手册原文**约 1 秒**就能先显示（用流式接口时），整理后的回答随后显示 |
| 模型没把握 / 出错 | 「手册中未找到依据」 | 退回显示**手册原文**，并标明是原文 |

## 3. 返回值

```python
from llm import answer
result = answer("S5700 上怎么把 GE0/0/1 配成 trunk 口？", history=[])
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `question` | str | 用户原话 |
| `query` | str | 结合上下文后的完整问题（多轮对话时可能和原话不同，可显示为「理解为：…」） |
| `action` | str | `greet` / `reject` / `clarify` / `answer` |
| `answer_type` | str | 决定怎么显示，见第 4 节 |
| `answer` | str | 显示给用户的文字（可能有多行，含 `\n`） |
| `citations` | list | 出处，格式和 `ask()` 一样：`[{n, file, page, section, label, text}]`；`n` 和回答里的 `[1]` `[2]` 对应 |
| `extract` | dict 或 null | 截取的手册原文 `{text, file, page, section, label}`；只有查了手册时才有 |
| `unsupported_commands` | list | 排查用：模型回答里在手册中找不到的命令（一般不用显示） |
| `latency_s` | float | 耗时（秒） |
| `skill` | str 或 null | （10-04 新增）执行的技能 ID，只有 `diagnosed` 时有 |
| `run` | dict 或 null | （10-04 新增）技能执行结果，和一键体检诊断流 `done` 事件的数据**完全一样**（commands / rules / findings / unresolved / elapsed） |
| `remembered` | list | （10-04 新增）这一轮写入长期记忆的内容 `[{id, kind, text, …}]` |
| `suggest_skill` / `suggestion` | str 或 null | （10-04 新增）用户描述了故障但没要求动手查时，建议的技能和一句提示语（「要我现场排查吗？回复「好」…」） |

### 真实返回示例

**打招呼**（1.9 秒）

```json
{"question": "你是谁", "query": "你是谁", "action": "greet", "answer_type": "intro",
 "answer": "我是离线机房运维助手，根据《华为S系列园区交换机维护宝典》回答华为交换机的配置、维护和故障排查问题，全程不联网。可以试试问：接口 down 怎么排查、怎么把端口加入 VLAN、CPU 占用率高怎么处理。",
 "citations": [], "extract": null, "unsupported_commands": [], "latency_s": 1.941}
```

**追问**（3.5 秒）

```json
{"question": "s5700", "query": "S5700", "action": "clarify", "answer_type": "clarify",
 "answer": "您是想了解 S5700 的哪些信息呢？例如：配置、故障排查、维护操作还是查看设备信息？",
 "citations": [], "extract": null, "unsupported_commands": [], "latency_s": 3.48}
```

**超出范围**（2.0 秒）

```json
{"question": "MySQL 主从复制怎么配置", "query": "MySQL 主从复制怎么配置", "action": "reject",
 "answer_type": "out_of_scope",
 "answer": "这个问题不在交换机维护手册的范围内。我只能回答华为 S 系列交换机的配置、维护和故障排查问题，例如：接口 down 怎么排查、怎么配置 trunk、怎么查看日志。",
 "citations": [], "extract": null, "unsupported_commands": [], "latency_s": 2.049}
```

**手册问题，回答通过核对**（26 秒；`text` 已截短）

```json
{"question": "S5700 上怎么把 GE0/0/1 配成 trunk 口？", "query": "S5700 上怎么把 GE0/0/1 配成 trunk 口？",
 "action": "answer", "answer_type": "generated",
 "answer": "1. 进入接口视图。\n[Switch] interface GigabitEthernet 0/0/1\n2. 设置接口链路类型为Trunk。\n[Switch-GigabitEthernet0/0/1] port link-type trunk\n3. 配置允许通过的VLAN。\n[Switch-GigabitEthernet0/0/1] port trunk allow-pass vlan 2\n…",
 "citations": [{"n": 1, "file": "华为S系列园区交换机维护宝典.pdf", "page": 2274,
                "section": "22 TechNotes > 22.28 TechNotes：干道链路",
                "label": "《华为S系列园区交换机维护宝典》 22 TechNotes > 22.28 TechNotes：干道链路 P2274",
                "text": "[SwitchB] interface GigabitEthernet 0/0/1\n…"}],
 "extract": {"text": "[SwitchB] interface GigabitEthernet 0/0/1\n…", "page": 2274, "label": "…", "file": "…", "section": "…"},
 "unsupported_commands": [], "latency_s": 25.989}
```

## 4. 按 `answer_type` 显示

| `answer_type` | 含义 | 建议显示 |
|---|---|---|
| `intro` | 打招呼 | 普通气泡，显示 `answer` |
| `out_of_scope` | 和交换机无关 | 普通气泡（或灰色提示），显示 `answer` |
| `clarify` | 问题太笼统 | 显示 `answer`（追问），等用户回复；**下一次请求要带上 `history`** |
| `generated` | 模型整理的回答，已核对出处和命令 | 标题「回答」，显示 `answer`，下方列 `citations`（`label` + 可展开的 `text`） |
| `extracted` | 模型没给出有依据的回答，`answer` 是**手册原文** | 标题「以下为手册原文，请自行判断」，用引用样式显示 `answer`，下方显示出处 |
| `not_found` | 手册里没找到相关内容 | 沿用现在「手册中未找到依据」的样式 |
| `diagnosed` | （10-04 新增）已执行排查技能 | 显示 `answer`（总结 + 文字版报告）；想要和一键体检一样的卡片，直接用 `run` 调现有的 `renderReport(run)` / `renderRules(run.rules)` |
| `remembered` | （10-04 新增）记住了用户说的现场信息 | 普通气泡，显示 `answer` |

`suggestion` 不为空时，在回答下面加一行提示（或一个「开始排查」按钮，点击等于发送「好」）。

小建议：
- `query` 和 `question` 不同时，可以在问题下方显示一行小字「理解为：S5700 的型号规格」，让用户知道系统怎么理解的。
- `answer` 里有 `\n`，现在 `askManual()` 用 `<p>` 显示会挤成一行，建议加 `white-space: pre-wrap`。
- 回答里的 `[1]` `[2]` 和 `citations[].n` 对应，可以做成点击跳到对应出处。

## 5. 多轮对话：`history`

`history` 是**之前几轮 `answer()` 的返回值组成的列表**（原样回传即可）。后端只看最近两轮，用每一轮的 `question`、`action`、`answer`，以及（10-04 新增）`query`、`suggest_skill`：用户回答「好」时，靠上一轮的 `suggest_skill` 知道要执行哪个技能。**请一起存下来**，否则「回复好就排查」不生效。

```js
// 前端：每个对话保存一份 history，新建对话时清空
state.qaHistory = state.qaHistory || [];
const result = await api("/api/answer", {
  method: "POST",
  body: JSON.stringify({ question, history: state.qaHistory.slice(-2) }),
});
state.qaHistory.push({ question: result.question, query: result.query, action: result.action,
                      answer: result.answer, suggest_skill: result.suggest_skill });
```

- 不传 `history`（或传 `[]`）时，就是单轮问答，和 `ask()` 一样独立。
- 系统最多连续追问一次：上一轮已经追问过，这一轮一定会去查手册。

## 6. 后端怎么加接口（`ui/server.py`）

### 方式一：普通接口（最简单）

```python
from llm import SKILLS, answer, ask, chat, config, health, ingest, route   # 第 21 行加上 answer

# do_POST 里，紧挨着 /api/ask 加：
elif parsed.path == "/api/answer":
    payload = self._read_json_body()
    question = str(payload.get("question", ""))
    history = payload.get("history") or []
    self._send_json(answer(question, history))
```

前端照着现在的 `askManual()` 改一份即可：把 `/api/ask` 换成 `/api/answer`，按第 4 节的 `answer_type` 显示。

### 方式二：流式接口（原文先显示，体验更好）

`answer_stream()` 按步骤产出三种事件：

| 事件 | 时间 | 内容 |
|---|---|---|
| `dispatch` | 约 2 秒 | `{action, query}`：判断出的问题类型 |
| `extract` | 约 3 秒（只有查手册时才有） | `{extract: {text, label, page, …}}`：手册原文，**可以先显示** |
| `final` | 打招呼等 2 到 4 秒；查手册 20 到 40 秒 | 和 `answer()` 的返回值完全一样 |

服务端已经有 `_send_sse()` 和诊断流的写法，可以照着加：

```python
from llm import answer_stream

# do_GET 里加：
elif parsed.path == "/api/answer/stream":
    query = urllib.parse.parse_qs(parsed.query)
    question = query.get("question", [""])[0]
    history = json.loads(query.get("history", ["[]"])[0])
    self._answer_stream(question, history)

# UIHandler 里加一个方法：
def _answer_stream(self, question: str, history: list) -> None:
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    try:
        for event in answer_stream(question, history):
            name = event.pop("event")
            self._send_sse(name, event)
    except Exception as exc:
        self._send_sse("error", {"error": str(exc)})
```

```js
// 前端
const url = "/api/answer/stream?question=" + encodeURIComponent(question)
          + "&history=" + encodeURIComponent(JSON.stringify(state.qaHistory.slice(-2)));
const source = new EventSource(url);
source.addEventListener("extract", (e) => showExcerpt(JSON.parse(e.data).extract));   // 先显示原文
source.addEventListener("final", (e) => { showAnswer(JSON.parse(e.data)); source.close(); });
source.addEventListener("error", () => source.close());
```

注意：`EventSource` 只能用 GET，所以 `history` 放在网址参数里；只传最近两轮的 `question`、`query`、`action`、`answer`、`suggest_skill`，不会太长。

（10-04 新增）流式接口多了三种事件，不处理也不影响 `final`：

| 事件 | 内容 | 建议 |
|---|---|---|
| `memory` | `{facts, episodes}`：长期记忆里和这句话相关的内容 | 可以显示一行小字「想起了：MES 服务器是 192.168.10.20…」 |
| `remember` | `{memories}`：这句话里刚记住的现场信息 | 可以显示「已记住：…」 |
| `skill` | `{name, data}`：排查技能执行的每一步，`name` 是 `start` / `collect` / `rules` / `ai` / `report` / `done`，`data` 和一键体检诊断流的同名事件**完全一样** | 直接复用一键体检的 `appendCommand(data)`、`renderRules(data.rules)`、`renderReport(data)` |

```js
source.addEventListener("skill", (e) => {
  const { name, data } = JSON.parse(e.data);
  if (name === "collect") appendCommand(data);          // 每条命令和原始输出
  if (name === "rules") renderRules(data.rules);         // 规则树路径
  if (name === "report") renderReport(data);             // 分级报告 + 出处
});
```

## 7. 出错和特殊情况

| 情况 | 表现 | 建议 |
|---|---|---|
| Ollama 没启动 | `answer()` 在调度那一步抛出 `LLMError`；`/api/answer` 会返回 500 和 `{"error": "连不上 Ollama…"}`（`do_POST` 已经统一处理） | 沿用现在「本机服务不可用」的提示 |
| 已经截取到原文后，模型出错 | 不报错，返回 `answer_type: "extracted"`（手册原文） | 按 `extracted` 显示 |
| Mock 模式（`LLM_MOCK=1`） | 也能用：问句含「你好、你是谁」等返回 `intro`，其他返回 mock 的手册回答 | 可以先在没有模型的电脑上把界面做出来 |
| 空问题 | 没有专门处理，结果不确定 | 前端直接拦住空输入，不要发请求 |

## 8. 耗时参考

MacBook Air M4 16GB，qwen3:8b；有独立显卡的 Windows 电脑会快一些。

| 情况 | 耗时 |
|---|---|
| 打招呼、超出范围、追问 | 2 到 4 秒 |
| 手册原文（流式接口的 `extract` 事件） | 约 3 秒 |
| 手册问题的最终回答 | 20 到 40 秒 |
| 模型刚启动、第一次调用 | 再多 10 秒左右 |

请求超时建议设成 120 秒以上（和 `LLM_TIMEOUT` 一致）。

## 9. 自测清单

接好后可以用这些输入检查：

| 输入 | 预期 `answer_type` |
|---|---|
| 你好 | `intro` |
| MySQL 主从复制怎么配置 | `out_of_scope` |
| s5700 → 再输入「型号规格」 | `clarify` → `generated`（`query` 为「S5700 的型号规格」） |
| S5700 上怎么把 GE0/0/1 配成 trunk 口？ | `generated`，出处 22.28 P2274 |
| 光模块插上了但是端口不亮 | `extracted`（手册原文） |
| 记一下，MES 服务器是 192.168.10.20，接在 GE0/0/8，属于 VLAN 10 | `remembered`（10-04 新增） |
| MES 服务器连不上了，帮我查一下 | `diagnosed`，`run.findings[0]` 为「端口 GigabitEthernet0/0/8 的 VLAN 划分错误」（10-04 新增） |
| 交换机 SSH 一直登不上 → 再输入「好」 | `generated` 且 `suggestion` 不为空 → `diagnosed`（10-04 新增） |

也可以先在命令行看效果：`python -m llm answer`（连续对话模式），或 `python -m llm answer "问题" --json` 看原始返回值。

## 10. 相关文档

- 接口完整说明：[`llm/README.md`](../llm/README.md)
- 技术路线（调度器、原文截取、审核的原理）：[`rag-plan.md`](rag-plan.md)
- 交接说明：[`rag-handoff.md`](rag-handoff.md)

## 11. 10-04 更新：和 Haward 的界面合并后

`main` 上 Haward 的界面（`ui/service.py`）通过 `engine.SkillEngine` 调用诊断引擎。合并后：

| 部分 | 现在用的是 | 界面要不要改 |
|---|---|---|
| 技能内容（`skills/`） | 陈文韬的 4 个交换机技能（网络连通、Flash 存储空间、SSH 登录、日志审计），交换机命令的回放数据取自手册示例 | 不用 |
| 引擎（`engine/`） | 陈文韬的引擎；`engine/skill_engine.py` 提供和原来一样的 `SkillEngine` 接口（`list_skills` / `run` / `save_skill`、`loader.load`、`EngineError`、`SkillValidationError`） | 不用 |
| 一键体检 `real` 模式 | 本机命令（Windows：`ping -n`、`ipconfig`；macOS：`ping -c`、`ifconfig`、`netstat -rn`）真实执行；交换机命令（`display …`）读回放，输出第一行写明出自手册哪一页 | 不用 |
| 一键体检 `simulation` 模式 | 全部命令读回放 | 不用 |
| 事件和字段 | `start / collect / rules / ai / report / done`，字段和原来一样（`run_id`、`collected`、`rule_path`、`timing`、`display`、`duration_s` 等），另外多了 `mode`（live / replay）、`replay_source`、`finding_id` | 不用 |
| 出处 | 技能里写章节号，由 `llm.cite()` 查出真实页码；没有依据的结论标「手册中未找到依据」，不隐藏 | 不用 |
| 主对话 `/api/ask` | 传 `agent_mode: true`，支持记忆、排障建议和明确要求时执行技能 | 已接入 |
| 独立知识问答 `/api/ask` | 传 `agent_mode: false`，保持纯 RAG，不执行技能、不读写记忆 | 已接入 |
| 长期记忆 | `GET /api/memory` 展示，`DELETE /api/memory/{id}` 删除 | 已接入 |
| 命令模拟器 | `POST /api/simulator/check` 调用后端白名单，仅返回固定样例、不执行命令 | 已接入 |

### 已接入：问答里排查 + 长期记忆

网页主对话已经通过服务层用下面的方式调用：

```python
result = answer(question, history=..., locale=locale, diagnose=True)
```

此时会多出两种 `answer_type`：
- `diagnosed`：已执行技能，`run` 是完整的执行结果，可以直接用一键体检的渲染函数显示；
- `remembered`：已记住现场信息。

还会多出 `suggestion` 字段（「要我现场排查吗？回复『好』…」）。`history` 会保存 `query`、`suggest_skill` 两个字段（第 5 节）。长期记忆存在本机 `kb/memory.db` 和 `kb/memory/*.md`，也可在前端「长期记忆」页查看和删除。

有问题找陈文韬。
