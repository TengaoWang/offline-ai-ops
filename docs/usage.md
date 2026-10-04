# 使用说明

离线 AI 运维助手：在本机和本地 AI 对话，它可以查华为交换机手册（带页码出处）、现场排查故障、记住现场信息和以前的排查经历。全程不联网。

| 适用系统 | 状态 |
|---|---|
| macOS | 已真实验证 |
| Windows | 已支持，**演示前请按第 6 节在演示机上测一遍** |

---

## 1. 第一次准备（需要联网，只做一次）

| 步骤 | macOS | Windows |
|---|---|---|
| 安装 Ollama | [ollama.com/download](https://ollama.com/download) 或 `brew install ollama` | [ollama.com/download](https://ollama.com/download) 下载 `OllamaSetup.exe` |
| 下载模型 | `ollama pull qwen3:8b`，`ollama pull bge-m3` | 同左 |
| Python 环境 | `uv venv .venv --python 3.12` | 同左 |
| 安装依赖 | `uv pip install --python .venv/bin/python -r requirements.txt` | `uv pip install --python .venv\Scripts\python -r requirements.txt` |
| 手册索引 | 向队友要 `kb/index.db`（约 50MB）放进 `kb/` | 同左 |
| 检查 | `.venv/bin/python -m llm health` | `.venv\Scripts\python -m llm health` |

`health` 的结果里 `ollama`、`model`、`embed_model`、`index` 都是 `true` 就可以用了。

> 下文命令按 macOS 写。Windows 上把 `.venv/bin/python` 换成 `.venv\Scripts\python`。

## 2. 和本地 AI 对话（主要用法）

```bash
.venv/bin/python -m llm answer
```

进入连续对话，直接回车退出。可以这样说：

| 你说 | AI 做什么 |
|---|---|
| 你好 / 你是谁 | 自我介绍 |
| S5700 上怎么把 GE0/0/1 配成 trunk 口？ | 查手册回答，附章节和页码 |
| 记一下：MES 服务器的业务地址是 192.168.10.20，接在交换机 GE0/0/8，应该属于 VLAN 10 | **记住**现场信息 |
| MES 服务器连不上了，帮我查一下 | **现场排查**：从记忆里取地址 → 在本机执行检查 → 规则树判定 → 报告 |
| MES 那台又连不上了，帮我排查一下 | 同上，并且会说「和上次那次一样」 |
| 交换机 SSH 一直登不上 | 先查手册回答，再问「要我现场排查吗？」，回「好」就开始排查 |
| 帮我检查一下交换机日志有没有异常 | 执行日志审计（规则没覆盖的日志交给 AI 判断） |
| 升级时提示存储空间不足，帮我检查一下 | 执行存储空间排查 |

**什么时候会执行排查**：要明确说「帮我查一下」「排查一下」「检查一下」「体检」之类的话。只描述现象时，AI 先查手册回答，不会直接动手。

**排查的结果怎么看**：

```
▶ 执行技能：网络连通排查
  $ ping -c 2 -t 2 192.168.10.20    [失败 · 真实执行]   ← 在你电脑上真实执行的命令
  $ display port vlan               [成功 · 回放]       ← 交换机命令：没有交换机，用手册示例
  规则树判定：
    ✓ 本机已获取 IPv4 地址 → 本机地址正常              ← ✓ 是 / – 否，一层层排除
    ✓ 网关 192.168.10.1 有回复 → 本机到网关链路正常
    ✓ 目标 192.168.10.20 没有回复 → 继续检查交换机端口
    – 交换机端口物理状态为 down → 端口 up，继续检查 VLAN
    ✓ 端口 PVID 不是业务 VLAN 10 → 端口 VLAN 划分错误
答（已执行排查）：……                                  ← AI 结合以前的排查记录写的总结
🔴 严重  端口 GigabitEthernet0/0/8 的 VLAN 划分错误 [1][2]
   建议步骤（不会自动执行，操作前请备份配置）：system-view → …
  出处 [1] 《华为S系列园区交换机维护宝典》… 22.53.3.2 VLAN的划分 P2454   ← 手册真实页码
```

## 3. 长期记忆

```bash
.venv/bin/python -m llm memory              # 查看全部记忆
.venv/bin/python -m llm memory forget 3     # 删除第 3 条
open kb/memory                              # 打开记忆文件夹（Windows：explorer kb\memory）
```

- **现场信息**：你说「记一下……」时保存；以后排查时自动用来填地址、端口、VLAN。
- **排查记录**：每次排查完自动保存；下次遇到类似问题，AI 会参考以前的结论。
- 每条记忆是 `kb/memory/` 里的一个 Markdown 文件，**可以直接改或删**，下次运行时自动同步。
- 只存在本机，不进 git。想清空就删掉 `kb/memory.db` 和 `kb/memory/`。

## 4. 网页界面

```bash
.venv/bin/python -m ui.server          # 打开 http://127.0.0.1:8765
```

界面的「一键体检」执行内置技能：「真实」模式下本机命令真实执行、交换机命令读回放；「模拟」模式全部读回放。启动脚本和便携包见 README 的启动说明。

## 5. 直接执行技能（不经过对话）

```bash
.venv/bin/python -m engine list                              # 列出技能
.venv/bin/python -m engine run net-unreachable               # 执行技能，打印命令、判定路径和报告
.venv/bin/python -m engine run log-audit --no-ai             # 不调用模型（更快）
.venv/bin/python -m engine check "ping 1.1.1.1; rm -rf /"    # 只检查白名单，不执行
```

| 技能 | 查什么 | 演示结论 |
|---|---|---|
| `net-unreachable` 网络连通排查 | 本机地址 → 网关 → 目标 → 交换机端口 → 端口 VLAN | 🔴 GE0/0/8 VLAN 划分错误 |
| `disk-full` 交换机存储空间 | Flash 使用率 → 回收站 → 闲置系统软件 | 🔴 Flash 92.6%，🟡 回收站，🟡 闲置 .cc |
| `service-down` 交换机登录 | 管理地址 → STelnet → SSH 源接口 → VTY 用户数 | 🔴 STelnet 未开启，🟡 源接口为空 |
| `log-audit` 日志审计 | 地址冲突 → 危险命令拦截；其余日志交给 AI | 🟡 地址冲突，🟡 TC 报文（AI），🟢 拦截生效 |

## 6. 哪些是真实的，哪些是模拟的

| 内容 | 来源 |
|---|---|
| 本机命令（ping、ipconfig / ifconfig 等） | **真实执行**，结果是你电脑和网络的真实情况 |
| 交换机命令（`display …`、`dir …`） | **回放**：手册里的示例输出，为演示场景改过个别字段，每份文件第一行写明出自哪一页、改了什么 |
| 规则判定、报告、手册页码 | 程序实时计算，页码从手册索引里查，不是手写的 |
| 修复命令 | 来自手册原文，**只作为建议，不会自动执行** |
| AI 补充推理 | 本地模型生成，标注「AI 推理」；它给的修复命令没有逐条核对手册 |

安全边界：只执行白名单里的只读命令；含 `;` `|` `&` 等字符的命令直接拒绝；会改配置的命令一律不执行。

## 7. 演示前检查（在演示机上做）

```bash
.venv/bin/python -m unittest discover -s tests           # 62 项应全部通过
.venv/bin/python -m engine run net-unreachable --no-ai   # 看规则树是否走到「VLAN 划分错误」
.venv/bin/python -m llm answer                           # 按第 2 节的顺序说几句
```

网络连通排查会真的 ping 网关和 192.168.10.20，结果取决于现场网络：

| 现场情况 | 结果 |
|---|---|
| 网关通、192.168.10.20 不通 | 一路查到交换机，报告「VLAN 划分错误」（演示想要的） |
| 网关不通（例如断网演示） | 第二步就结束，报告「网关不可达」（这是真实结果） |
| 想要固定的演示结果 | 启动前设置 `ENGINE_MODE=replay`，所有命令都读回放 |

```bash
export ENGINE_MODE=replay          # macOS
set ENGINE_MODE=replay             # Windows 命令提示符
$env:ENGINE_MODE="replay"          # Windows PowerShell
```

也可以改要排查的地址：`OPS_TARGET`（目标）、`OPS_GATEWAY`（网关）、`OPS_PORT`（交换机端口）、`OPS_VLAN`（业务 VLAN），用法同上。

## 8. 常见问题

| 现象 | 解决 |
|---|---|
| 「本地模型暂不可用」/ 连不上 `127.0.0.1:11434` | Ollama 没启动：打开 Ollama App，或另开终端运行 `ollama serve` |
| `ModuleNotFoundError: No module named 'yaml'` | 重新安装依赖：`uv pip install --python .venv/bin/python -r requirements.txt` |
| 说了故障但没有执行排查 | 要明确说「帮我查一下 / 排查一下」；或者在 AI 问「要我现场排查吗」之后回「好」 |
| 排查时用的地址不对 | 用「记一下：……」告诉它正确的地址，或直接改 `kb/memory/` 里的文件 |
| Windows 上符号显示成问号 | 不影响使用；用 Windows Terminal 显示效果更好 |
| 回答很慢 | 排查一次约 15 到 25 秒，查手册约 20 到 45 秒（MacBook Air M4，qwen3:8b） |

## 9. 更多说明

| 文档 | 内容 |
|---|---|
| [`llm/README.md`](../llm/README.md) | 模型与知识库接口（`answer`、`ask`、`retrieve`、`cite`、记忆） |
| [`engine/README.md`](../engine/README.md) | 技能引擎、技能包格式、怎么新增技能 |
| [`rag-plan.md`](rag-plan.md) | RAG 技术路线、评测方法和已知限制 |
| [`skill-authoring.md`](skill-authoring.md) | 技能包格式和安全边界 |
