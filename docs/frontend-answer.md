# 给前端：手册问答新接口 `answer()` 接入说明

| 项目 | 内容 |
|---|---|
| 写给 | 负责界面（`ui/`）的同学 |
| 来自 | 陈文韬（模型与知识库 `llm/`） |
| 日期 | 2026-10-03，10-04 更新（新增第 11 节：对话里排查和长期记忆、技能引擎的接口） |
| 代码 | `answer()` 已合进 `main`（PR #3）；第 11 节的内容在 `dev-rag-v2` 分支，尚未合并 |

---

## 1. 先说结论

- **现在的界面不用改，也不会坏。** `ui/server.py` 调用的 `ask()`、`route()`、`health()`、`chat()`、`ingest()` 都没变，`/api/ask` 返回的字段和以前完全一样（已启动界面服务实测过）。
- **新增了一个可选接口 `answer()`**，比 `ask()` 体验更好。要不要换、什么时候换，由你决定。
- 如果要换，后端只需在 `ui/server.py` 里加一个接口（约 10 行），前端按 `answer_type` 分几种情况显示即可。下面给了可以直接参考的代码。
- **10-04 更新**：`answer()` 的对话里可以直接排查现场故障，并有长期记忆；新增了技能引擎的接口（一键体检可以接真实执行）。**`ui/` 一行没改，原有接口和字段都没删、没改名，只是新增**，详见文末第 11 节。

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

## 11. 10-04 更新：新增的接口（`ui/` 一行没改）

**`ui/` 目录完全没动，现在的界面照常运行，不会坏。** 下面都是新增的 Python 接口，要不要接、什么时候接，由你决定。接法都给了参考代码（在我本地的服务副本上实测过）。

| 接口 | 作用 | 对应界面功能 |
|---|---|---|
| `llm.answer()` / `llm.answer_stream()` | 对话：手册问答 + **现场排查**（`diagnosed`）+ **长期记忆**（`remembered`） | 知识问答 / 诊断对话框 |
| `engine.runner.run_skill(skill_id)` | 真实执行技能，产出的事件和字段**和 `DEMO_RUNS` 演示流完全一样** | 一键体检 |
| `engine.loader.list_skills()` | 扫描 `skills/`，返回技能名称、描述、能否执行 | 技能列表 |
| `engine.skillgen.build(name, run)` | 把一次执行结果存成可以直接执行的新技能目录 | 存为技能 |
| `llm.cite(sections, query)` | 手册章节号 → 真实页码和原文 | 出处 |

### 11.1 对话里排查 + 长期记忆：加第 6 节的 `/api/answer` 就自动有

- 「MES 服务器连不上了，帮我查一下」→ `answer_type: diagnosed`，`run` 里是完整的执行结果（命令、规则路径、报告），可以直接用现有的 `renderRules(run.rules)`、`renderReport(run)` 显示。
- 「记一下，MES 服务器是 192.168.10.20」→ `answer_type: remembered`。
- 「交换机 SSH 一直登不上」→ 照常回答手册内容，`suggestion` 为「要我现场排查吗？回复「好」…」；用户回「好」就执行排查。
- 长期记忆存在本机 `kb/memory.db` 和 `kb/memory/*.md`，前端不用管存储。

前端要做的：第 4 节新增的两种 `answer_type`；`suggestion` 的提示（或一个「开始排查」按钮，点击等于发送「好」）；`history` 多存 `query`、`suggest_skill`（第 5 节）。

### 11.2 一键体检接真实引擎（替换 `DEMO_RUNS`）

在 `_diagnose_stream()` 开头加上下面这段：技能能执行就走引擎，否则照旧用演示数据。

```python
# 文件开头
try:
    from engine import loader as engine_loader
    from engine.runner import run_skill as engine_run_skill
except Exception:            # 没装 pyyaml 等情况：退回演示数据
    engine_loader = engine_run_skill = None

# _diagnose_stream() 开头
skill_dir = SKILLS_DIR / skill_id
if engine_loader and re.fullmatch(r"[A-Za-z0-9_-]+", skill_id) and engine_loader.load_skill(skill_dir)["valid"]:
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    try:
        for event, data in engine_run_skill(skill_id):     # start / collect / rules / ai / report / done
            self._send_sse(event, data)
    except Exception as exc:
        self._send_sse("error", {"message": f"诊断引擎出错：{exc}"})
    return
# ……下面是原来的 DEMO_RUNS 代码，不用动
```

- `start.demo` 为 `false`，界面徽标会显示「本机执行中」。
- 交换机命令的输出第一行是「【模拟回放 · 来源：手册哪一页、改了什么】」；本机命令（ping 等）是真实执行的。
- `collect` 和 `findings` 比演示数据多了几个字段（`id`、`mode`、`raw`、`finding_id`、`refs`），现有代码会忽略。

### 11.3 技能列表

`list_skill_cards()` 里，技能卡片的名称和描述可以改读 `SKILL.md`。能执行的技能要设置 `demo_ready: true`，否则 `app.js` 会把「一键体检」按钮置灰（`skills/` 目录里的技能默认不是 `demo`）。

```python
skill = engine_loader.load_skill(skill_dir)
if skill["valid"]:
    card.update({"name": skill["name"], "description": skill["description"],
                 "command_count": len(skill["collect"]["commands"]), "demo_ready": True})
```

### 11.4 存为技能

`/api/save-skill` 收到的 `run` 是一键体检 `done` 事件的数据。如果是引擎执行的结果（`run["engine"]` 为 `true`），改用：

```python
from engine import skillgen
result = skillgen.build(name, run, SKILLS_DIR, slug=slug)   # → {"skill_id", "path", "errors"}
```

生成的技能目录包含 `SKILL.md`、`collect.yaml`、`rules.yaml`、`refs.yaml` 和 `replay/`，可以直接执行。

### 11.5 已知情况

- 4 个技能的 ID 没变（`net-unreachable` / `disk-full` / `service-down` / `log-audit`），内容改成了交换机方向。`DEFAULT_SKILLS` 和 `app.js` 里的描述文字、英文翻译还是旧的，需要的话改一下文字即可。
- 存为技能后，同一个浏览器再执行这个新技能时，`app.js` 会优先播放 `localStorage` 里保存的回放，不经过引擎（前端原有逻辑）。
- 新增依赖 `pyyaml`，记得 `pip install -r requirements.txt`。
- 技能、规则树、回放数据的说明见 [`engine/README.md`](../engine/README.md)。

有问题找陈文韬。
