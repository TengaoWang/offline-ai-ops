"""Small declarative rules evaluator. It deliberately has no eval/exec surface."""
from __future__ import annotations

import re


class RuleError(ValueError):
    pass


OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "not_contains", "regex", "exists"}
TEMPLATE = re.compile(r"\$\{([A-Za-z0-9_.-]+)\}")


def get_path(data, path: str):
    value = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _leaf(condition: dict, facts: dict) -> bool:
    path, op = condition.get("fact"), condition.get("op")
    if not isinstance(path, str) or op not in OPS:
        raise RuleError("规则叶子必须包含合法 fact/op")
    actual, expected = get_path(facts, path), condition.get("value")
    if op == "exists":
        return (actual is not None) is bool(expected if expected is not None else True)
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op in {"gt", "gte", "lt", "lte"}:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError) as exc:
            raise RuleError(f"规则数值不可比较：{path}") from exc
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[op]
    if op in {"contains", "not_contains"}:
        result = str(expected) in str(actual or "")
        return result if op == "contains" else not result
    pattern = str(expected or "")
    if len(pattern) > 200:
        raise RuleError("正则表达式过长")
    return re.search(pattern, str(actual or ""), re.I) is not None


def evaluate(condition: dict, facts: dict) -> bool:
    if not isinstance(condition, dict):
        raise RuleError("规则条件必须是对象")
    if "all" in condition:
        items = condition["all"]
        if not isinstance(items, list) or not items:
            raise RuleError("all 必须是非空列表")
        return all(evaluate(item, facts) for item in items)
    if "any" in condition:
        items = condition["any"]
        if not isinstance(items, list) or not items:
            raise RuleError("any 必须是非空列表")
        return any(evaluate(item, facts) for item in items)
    if "not" in condition:
        return not evaluate(condition["not"], facts)
    return _leaf(condition, facts)


def render(value, facts):
    if not isinstance(value, str):
        return value
    def replacement(match):
        resolved = get_path(facts, match.group(1))
        return "未知" if resolved is None else str(resolved)
    return TEMPLATE.sub(replacement, value)


def evaluate_rules(rules: list[dict], facts: dict) -> tuple[list[dict], list[dict]]:
    paths, findings = [], []
    for rule in rules:
        matched = evaluate(rule["when"], facts)
        action = rule.get("on_match", {}) if matched else rule.get("on_miss", {})
        path = {"rule_id": rule["id"], "id": rule["id"], "matched": matched,
                "state": "hit" if matched else "miss", "label": rule.get("label", rule["id"]),
                "branch": action.get("branch", "continue")}
        paths.append(path)
        finding = action.get("finding")
        if finding:
            item = {key: render(value, facts) for key, value in finding.items() if key not in {"fix_commands", "ref_ids"}}
            item["fix_commands"] = [render(x, facts) for x in finding.get("fix_commands", [])]
            item["ref_ids"] = list(finding.get("ref_ids", []))
            item["judged_by"] = "rule"
            item["rule_path"] = [path]
            findings.append(item)
    return paths, findings
