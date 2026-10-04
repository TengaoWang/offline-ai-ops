"""手册问答的完整流程：调度器 → 原文截取 + 模型生成 → 审核。

和 rag.ask() 的区别：
  1. 调度器先看问句：打招呼就自我介绍，和交换机无关就拒答，太笼统就追问，只有具体问题才去查手册。
  2. 两条路：先从检索到的原文里截取最相关的几行（约 1 秒），再让模型根据原文整理回答（rag.ask）。
  3. 审核：模型的回答通过出处和命令核对就用它；没通过就退回手册原文，并说明这是原文。

rag.ask() 保持不变；answer() 是新入口，answer_stream() 按步骤产出结果，方便界面先显示原文。
"""

import json
import re
import time

from . import config, rag
from .client import LLMError, chat, embed

INTRO = ("我是离线机房运维助手，根据《华为S系列园区交换机维护宝典》回答华为交换机的配置、维护和故障排查问题，"
         "全程不联网。可以试试问：接口 down 怎么排查、怎么把端口加入 VLAN、CPU 占用率高怎么处理。")
OUT_OF_SCOPE = ("这个问题不在交换机维护手册的范围内。我只能回答华为 S 系列交换机的配置、维护和故障排查问题，"
                "例如：接口 down 怎么排查、怎么配置 trunk、怎么查看日志。")

EXTRACT_CHARS = 400  # 截取原文最多多少字
HISTORY_TURNS = 2    # 调度器看之前几轮对话

DISPATCH_PROMPT = """你是离线机房运维助手的「问题分诊员」。助手只能根据《华为S系列园区交换机维护宝典》回答
华为交换机的配置、维护和故障排查问题。判断用户这句话属于哪一类，只输出 JSON。

- greet：打招呼、问你是谁、你能做什么、感谢等闲聊。
- reject：和华为交换机、网络设备维护无关，例如电脑操作系统、数据库、服务器软件、办公软件、
  其他品牌的产品、价格、保修、售后。
- clarify：和交换机有关，但太笼统，无法确定要查什么，例如只给了一个型号或一个词。
  这时在 clarify_question 里写一句追问，并列出 2 到 4 个可选方向；可选方向只能从手册覆盖的内容里选：
  配置（VLAN、trunk、SSH 等）、故障排查（接口 down、丢包、CPU 高等）、维护操作（保存配置、恢复出厂、
  升级等）、查看设备信息（型号、序列号、日志等）。
- answer：可以去手册里查的具体问题，包括配置、命令、故障现象、排查方法、维护操作；
  用口语描述的故障现象（如「网口灯不亮」「网特别卡」）也属于 answer。

拿不准是 answer 还是其他类时，选 answer。

如果给出了之前的对话，用户这句话可能是在回答助手的追问或接着上一句问，
要结合上下文理解。query 填结合上下文后的完整问题（例如之前问「s5700」、
助手追问后用户说「型号规格」，query 填「S5700 的型号规格」）；没有上下文时 query 就是用户原话。"""

DISPATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"enum": ["greet", "reject", "clarify", "answer"]},
        "clarify_question": {"type": "string"},
        "query": {"type": "string"},
    },
    "required": ["action", "clarify_question", "query"],
}

# 对话里的「排查」动作（新增）：有可执行的技能时，调度器多一类 diagnose，执行技能并把报告作为回答。
# 没有技能（engine 不可用）时，调度器的提示词和输出格式和原来完全一样。
DIAGNOSE_PROMPT = """

另外还有两类：
- remember：用户只是在告诉你现场信息、让你记住（例如「记一下，MES 服务器是 192.168.10.20」），没有要你排查。
- diagnose：用户在描述**现场正在发生**的故障，需要你动手检查设备和网络，例如「MES 服务器连不上了」
  「帮我查一下网络」「交换机 SSH 登不上」「升级提示存储空间不足」「看看交换机日志有没有异常」「一键体检」。
  这时从下面的技能里选一个填到 skill，并填写技能参数 vars：只填用户这句话或「已记住的现场信息」里
  明确给出的值，没有就不填，不要编造。
  只是在问「怎么排查」「某个命令什么意思」「某种现象一般是什么原因」，属于 answer，不是 diagnose。
  但如果是 answer、而用户描述的故障现象正好是某个技能能检查的（例如「SSH 登不上」对应登录排查），
  skill 也填那个技能（系统会在回答后问用户要不要现场排查）；和技能无关就填空字符串。

不管哪一类，如果用户这句话里有以后还会用到的现场信息（例如「MES 服务器是 192.168.10.20」「接在 GE0/0/8」），
写到 facts：每条写 text（一句完整的话）；如果正好对应某个技能参数，再写 skill、var、value。没有就返回空列表。

可用技能：
{skills}

{memory}"""


# 只有用户明确要求动手检查时才执行技能；只描述现象（「SSH 连不上」）仍然查手册回答，并提示可以现场排查。
# 这样原来的手册问答不会被抢走（调度器评测里的问题全是这一类）。
_WANTS_CHECK = re.compile(r"(帮我|给我|替我|麻烦|请)(查|排查|检查|诊断|测)|(排查|检查|诊断|查|看|测)一下|体检|巡检|"
                          r"(开始|现在|马上)(排查|检查|诊断)|跑一下|执行一下")
_AGREE = re.compile(r"^(好|好的|可以|行|嗯|是|对|查吧|查一下|排查吧|开始吧?|执行吧?|ok|yes)[。！!. ]*$", re.I)


def _dispatch_schema(skills: list[dict]) -> dict:
    var_names = sorted({v for s in skills for v in s["vars"]}) or [""]
    schema = json.loads(json.dumps(DISPATCH_SCHEMA))
    schema["properties"]["action"]["enum"] = DISPATCH_SCHEMA["properties"]["action"]["enum"] + ["diagnose", "remember"]
    schema["properties"].update({
        "skill": {"type": "string", "enum": [s["id"] for s in skills] + [""]},
        "vars": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "enum": var_names}, "value": {"type": "string"}}, "required": ["name", "value"]}},
        "facts": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "skill": {"type": "string"}, "var": {"type": "string"},
            "value": {"type": "string"}}, "required": ["text"]}},
    })
    schema["required"] = DISPATCH_SCHEMA["required"] + ["skill", "vars", "facts"]
    return schema


# 新流程专用的回答提示词（rag.ask() 默认的 ANSWER_PROMPT 不变，界面调用的 ask() 不受影响）
QA_ANSWER_PROMPT = """你是离线机房运维助手。只能根据下面带编号的手册片段回答用户问题。
规则：
1. 只使用片段里写明的内容。片段里没写的事实（设备类型、性能、用途等）一律不写，不要自己补充。
2. 回答里的每一条命令都必须在片段里原样出现，逐字照抄。
3. 先判断片段讲的是不是用户问的那件事：名称相近但不是同一个功能或对象时，不能拿来回答。
4. 片段只和问题部分相关、不能直接回答时，answer 第一句写「手册中没有直接回答这个问题，相关内容如下：」，
   再列出相关的要点。
5. 每条要点末尾用 [编号] 标出它来自哪个片段，例如「……执行 display interface brief 查看。[2]」。
   正文里不要写文件名、章节名和页码，出处由程序单独列出。
6. citations 填你实际用到的片段编号（整数）。
7. 片段和问题完全无关时，found 填 false，answer 填「手册中未找到依据。」，citations 为空。
8. 回答简洁，要点或操作步骤用编号列出。"""

_MARKER = re.compile(r"\[(\d+)\]")


def _renumber(answer: str, citations: list[dict]) -> tuple[str, list[dict]]:
    """出处按在回答里第一次出现的先后重新编号为 [1] [2] [3]…，回答里的 [编号] 跟着改。

    模型用的是资料编号（如先引用 [3] 再引用 [2]），直接显示会让人对不上号。
    """
    by_old = {c["n"]: c for c in citations}
    order = [n for n in dict.fromkeys(int(m) for m in _MARKER.findall(answer)) if n in by_old]
    order += [n for n in by_old if n not in order]  # 回答里没标、但模型列为出处的，排在后面
    new_number = {old: i for i, old in enumerate(order, 1)}
    answer = _MARKER.sub(lambda m: f"[{new_number[int(m.group(1))]}]" if int(m.group(1)) in new_number else "",
                         answer)
    return answer, [by_old[old] | {"n": new_number[old]} for old in order]


_MOCK_GREETINGS = ("你好", "你是谁", "您好", "hello", "hi", "谢谢")


def _history_text(history: list[dict]) -> str:
    """把之前几轮 answer() 的结果写成对话文字，给调度器理解上下文。"""
    lines = []
    for turn in history[-HISTORY_TURNS:]:
        lines.append(f"用户：{turn.get('question', '')}")
        reply = turn.get("answer", "")
        kind = "追问" if turn.get("action") == "clarify" else "回答"
        lines.append(f"助手（{kind}）：{reply[:200]}")
    return "\n".join(lines)


def dispatch(question: str, history: list[dict] | None = None, skills: list[dict] | None = None,
             recalled: dict | None = None) -> dict:
    """返回 {"action": "greet" | "reject" | "clarify" | "answer" | "diagnose" | "remember", "clarify_question": 追问（仅 clarify）,
    "query": 结合上下文后的完整问题, "skill", "vars", "facts"}。

    history 是之前几轮 answer() 的返回值（含 question、action、answer），可以不传。
    上一轮已经追问过时，这一轮不再追问，直接去查手册（最多追问一次）。
    skills：可执行的技能（diagnose.available_skills()）；不传或为空时没有 diagnose 这一类，和原来的行为一样。
    recalled：长期记忆（diagnose.recall()），给调度器取技能参数用。
    """
    history = history or []
    skills = skills or []
    if config.MOCK:
        action = "greet" if any(g in question.lower() for g in _MOCK_GREETINGS) else "answer"
        return {"action": action, "clarify_question": "", "query": question, "skill": "", "vars": [], "facts": [],
                "suggest_skill": None}
    content = question if not history else f"之前的对话：\n{_history_text(history)}\n\n用户现在说：{question}"
    system, schema = DISPATCH_PROMPT, DISPATCH_SCHEMA
    if skills:
        from .diagnose import recall_text, skills_text
        system += DIAGNOSE_PROMPT.format(skills=skills_text(skills),
                                         memory=recall_text(recalled or {"facts": [], "episodes": []}))
        schema = _dispatch_schema(skills)
    raw = chat([{"role": "system", "content": system}, {"role": "user", "content": content}], schema=schema)
    try:
        reply = json.loads(raw)
    except json.JSONDecodeError:
        reply = {}
    action = reply.get("action") if reply.get("action") in schema["properties"]["action"]["enum"] else "answer"
    clarify = (reply.get("clarify_question") or "").strip()
    query = (reply.get("query") or "").strip() or question
    if action == "clarify" and (not clarify or (history and history[-1].get("action") == "clarify")):
        action = "answer"  # 没给出追问，或者上一轮已经追问过：按普通问题去查手册
    skill = reply.get("skill") or ""
    offered = history[-1].get("suggest_skill") if history else None
    if offered and _AGREE.match(question.strip()):
        # 上一轮提示「要我现场排查吗」，用户回答「好」：执行上一轮建议的技能，问题用上一轮的
        action, skill, query = "diagnose", offered, history[-1].get("query") or query
    suggest = None
    if action == "diagnose" and skill not in {s["id"] for s in skills}:
        action = "answer"  # 没选出可执行的技能：按普通问题去查手册
    elif action == "diagnose" and not (offered and _AGREE.match(question.strip())) and not _WANTS_CHECK.search(question):
        action, suggest = "answer", skill  # 没有明确要求动手检查：先查手册回答，再提示可以现场排查
    elif action == "answer" and skill in {s["id"] for s in skills}:
        suggest = skill  # 手册问题，但描述的现象有对应的技能：回答后提示可以现场排查
    # 技能参数只接受这句话或长期记忆里真实出现过的值，模型编造的（如「未知」「80」）丢掉
    source_text = question + "".join(f["text"] for f in (recalled or {}).get("facts", []))
    variables = [v for v in reply.get("vars") or [] if v.get("value") and _value_in(v["value"], source_text)]
    return {"action": action, "clarify_question": clarify if action == "clarify" else "", "query": query,
            "skill": skill if action == "diagnose" else "", "vars": variables if action == "diagnose" else [],
            "facts": reply.get("facts") or [], "suggest_skill": suggest}


def _value_in(value: str, text: str) -> bool:
    """参数值是否真的出现在用户的话或记忆里（接口名允许简写：GE0/0/8 ↔ GigabitEthernet0/0/8）。"""
    compact = re.sub(r"\s+", "", text).lower()
    value = re.sub(r"\s+", "", value).lower()
    if value in compact:
        return True
    number = re.search(r"\d+/\d+/\d+$", value)
    return bool(number and number.group(0) in compact)


def _line_scores(question: str, lines: list[str]) -> list[float]:
    """每一行和问题的相关程度：优先用向量相似度；向量模型不可用时按问题里的词在这一行出现的个数。"""
    if config.EMBED_MODEL and not config.MOCK:
        try:
            vectors = embed([question] + lines, config.EMBED_MODEL)
            q = rag._normalize(vectors[0])
            return [float(rag._normalize(v) @ q) for v in vectors[1:]]
        except LLMError:
            pass
    terms = {t for t in rag._tokenize(question).split() if len(t) > 1}
    return [float(sum(t in line.lower() for t in terms)) for line in lines]


def extract(question: str, passage: dict) -> dict:
    """从一段资料里截取和问题最相关的连续几行（不超过 EXTRACT_CHARS 字），原样返回，不改一个字。

    从最相关的那一行往前带 1 行（常是「步骤 N」或小标题），再往后接，直到字数用完。
    """
    lines = [line for line in passage["text"].split("\n") if line.strip()]
    if sum(len(line) for line in lines) <= EXTRACT_CHARS:
        picked = lines
    else:
        scores = _line_scores(question, lines)
        best = max(range(len(lines)), key=scores.__getitem__)
        picked, size = [], 0
        for line in lines[max(0, best - 1):]:
            if picked and size + len(line) > EXTRACT_CHARS:
                break
            picked.append(line)
            size += len(line)
    return {"text": "\n".join(picked), "file": passage["file"], "page": passage["page"],
            "section": passage["section"], "label": rag._cite_label(passage)}


def answer_stream(question: str, history: list[dict] | None = None):
    """按步骤产出结果，界面可以先显示原文，再显示模型整理的回答：

      {"event": "memory", "facts": [...], "episodes": [...]}   （新增）长期记忆里和这句话相关的内容
      {"event": "dispatch", "action": ...}
      {"event": "remember", "memories": [...]}       （新增）这句话里提到、已记住的现场信息
      {"event": "skill", "name": ..., "data": ...}   （新增）只有 action 为 diagnose 时：技能执行的每一步
                                                     （start / collect / rules / ai / report / done，和界面诊断流一致）
      {"event": "extract", "extract": {...}}        只有 action 为 answer 且检索到内容时
      {"event": "final", ...answer() 的返回值}

    history：之前几轮 answer() 的返回值（可以不传）。用户回答追问时，会和上一句合成完整的问题再去查。
    """
    start = time.perf_counter()

    def final(**result):
        base = {"question": question, "query": routed["query"], "action": "answer", "answer_type": "not_found",
                "answer": rag.NOT_FOUND, "citations": [], "extract": None, "unsupported_commands": [],
                "skill": None, "run": None, "remembered": remembered, "suggest_skill": routed.get("suggest_skill"),
                "suggestion": suggestion}
        return {"event": "final", **base, **result, "latency_s": round(time.perf_counter() - start, 3)}

    from . import diagnose  # 对话里的排查和长期记忆（新增）

    skills = [] if config.MOCK else diagnose.available_skills()
    recalled = diagnose.recall(question) if skills else {"facts": [], "episodes": []}
    if recalled["facts"] or recalled["episodes"]:
        yield {"event": "memory", **recalled}
    routed = dispatch(question, history, skills, recalled)
    yield {"event": "dispatch", "action": routed["action"], "query": routed["query"]}
    names = {sk["id"]: sk["name"] for sk in skills}
    suggestion = (f"要我现场排查吗？回复「好」，我会执行「{names[routed['suggest_skill']]}」技能（只执行只读命令）。"
                  if routed.get("suggest_skill") in names else None)
    remembered = diagnose.remember(routed["facts"], {s["id"] for s in skills}) if skills else []
    if remembered:
        yield {"event": "remember", "memories": remembered}
    if routed["action"] == "remember":
        text = ("好的，已记住：\n" + "\n".join(f"- {m['text']}" for m in remembered)) if remembered else \
            "好的。不过我没有从这句话里找到需要记住的现场信息，可以说得具体一些，例如「MES 服务器是 192.168.10.20」。"
        yield final(action="remember", answer_type="remembered", answer=text)
        return
    if routed["action"] == "diagnose":
        run = None
        for name, data in diagnose.run(routed["skill"], routed["vars"]):
            yield {"event": "skill", "name": name, "data": data}
            if name == "done":
                run = data
        cites, index = diagnose.citations(run)
        summary = diagnose.summarize(routed["query"], run, recalled["episodes"])
        episode = diagnose.save_episode(routed["query"], routed["skill"], run)
        yield final(action="diagnose", answer_type="diagnosed", skill=routed["skill"], run=run, citations=cites,
                    answer=f"{summary}\n\n诊断报告：\n{diagnose.report_text(run, index)}",
                    remembered=remembered + [episode])
        return
    if routed["action"] == "greet":
        yield final(action="greet", answer_type="intro", answer=INTRO)
        return
    if routed["action"] == "reject":
        yield final(action="reject", answer_type="out_of_scope", answer=OUT_OF_SCOPE)
        return
    if routed["action"] == "clarify":
        yield final(action="clarify", answer_type="clarify", answer=routed["clarify_question"])
        return

    query = routed["query"]  # 结合上下文后的完整问题，用它去检索和回答
    hits = rag.retrieve(query, k=5)
    if not hits:
        yield final()
        return
    excerpt = extract(query, rag._with_neighbors(hits)[0])
    yield {"event": "extract", "extract": excerpt}

    try:
        generated = rag.ask(query, prompt=QA_ANSWER_PROMPT)  # 模型整理回答，并做出处和命令核对
    except LLMError:
        # 原文已经截取到了，模型这一步出错（如 Ollama 中途停了）时不丢掉原文，按「没通过核对」退回原文
        generated = {"found": False, "answer": rag.NOT_FOUND, "citations": [], "unsupported_commands": []}
    if generated["found"]:
        text, citations = _renumber(generated["answer"], generated["citations"])
        yield final(answer_type="generated", answer=text, citations=citations, extract=excerpt)
    else:
        # 模型的回答没有通过核对（或模型认为资料不够）：退回手册原文，明确标出是原文、需要自己判断
        yield final(answer_type="extracted", answer=excerpt["text"], citations=[{"n": 1, **excerpt}],
                    extract=excerpt, unsupported_commands=generated["unsupported_commands"])


def answer(question: str, history: list[dict] | None = None) -> dict:
    """手册问答的新入口。history 是之前几轮 answer() 的返回值，用于多轮对话（可以不传）。返回：

    {"question": 用户原话, "query": 结合上下文后的完整问题,
     "action": "greet" | "reject" | "clarify" | "answer" | "diagnose" | "remember",
     "answer_type": "intro" | "out_of_scope" | "clarify" | "generated" | "extracted" | "not_found" | "diagnosed"
                    | "remembered",
     "answer": 显示给用户的文字,
     "citations": 出处（和 rag.ask 相同的格式）,
     "extract": 截取的原文 {"text", "file", "page", "section", "label"} 或 None,
     "unsupported_commands": 模型回答里在出处中找不到的命令,
     "skill": 执行的技能（仅 diagnose）, "run": 技能执行结果（仅 diagnose，和界面诊断流 done 事件相同）,
     "remembered": 这一轮写入长期记忆的内容,
     "suggest_skill" / "suggestion": 用户描述了故障但没要求动手查时，建议的技能和提示语（回复「好」就执行）,
     "latency_s": 耗时}

    diagnosed：用户描述了现场故障，已执行技能；answer 是总结 + 诊断报告，citations 是报告里的手册出处。
    remembered：用户只是告诉了现场信息，已写入长期记忆。

    answer_type 为 generated：模型整理的回答，已通过核对；extracted：模型的回答没通过核对，
    显示的是手册原文（界面应标明「以下为手册原文」）。
    """
    for event in answer_stream(question, history):
        if event["event"] == "final":
            return {k: v for k, v in event.items() if k != "event"}
    raise RuntimeError("answer_stream 没有产出 final")  # 不会发生

