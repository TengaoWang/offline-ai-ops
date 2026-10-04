# 技能引擎技术方案（FR-2 ~ FR-9）

| 项目 | 内容 |
|---|---|
| 范围 | FR-2 技能库、FR-3 一键采集、FR-4 规则树、FR-5 混合判定、FR-6 故障报告、FR-7 强制溯源、FR-8 沉淀技能、FR-9 白名单执行器 |
| 日期 | 2026-10-03 |
| 状态 | 草案，待团队确认 |
| 前提 | **前端不改**：引擎产出的数据和现在 `DEMO_RUNS` 的格式完全一样，诊断流的事件也不变 |
| 已定 | 演示平台 **Windows**；技能**对应《华为S系列园区交换机维护宝典》**；执行器、规则引擎、`cite()` 由陈文韬负责 |

---

## 1. 现状和要解决的问题

界面原型（`ui/`）已经做好了技能列表、诊断流、报告、存为技能的交互，但背后是写死的演示数据：

| 现状 | 问题 |
|---|---|
| 一键体检读取 `DEMO_RUNS`，固定回放 | 没有真正执行命令（FR-3） |
| 4 个预置技能只有名字，没有目录 | FR-2 要求每个技能包含 4 个文件 |
| `rules.yaml` 是文字（`if: "目标 IP 100% 丢包"`） | 程序无法判断（FR-4） |
| 出处写的是「《S5700 产品文档》§3.2.1 P47」「《安全执行规范》§1.1 P5」 | **这些文档和页码都不存在**，违反 FR-7，抽查会露馅 |
| 采集命令里有 `ipconfig \| findstr 192.168` | 带管道符，违反 FR-9；Windows 和 Linux 命令混用 |

## 2. 总体架构

```
            ┌────────────────────── ui/server.py（只改一处：数据来源）──────────────────────┐
  界面 ──→  │ /api/diagnose/stream?skill=disk-full                                          │
            │      ↓                                                                         │
            │ engine.run_skill(skill_id)  →  逐步产出事件  →  _send_sse()（已有）            │
            └────────────────────────────────────────────────────────────────────────────────┘
                     ↓
  engine/（新增）
   ├─ loader.py     读取 skills/<id>/ 的 4 个文件，校验格式            FR-2
   ├─ executor.py   白名单校验 → 不经过 shell 执行 → 超时 → 收集输出   FR-9、FR-3
   ├─ rules.py      规则树：从输出里取特征 → 比较 → 走向分支           FR-4
   ├─ judge.py      规则没覆盖到的，交给模型推理，标注「AI 推理」       FR-5
   ├─ cite.py       章节号 → 真实出处（调用 llm 的检索）                FR-7
   ├─ report.py     汇总成分级报告：现象 / 根因 / 修复指令              FR-6
   ├─ replay.py     没有真实设备时，读取录制好的输出（标注「模拟」）
   └─ runner.py     串起整个流程，产出 start/collect/rules/ai/report/done 事件
  skills/<id>/（新增 4 个目录）   SKILL.md + collect.yaml + rules.yaml + refs.yaml（+ replay/）
```

**核心约定：`runner.py` 产出的事件名称和字段，和现在 `DEMO_RUNS` 完全一致。** `ui/server.py` 只需把 `_diagnose_stream()` 的数据来源从 `DEMO_RUNS` 换成 `engine.run_skill()`；引擎出错时退回原来的演示数据，界面不会因此坏掉。

## 3. 技能包格式（FR-2）

> 已实现。下面是设计时的示例，**实际格式以 [`engine/README.md`](../engine/README.md) 和 `skills/net-unreachable/` 为准**（主要区别：分支写成 `hit: {branch, finding, next}`，结论统一放在 `findings` 里）。

```
skills/disk-full/
├─ SKILL.md         名称、适用场景、安全边界（给人看，界面显示第一行标题）
├─ collect.yaml     采集哪些命令
├─ rules.yaml       规则树
├─ refs.yaml        每条结论对应的手册章节号
└─ replay/          （可选）录制的命令输出，没有真实设备时使用
```

**自动识别**：`loader.py` 扫描 `skills/` 下所有包含 `collect.yaml` 的目录，新增一个目录就会出现在列表里，不用改代码（界面已有的 `list_skill_cards()` 已经是这样做的）。启动时校验格式，格式错的技能在列表里标红并说明原因，不影响其他技能。

### collect.yaml：采集哪些命令

```yaml
platform: windows          # windows（本机真实执行）/ switch（交换机命令，走回放）
timeout: 10                # 单条命令超时（秒）
commands:                  # 以 net-unreachable 为例
  - id: ping-target        # 规则里用这个 id 引用输出
    run: ping -n 2 192.168.10.20
  - id: ping-gateway
    run: ping -n 2 192.168.10.1
  - id: ipconfig
    run: ipconfig /all
  - id: if-brief
    run: display interface brief
    target: switch         # 交换机侧命令，读取 replay/if-brief.txt
```

### rules.yaml：规则树（FR-4）

```yaml
start: target-unreachable           # 从哪条规则开始
rules:
  - id: target-unreachable
    label: 目标 IP 100% 丢包         # 界面显示「命中哪条规则」
    check: {cmd: ping-target, op: regex, value: '100%\s*(丢失|loss)'}
    hit: gateway-ok                 # 命中走这个分支
    miss: end                         # 没命中：目标是通的，结束
  - id: gateway-ok
    label: 网关可达
    check: {cmd: ping-gateway, op: regex, value: '(来自|Reply from).*(TTL|ttl)='}
    hit: port-down
    miss: end                         # 网关也不通：本机链路问题，另一条分支（略）
  - id: port-down
    label: 交换机业务端口物理状态为 down
    check: {cmd: if-brief, op: regex, value: 'GigabitEthernet0/0/8\s+\*?down'}
    hit: end
    miss: vlan-check
    finding:                        # 命中时加入报告
      severity: critical
      title: 业务端口 down
      symptom: "目标 100% 丢包，网关可达；GE0/0/8 物理状态为 down"
      root_cause: 交换机端口物理层故障（线缆、光模块或被关闭）
      fix_commands: ["interface GigabitEthernet 0/0/8", "display this", "undo shutdown"]
      refs: [port-down]             # 对应 refs.yaml 里的条目
  - id: vlan-check
    ...
```

规则支持的判断方式（够用即可，不做通用表达式语言）：

| `op` | 含义 | 例子 |
|---|---|---|
| `>` `<` `>=` `<=` `==` | 用正则 `extract` 取出数字后比较 | 使用率 > 90 |
| `contains` / `not_contains` | 输出里有 / 没有某段文字 | `100% packet loss` |
| `regex` | 输出匹配正则 | `Active: (failed\|inactive)` |
| `status` | 命令执行结果 | `failed` / `timeout` / `rejected` |

**判定路径**：引擎按 `start → hit/miss` 走一遍（不用 yes/no 作键名：YAML 会把它们读成布尔值），每经过一条规则就记一条 `{label, state: hit/miss, branch}`，这正是界面 `rules` 事件要的格式。

### refs.yaml：结论对应的出处（FR-7）

```yaml
refs:
  port-down:
    sections: ["8.2"]              # 手册章节号，不写页码
    query: 接口物理 DOWN 故障定位    # 章节号找不到时，用这句话检索
  vlan-wrong:
    sections: ["22.53.3.2", "21.7.4.14"]
```

**规定：任何地方都不手写页码。** 页码和章节标题一律由 `cite.py` 从手册索引里查出来。

## 4. 白名单执行器（FR-9、FR-3）

执行一条命令要过 4 关：

```
命令字符串 → ① 拦截危险字符 → ② 拆分成参数 → ③ 白名单校验 → ④ 不经过 shell 执行（带超时）
```

| 关卡 | 做法 |
|---|---|
| ① 危险字符 | 出现 `;` `&` `\|` `` ` `` `$(` `>` `<` `^` `%` 换行，直接拒绝：`ping 1.1.1.1; rm -rf /`、`ping 1.1.1.1 & del C:\*` 在这一步被拦下 |
| ② 拆分 | `shlex.split()` 拆成参数列表 |
| ③ 白名单 | 第一个词必须在白名单里，参数也要符合规则（见下表） |
| ④ 执行 | `subprocess.run(参数列表, shell=False, timeout=10)`，输出最多保留 8KB |

白名单（只读命令，写在 `engine/whitelist.yaml`，可以审查）。演示平台是 Windows，只放 Windows 的写法：

| 命令 | 允许的参数 |
|---|---|
| `ping` | `-n` 次数不超过 4、`-w` 超时不超过 2000 毫秒，加一个 IP 或主机名 |
| `tracert` | `-d`、`-h` 跳数不超过 10、`-w`，加一个 IP 或主机名 |
| `ipconfig` | 无参数或 `/all` |
| `arp` | `-a` |
| `route` | `print` |
| `netstat` | `-an`、`-r` |

交换机侧的命令（`display …`、`dir flash:`）也要过同一套白名单，只允许 `display` 和 `dir` 开头，然后走回放；`save`、`reset`、`undo`、`system-view` 等一律拒绝。

**明确拒绝**：`del`、`format`、`shutdown`、`taskkill`、`reg`、`netsh`（会改网络配置），交换机的 `save`、`reset`、`reboot`、`undo`、`system-view`、`write memory` 等，以及白名单以外的任何命令。拒绝时这条命令的状态为 `rejected`，输出「该命令不在白名单，已拒绝」，界面已经支持这种显示。

**30 秒限制（FR-3）**：单条超时 10 秒，整个技能超过 30 秒就停止后面的命令，已采集的照常进入判定，并在报告里列为未完成项。

**`findstr`、`grep` 这类过滤怎么办**：不允许用管道。需要过滤时在规则里用正则从输出中提取，效果一样，更安全。

## 5. 四个技能和手册的对应（方案 A：保留 4 个 ID，内容改成交换机方向）

保留 `route()` 和界面已经在用的 4 个技能 ID，内容全部改成**交换机故障**，每个技能的结论都能在手册里找到出处。

| 技能 ID | 新定位 | 本机（Windows）真实执行 | 交换机侧（回放） | 手册出处 |
|---|---|---|---|---|
| `net-unreachable` | 网络不通：业务口不通、接口 down、VLAN 配错（场景 A） | `ping -n 2 目标`、`ping -n 2 网关`、`ipconfig /all`、`arp -a`、`tracert -d -h 8 目标` | `display interface brief`、`display port vlan`、`display vlan` | 15.2 Ping 不通故障定位、8.2 接口物理 DOWN、22.53.3.2 VLAN 的划分、21.7.4.14 VLAN 间互访不通 |
| `disk-full` | 交换机存储空间不足（升级、存日志失败） | 无（只有交换机侧） | `dir flash:`、`display device` | 21.4.2.58 升级时保证存储空间、21.4.2.65 如何释放存储空间、21.4.2.37 存储设备异常修复 |
| `service-down` | 交换机登录服务异常（SSH / STelnet 连不上） | `ping -n 2 管理口`、`arp -a` | `display ssh server status`、`display users` | 19.3 SSH 故障定位、22.3 无法登录 S5700、21.4.2.7 登录相关功能的默认开启情况 |
| `log-audit` | 交换机日志和告警审计（异常登录、配置变更） | 无（只有交换机侧） | `display logbuffer`、`display trapbuffer` | 6.1 常用信息采集、22.8 获取日志文件、12.2 管理员 AAA 登录异常 |

### 命令在哪里执行

我们**没有真实的 S5700 交换机**，所以分两部分：

| 部分 | 执行方式 | 说明 |
|---|---|---|
| **本机（Windows）** | **真实执行** | `ping`、`ipconfig`、`arp`、`tracert`；演示时可以 ping 一个不存在的地址来制造「不通」 |
| **交换机侧** | **回放** | `skills/<id>/replay/<命令id>.txt` 存交换机的输出，执行时读文件。界面标注「模拟回放」（界面已有这个标签） |

**回放内容只能来自手册里的真实示例**（手册里有大量真实输出：`display interface brief` 15 处、`display device` 18 处、`display vlan` 11 处、`display cpu-usage` 10 处、`display logbuffer` 8 处），每份回放文件第一行注明出自手册哪一页，例如：

```
# 来源：《华为S系列园区交换机维护宝典》8.2.1 P209（按演示场景把 GE0/0/8 的状态改为 down，其余原样）
```

如果为了演示场景改动了回放里的个别字段（比如把某个端口改成 down），必须在来源注释里写明改了什么。以后有真实交换机时，只要把回放换成通过 SSH 执行即可，规则和报告都不用改。

### Windows 上要注意的地方

| 问题 | 处理 |
|---|---|
| 中文 Windows 的命令输出是 GBK 编码 | 执行器先按 UTF-8 解码，失败再按 GBK 解码，不会乱码 |
| `ping` 的输出是中文（「请求超时」「(100% 丢失)」） | 规则同时匹配中文和英文，例如 `regex: '100%\s*(丢失\|loss)'` |
| 命令格式不同 | `ping -n`（不是 `-c`）、`tracert`（不是 `traceroute`）、`ipconfig`（不是 `ip addr`）；白名单只放 Windows 的写法 |
| `findstr` 这类过滤 | 不允许用管道，过滤在规则里用正则完成 |

### route() 要跟着改

`route()` 的提示词和评测数据目前描述的是 Linux 服务器问题（「C 盘满了」「nginx 起不来」）。改成交换机方向后：

- 改 `llm/router.py` 的 `SYSTEM_PROMPT` 里 4 个技能的描述
- 改 `eval/gen_data.py` 的说法模板，重新生成数据、重新评测（原来是 97.7%）
- 界面 `DEFAULT_SKILLS` 里 4 个技能的描述文字需要前端同学同步改一下（只是文字，不影响逻辑）

## 6. 混合判定（FR-5）

```
规则树走完
  ├─ 有结论 → 「规则树判定」（judged_by: rule）
  └─ 有规则没覆盖到的异常（命令失败、输出里有 error/failed 但没有规则匹配）
        ↓
     把这些命令和输出交给 llm.chat()，要求只根据输出推理，输出 JSON
        ↓
     「AI 补充推理」（judged_by: ai），界面已经区分显示这两种来源
```

- AI 推理的结论**也要走出处查询**：用它的结论去 `llm.retrieve()` 查手册，查到就附上出处，查不到就写「手册中未找到依据」。
- AI 推理只提建议，不能改变规则树已经得出的结论，两者合并后一起列出。
- 场景 A 的主判定由规则树给出；准备至少 1 个规则覆盖不到的长尾案例，比如交换机日志（`display logbuffer` 回放）里一条没有规则匹配的告警，用来演示 AI 补充判定。

## 7. 故障报告（FR-6）

`report.py` 把规则命中和 AI 推理的结果汇总成界面现在的 `findings` 格式：

```json
{"severity": "critical", "title": "业务端口 down",
 "symptom": "目标 100% 丢包，网关可达；GE0/0/8 物理状态为 down",
 "root_cause": "交换机端口物理层故障（线缆、光模块或被关闭）",
 "fix_commands": ["interface GigabitEthernet 0/0/8", "display this", "undo shutdown"],
 "judged_by": "rule", "rule_path": ["目标 IP 100% 丢包", "网关可达", "交换机业务端口物理状态为 down"],
 "sources": [{"label": "《华为S系列园区交换机维护宝典》8 故障处理：以太网接口物理DOWN > 8.2 接口物理DOWN故障定位指导 P208", "text": "…"}]}
```

- 分级：`critical` 严重 / `warning` 警告 / `ok` 正常。每个技能至少产出 3 条，正常项也列出来，例如「inode 使用正常」。
- **修复指令只展示，不执行**（写操作），报告顶部固定提示「以下为建议步骤，不会自动执行，操作前请备份配置」（界面已有这句）。
- `unresolved`：超时、被拒绝、规则和 AI 都没下结论的项，明确列出来。

## 8. 强制溯源（FR-7）

这部分由模型与知识库模块（陈文韬）负责，提供一个接口：

```python
from llm import cite
cite(sections=["22.53.3.2"], query="端口 VLAN 配置")
# → [{"label": "《华为S系列园区交换机维护宝典》22.53.3 配置VLAN > 22.53.3.2 VLAN的划分 P2454",
#     "page": 2454, "section": "...", "text": "原文片段"}]
```

1. **章节号 → 真实出处**：按手册书签找到章节的真实页码和原文；章节号不存在就退回用 `query` 检索。
2. **找不到就明说**：两种方式都找不到时返回空，报告里写「手册中未找到依据」，不编造。
3. **启动时检查**：`loader.py` 检查所有 `refs.yaml` 里的章节号在手册里是否存在，不存在的在技能列表里报警。
4. **清理现有的编造出处**：`DEMO_RUNS` 和 `saved-skill` 里的「《S5700 产品文档》…」「《安全执行规范》…」全部换掉。

4 个技能都改成交换机方向后，所有结论都能在交换机手册里找到出处，**不需要再补 Linux 文档**。

## 9. 沉淀技能（FR-8）

「存为技能」从**真实的执行结果**生成：

| 文件 | 生成方式 |
|---|---|
| `collect.yaml` | 这次实际执行成功的命令（被拒绝的不收录） |
| `rules.yaml` | 这次命中的规则路径；AI 推理的结论转成一条 `contains` 规则，并标注「来自 AI 推理，待人工确认」 |
| `refs.yaml` | 这次报告里**真实查到的**章节号 |
| `SKILL.md` | 用户填写的名称 + 适用场景 + 安全边界 |
| `replay/` | 这次的命令输出，用于下次演示回放 |

生成后立即通过 `loader.py` 校验，新技能出现在列表里并可以直接执行，满足 FR-8 的现场演示。

## 10. 验收对照

| FR | 验收标准 | 怎么测 |
|---|---|---|
| FR-2 | 4 个技能均可一键执行；新增目录自动识别 | 复制一个技能目录、改名，刷新列表后出现且能执行 |
| FR-3 | 30 秒内完成采集，展示每条命令和原始输出 | 计时；对比界面输出和终端里手动执行的结果 |
| FR-4 | 至少 2 棵规则树（网络、存储）完整走通 | 用不同的回放（端口 down / 端口正常）各跑一次，判定路径不同 |
| FR-5 | 至少 1 个长尾案例由 AI 补充判定 | 准备一份规则覆盖不到的交换机告警回放 |
| FR-6 | ≥3 条分级项，每条有现象 / 根因 / 修复指令 | 检查报告字段 |
| FR-7 | 抽查 5 条出处，页码和手册一致 | 打开 PDF 翻到对应页核对；单元测试检查所有 `refs.yaml` 的章节号都存在 |
| FR-8 | 排查 → 存技能 → 新技能出现并可执行 | 现场演示一遍 |
| FR-9 | `ping 1.1.1.1; rm -rf /` 被拦截 | 单元测试覆盖：注入符号、不在白名单的命令、超出范围的参数 |

单元测试放在 `tests/test_engine.py`，不需要 Ollama 和真实故障环境（执行器用假命令测，规则引擎用固定输出测）。

## 11. 分工和顺序

| 顺序 | 内容 | 负责 | 预计 |
|---|---|---|---|
| 1 | 确认本方案（尤其是第 5 节的技能定位） | 全员 | 15 分钟 |
| 2 | `executor.py` + `whitelist.yaml` + 测试（FR-9、FR-3） | 陈文韬 | 1.5 小时 |
| 3 | `cite()` 接口 + 清理编造的出处 + 4 个技能的 `refs.yaml`（FR-7） | 陈文韬 | 1 小时 |
| 4 | `rules.py` + 网络、存储两棵规则树（FR-4） | 陈文韬 | 2 小时 |
| 4 | 4 个技能包目录、`collect.yaml`、从手册摘取回放数据 | 成员 C（或陈文韬） | 1.5 小时 |
| 5 | `judge.py` + `report.py` + `runner.py`（FR-5、FR-6） | 陈文韬 | 1.5 小时 |
| 5 | `route()` 改成交换机方向，重新评测 | 陈文韬 | 1 小时 |
| 6 | `ui/server.py` 接上 `engine.run_skill()`；「存为技能」改用真实结果（FR-8）；4 个技能的描述文字 | 成员 D | 1 小时 |
| 7 | 联调、按第 10 节验收、录备份视频 | 全员 | 1.5 小时 |

陈文韬这一侧的工作量较大（约 8 小时），时间紧时的取舍顺序：

1. **必须有**：FR-9 执行器、FR-7 真实出处、FR-4 网络规则树（场景 A），这三项是评委最容易抽查的
2. **尽量有**：存储规则树、FR-5 AI 补充判定、FR-6 报告
3. **可以简化**：`service-down`、`log-audit` 两个技能先只做回放和规则，不做本机命令；`route()` 的重新评测放到最后

## 12. 风险

| 风险 | 对策 |
|---|---|
| 引擎没做完或出错，演示时界面空白 | `ui/server.py` 保留 `DEMO_RUNS`，引擎出错时自动退回，并标注「演示数据」 |
| 开发机是 Mac，演示机是 Windows | 执行器的单元测试用假命令，不依赖平台；Windows 上的真实执行由有 Windows 电脑的队友提前测一遍 |
| 规则写错，正常的机器也报严重 | 每棵规则树准备「有故障」「没故障」两份固定输出做单元测试 |
| 回放数据被质疑是编的 | 回放只用手册里的真实示例，每份注明出自哪一页、改了哪些字段；界面标注「模拟回放」 |
| 白名单被绕过 | 不经过 shell 执行 + 拦截危险字符 + 参数校验，三层把关；单元测试覆盖常见注入写法 |
