# 技能包编写与安全边界

每个技能位于 `skills/<skill-id>/`。`skill-id` 必须是 2～64 位小写字母、数字、`-` 或 `_`，目录中必须同时存在以下四个文件：

| 文件 | 用途 |
| --- | --- |
| `SKILL.md` | 技能名称、适用范围和人工处置说明 |
| `collect.yaml` | 稳定命令 ID、参数数组、超时、解析器、必需性和 simulation 固件 |
| `rules.yaml` | 固定 DSL 条件、命中/未命中分支和候选报告项 |
| `refs.yaml` | 规则结论到静态原文或当轮 RAG 查询的映射 |

## 采集命令

命令必须写成 `argv` 数组，不能写 shell 字符串。例如：

```yaml
version: 1
commands:
  - id: disk-usage
    argv: [df, -P]
    timeout_s: 5
    required: true
    parser: df_posix
    simulation:
      status: success
      returncode: 0
      output: "Filesystem ..."
```

技能包不能扩大全局白名单。当前允许的程序和参数策略以 `engine/executor.py` 为唯一权威来源；执行器固定 `shell=False`、受控 PATH 和工作目录，单条最长 30 秒、输出最多 64 KiB。包含分号、管道、重定向、`&&`、反引号、命令替换或换行的参数会被拒绝。

`required: true` 的命令失败、超时或被拒绝后停止后续采集；可选命令失败会继续并进入 `unresolved`。simulation 固件只用于可重复验收，运行结果和 UI 会持续显示 `execution_mode=simulation`。

## 规则 DSL

规则条件只允许 `eq`、`ne`、`gt`、`gte`、`lt`、`lte`、`contains`、`not_contains`、`regex`、`exists`，以及 `all`、`any`、`not` 组合。`fact` 是结构化采集结果中的点路径，例如：

```yaml
when: {fact: commands.disk-usage.parsed.max_usage_pct, op: gte, value: 90}
```

规则不执行 Python 表达式；禁止 `eval`/`exec`。`${...}` 只进行事实字段模板替换。每个要发布的 finding 都必须列出有效 `ref_ids`，否则只进入未决项。

## 出处

静态出处必须给出项目内文件路径、章节、页码（Markdown 可为空）和逐字存在于该文件的原文。RAG 出处只声明查询词，运行时从当前发布索引解析；解析失败时不会发布结论。

AI 只处理规则未覆盖项，不能生成或选择采集命令。AI finding 必须引用当轮片段编号，并逐字复制其中一条说明性证据；命令还要在引用原文中逐字出现。验证失败的内容进入 `unresolved`。

## 本地校验

```bash
.venv/bin/python -m unittest tests.test_engine -v
.venv/bin/python -c 'from engine import SkillEngine; from pathlib import Path; print(SkillEngine(Path("skills"), Path("runtime"), Path(".")).list_skills())'
```

新目录无需修改代码即可被扫描。无效技能仍会显示在 UI 中并列出错误，但不能执行。
