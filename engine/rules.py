"""规则树（FR-4）：命令输出特征 → 中间结论 → 根因分支。

rules.yaml 的格式（分支用 hit / miss，不用 yes / no：YAML 会把 yes / no 读成布尔值）：

    start: gateway                       # 从哪条规则开始
    rules:
      - id: gateway
        label: 网关有回复                 # 界面显示「命中哪条规则」
        check: {cmd: ping-gateway, regex: 'TTL='}
        hit:  {branch: 本机到网关正常, finding: gateway-ok, next: target}
        miss: {branch: 网关不可达, finding: gateway-down, next: end}
    findings:
      gateway-ok: {severity: ok, title: …, symptom: …, root_cause: …, fix_commands: […], refs: [ping]}

check 支持（都针对 cmd 这条命令的原始输出）：
    regex: '…'          输出匹配正则 → hit
    not_regex: '…'      输出不匹配 → hit
    status: [failed]    命令状态在列表里 → hit（success / failed / timeout / rejected）
    extract: '…(?P<used>\\d+)…'  取出数字，配合
    expr: 'used * 100 / total'    （可选）用取出的数字计算
    op: '>' , value: 90           比较结果成立 → hit，否则 miss

正则和文字里可以写 ${变量}：变量来自 collect.yaml 的 vars，以及正则里的命名分组（如 ${pvid}）。
命令没有输出、或取不到数字时无法判断，走 unknown 分支（没写就结束），并记为未完成项。
"""

from __future__ import annotations

import ast
import operator
import re

_OPS = {">": operator.gt, "<": operator.lt, ">=": operator.ge, "<=": operator.le, "==": operator.eq, "!=": operator.ne}
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_VAR = re.compile(r"\$\{(\w+)\}")
MAX_STEPS = 50


def fill(text: str, values: dict, for_regex: bool = False) -> str:
    """把 ${变量} 换成值；用在正则里时对值转义。"""
    def sub(match):
        value = str(values.get(match.group(1), match.group(0)))
        return re.escape(value) if for_regex else value
    return _VAR.sub(sub, text)


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _eval(expr: str, names: dict) -> float:
    """只支持数字、变量和 + - * / 括号的安全计算。"""
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        raise ValueError(f"不支持的表达式：{expr}")
    return walk(ast.parse(expr, mode="eval"))


def evaluate(check: dict, results: dict, values: dict) -> tuple[bool | None, dict, list[str]]:
    """判断一条规则。返回 (结果, 新取出的变量, 命中的输出行)；结果为 None 表示无法判断。"""
    result = results.get(check["cmd"])
    if result is None:
        return None, {}, []
    if "status" in check:
        wanted = check["status"] if isinstance(check["status"], list) else [check["status"]]
        return result["status"] in wanted, {}, []
    raw = result.get("raw") or ""
    if not raw.strip():
        return None, {}, []
    flags = re.IGNORECASE | re.MULTILINE
    if "regex" in check or "not_regex" in check:
        pattern = fill(check.get("regex") or check["not_regex"], values, for_regex=True)
        match = re.search(pattern, raw, flags)
        captured = {k: v for k, v in (match.groupdict() if match else {}).items() if v is not None}
        lines = [line for line in raw.splitlines() if re.search(pattern, line, flags)] if match else []
        hit = bool(match) if "regex" in check else not match
        return hit, captured, lines
    if "extract" in check:
        match = re.search(fill(check["extract"], values, for_regex=True), raw, flags)
        if not match:
            return None, {}, []
        captured = {k: v for k, v in match.groupdict().items() if v is not None}
        numbers = {}
        for key, text in captured.items():  # 只取能转成数字的分组（如 PVID），文字分组（如 link）留作 ${变量}
            try:
                numbers[key] = _number(text)
            except ValueError:
                pass
        try:
            value = _eval(check["expr"], numbers) if "expr" in check else next(iter(numbers.values()))
        except (ValueError, StopIteration, ZeroDivisionError):
            return None, captured, []
        captured["value"] = str(int(value)) if float(value).is_integer() else f"{value:.1f}"
        try:
            threshold = float(fill(str(check["value"]), values))
        except ValueError:
            return None, captured, []
        return _OPS[check["op"]](value, threshold), captured, [match.group(0)]
    raise ValueError(f"规则缺少判断方式：{check}")


def walk(tree: dict, results: dict, values: dict) -> dict:
    """从 start 开始走规则树。

    返回 {"path": 界面 rules 事件的列表 [{id, label, state, branch}],
          "findings": [(finding_id, 规则路径 labels, 变量)], "unresolved": [...], "matched_lines": [...]}。"""
    rules = {rule["id"]: rule for rule in tree.get("rules", [])}
    values = dict(values)
    path, findings, unresolved, matched = [], [], [], []
    labels: list[str] = []
    current = tree.get("start")
    steps = 0
    while current and current != "end" and steps < MAX_STEPS:
        steps += 1
        rule = rules[current]
        label = fill(rule["label"], values)
        hit, captured, lines = evaluate(rule["check"], results, values)
        values.update(captured)
        if hit is None:
            outcome = rule.get("unknown") or {"branch": "无法判断（缺少命令输出）", "next": "end"}
            path.append({"id": rule["id"], "label": label, "state": "miss", "branch": fill(outcome["branch"], values)})
            unresolved.append(f"无法判断「{label}」：命令 {rule['check']['cmd']} 没有可用的输出")
        else:
            outcome = rule["hit"] if hit else rule["miss"]
            if hit:
                matched.extend(lines)
            path.append({"id": rule["id"], "label": label, "state": "hit" if hit else "miss",
                         "branch": fill(outcome["branch"], values)})
        labels.append(label if hit is not False else f"{label}：否")
        if outcome.get("finding"):
            findings.append((outcome["finding"], list(labels), dict(values)))
        current = outcome.get("next", "end")
    return {"path": path, "findings": findings, "unresolved": unresolved, "matched_lines": matched, "values": values}
