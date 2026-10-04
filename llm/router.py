"""技能路由：用户对故障的描述 -> 应执行的技能包 ID。

基座模型 Qwen3-8B（Ollama），不微调，靠系统提示词 + JSON Schema 约束输出。
在 87 条测试题上的准确率见 eval/README.md。
"""

import json
import time

from . import config
from .client import chat

SKILLS = ["net-unreachable", "disk-full", "service-down", "log-audit"]

# 唯一的提示词来源：eval/ 的测试数据、评测和线上调用都用这一份
SYSTEM_PROMPT = """你是离线机房运维助手的「技能路由」。根据用户对故障或需求的描述，选择一个最合适的技能包。
只输出一行 JSON：{"skill": "<技能ID>"}；如果都不匹配，输出 {"skill": null}。

可选技能：
- net-unreachable：网络不通、ping 不通、连不上某台服务器或设备、丢包、网关、网线、交换机端口、VLAN
- disk-full：交换机 Flash/存储空间不足、升级空间不足、回收站或闲置系统软件占空间
- service-down：交换机 SSH、STelnet 或 Telnet 登录失败、远程登录服务未开启、VTY 用户已满
- log-audit：查看或分析日志、异常登录、可疑操作、安全审计、谁动过配置

与机房运维无关的问题（打印机、办公软件、账号申请、生活问题等）输出 {"skill": null}。"""

# 限定 skill 只能取这几个值或 null，保证输出永远是合法 JSON
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"skill": {"enum": SKILLS + [None]}},
    "required": ["skill"],
}

# mock 模式下按关键词粗略判断，只为让界面能跑起来，不代表模型效果
_MOCK_KEYWORDS = [
    ("disk-full", ["磁盘", "硬盘", "空间", "df", "inode", "disk", "盘满"]),
    ("log-audit", ["日志", "登录", "审计", "login", "audit"]),
    ("net-unreachable", ["ping", "网络", "连不上", "丢包", "网关", "vlan", "网线"]),
    ("service-down", ["起不来", "服务异常", "服务挂", "进程", "502", "503", "nginx", "mysql", "failed"]),
]

# High-confidence product vocabulary is routed deterministically. This avoids a
# small local model mapping "SSH 登不上" to the generic "连不上" network skill.
_DIRECT_KEYWORDS = [
    ("service-down", ["ssh", "stelnet", "telnet", "vty", "远程登录", "登录交换机", "登不上交换机"]),
    ("disk-full", ["flash", "存储空间", "升级空间", "回收站", "系统软件占用"]),
    ("log-audit", ["日志审计", "异常登录", "可疑操作", "谁动过配置"]),
]


def route(text: str, model: str | None = None) -> dict:
    """返回 {"skill": 技能 ID 或 None, "latency_s": 耗时（秒）, "raw": 模型原始输出}。

    skill 为 None 表示不属于任何技能包，应交给人工处理。
    """
    start = time.perf_counter()
    lowered = text.lower()
    direct = next((s for s, words in _DIRECT_KEYWORDS if any(word in lowered for word in words)), None)
    if direct:
        skill = direct
        raw = json.dumps({"skill": skill}, ensure_ascii=False)
    elif config.MOCK:
        skill = next((s for s, words in _MOCK_KEYWORDS if any(w in lowered for w in words)), None)
        raw = json.dumps({"skill": skill})
    else:
        raw = chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
            schema=OUTPUT_SCHEMA,
            model=model,
        )
        try:
            skill = json.loads(raw).get("skill")
        except (json.JSONDecodeError, AttributeError):
            skill = None  # 解析失败按「不匹配」处理，交给人工
    if skill not in SKILLS:
        skill = None
    return {"skill": skill, "latency_s": round(time.perf_counter() - start, 3), "raw": raw}
