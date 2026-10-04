# engine：诊断引擎

把 `skills/` 里的技能真正执行起来：白名单执行命令 → 规则树判定 → 规则没覆盖的交给 AI → 生成带手册出处的分级报告。`run_skill()` 产出的事件和字段与界面原来的演示数据（`ui/server.py` 的 `DEMO_RUNS`）一致。

两种用法：
- **对话里**：`python -m llm answer` 里说「MES 服务器连不上了，帮我查一下」，本地 AI 会选技能、从长期记忆里取参数、执行并总结（见 [`llm/README.md`](../llm/README.md)）。
- **界面一键体检**：`ui/service.py` 通过 `engine.SkillEngine`（`skill_engine.py`，需求文档 §6.1 的接口）调用本引擎；界面的「模拟」模式对应全部读回放。

| 需求 | 实现 |
|---|---|
| FR-2 技能库 | `loader.py`：扫描 `skills/` 下含 `collect.yaml` 的目录，校验格式，错误的标出原因 |
| FR-3 一键采集 | `runner.py`：按顺序执行，单条超时 10 秒，全部采集超过 30 秒后面的命令不再执行 |
| FR-4 规则树 | `rules.py`：`rules.yaml` 描述的决策树，界面显示每一步命中哪条规则、走向哪个分支 |
| FR-5 混合判定 | `judge.py`：`ai_review` 指定的输出里，规则没覆盖的记录交给模型，结论标注「AI 补充推理」 |
| FR-6 分级报告 | `runner.py`：严重 / 警告 / 正常，每条有现象、根因、修复指令（只作建议，不执行） |
| FR-7 强制溯源 | `llm/cite.py`：`refs.yaml` 只写章节号，页码和标题从手册索引里查；查不到显示「手册中未找到依据」 |
| FR-8 沉淀技能 | `skillgen.py`：把一次执行结果存成新技能目录，可以直接执行 |
| 界面接口 | `skill_engine.py`：`SkillEngine.list_skills()` / `run(skill_id, mode="real"\|"simulation")` / `save_skill(run, name)`，供 `ui/service.py` 调用 |
| FR-9 白名单 | `executor.py` + `whitelist.yaml`：危险字符 → 拆参数 → 白名单 → 不经过 shell 执行 |

## 命令行

```bash
.venv/bin/python -m engine list                              # 列出技能
.venv/bin/python -m engine run net-unreachable               # 执行技能，打印采集、判定路径和报告
.venv/bin/python -m engine run log-audit --no-ai             # 不调用模型
.venv/bin/python -m engine check "ping 1.1.1.1; rm -rf /"    # 只校验白名单，不执行
```

Windows 上把 `.venv/bin/python` 换成 `.venv\Scripts\python`。

## 命令在哪里执行

| 命令 | 执行方式 |
|---|---|
| 本机命令（Windows：`ping -n`、`ipconfig`、`arp`、`tracert`；macOS：`ping -c`、`ifconfig`、`netstat -rn`、`arp -an`） | **Windows、macOS 上真实执行**（按系统自动选写法）；其他系统读 `replay/` 里的示例输出 |
| 交换机命令（`display …`、`dir …`） | 没有真实交换机，读 `replay/<命令 id>.txt`，界面输出第一行标明「模拟回放 · 来源：手册哪一页、改了什么」 |

环境变量：

| 变量 | 作用 |
|---|---|
| `ENGINE_MODE` | `auto`（默认：Windows / macOS 真实执行本机命令）/ `replay`（全部回放，演示备用）/ `live`（强制真实执行） |
| `OPS_TARGET` | 网络连通排查要 ping 的业务地址（默认 192.168.10.20） |
| `OPS_GATEWAY` / `OPS_MGMT` | 网关 / 交换机管理地址（默认从 `ipconfig` 的默认网关自动取） |
| `OPS_PORT` / `OPS_VLAN` | 目标服务器接的交换机端口 / 应属的业务 VLAN |

**演示前在 Windows 演示机上务必跑一遍** `python -m engine run net-unreachable`：网关要能 ping 通、目标地址要 ping 不通，规则树才会走到交换机端口和 VLAN 的分支。

## 技能包格式

以 `skills/net-unreachable/` 为例：

```yaml
# collect.yaml
vars:
  target: 192.168.10.20
  gateway: {from: ipconfig, regex: '默认网关…(\d+\.\d+\.\d+\.\d+)', default: 192.168.10.1}
commands:
  - id: ping-target
    run: ping -n 2 -w 1000 ${target}
  - id: port-vlan
    run: display port vlan
    target: switch            # 交换机命令，读 replay/port-vlan.txt
```

```yaml
# rules.yaml
start: local-ip
rules:
  - id: vlan
    label: 端口 ${port} 的 PVID 不是业务 VLAN ${vlan}
    check: {cmd: port-vlan, extract: '^${port}\s+(?P<link>\w+)\s+(?P<pvid>\d+)', op: '!=', value: '${vlan}'}
    hit:  {branch: '端口 VLAN 划分错误（PVID ${pvid}）', finding: vlan-wrong, next: end}
    miss: {branch: 端口 VLAN 正确, finding: vlan-ok, next: end}
findings:
  vlan-wrong:
    severity: critical
    title: 端口 ${port} 的 VLAN 划分错误
    symptom: …PVID ${pvid}，应为 VLAN ${vlan}。
    root_cause: …
    fix_commands: [system-view, interface ${port}, port default vlan ${vlan}]
    refs: [vlan]
ai_review:                    # （可选）规则没覆盖的记录交给 AI
  - {cmd: logbuffer, line: '%%\d+\w+/\d/', covered: [ARP_DUPLICATE_IPADDR]}
```

```yaml
# refs.yaml：只写章节号，不写页码
refs:
  vlan: {sections: ["22.53.3.2", "15.2.2"], query: 接口加入 VLAN}
```

- 分支键名用 `hit` / `miss`，**不要用 `yes` / `no`**（YAML 会读成布尔值）。
- `check` 的判断方式：`regex`、`not_regex`、`status: [rejected]`、`extract` + `expr` + `op` + `value`。
- 正则和文字里的 `${变量}` 来自 `vars`，以及正则里的命名分组（如 `${pvid}`）。
- 命令没有输出、取不到数字时，规则记为「无法判断」，列入「仍需人工确认」。

## 四个预置技能

| 技能 | 规则树 | 演示结论 | 手册出处 |
|---|---|---|---|
| `net-unreachable` 网络连通排查 | 本机地址 → 网关 → 目标 → 端口物理状态 → 端口 VLAN | 🔴 GE0/0/8 VLAN 划分错误 | 15.2、8.2、22.53.3.2、15.2.2 |
| `disk-full` 交换机存储空间 | 使用率 → 回收站 → 闲置系统软件 | 🔴 Flash 92.6%、🟡 回收站、🟡 闲置 .cc | 21.4.2.65、21.4.2.58、21.4.2.21 |
| `service-down` 交换机登录 | 管理地址 → STelnet → 源接口 → VTY | 🔴 STelnet 未开启、🟡 源接口为空 | 19.3.2、19.3.4 |
| `log-audit` 日志审计 | 地址冲突 → 危险命令拦截；MSTP TC 日志交给 AI | 🟡 地址冲突、🟡 TC 报文（AI）、🟢 拦截生效 | 21.8.1.5、21.8.1.3（AI 选） |

## 已知限制

- **还没在 Windows 上真实跑过**（macOS 上已真实执行验证，单元测试用假的执行函数）。中文 / 英文 Windows 的 `ping`、`ipconfig` 输出规则都按 `TTL=`、`IPv4`、`默认网关|Default Gateway` 匹配，需要在演示机上确认。
- 交换机侧全部是回放。回放来自手册示例，为演示场景改过的字段都在文件第一行写明。
- AI 补充判定每次约 20 到 30 秒（qwen3:8b）；AI 给出的修复命令没有像 `ask()` 那样逐条核对手册原文。
- 没有 findings 时不会把结果隐藏进未完成项，而是明确标记「手册中未找到依据」；对应质量评测会将缺少出处的结论判为不通过。
- `route()` 的提示词还是按 Linux 服务器问题写的，技能改成交换机方向后需要同步修改。
