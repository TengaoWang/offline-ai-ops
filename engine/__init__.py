"""诊断引擎：技能库（FR-2）、白名单执行器（FR-9）、一键采集（FR-3）、规则树（FR-4）、
AI 补充判定（FR-5）、分级报告（FR-6）、手册出处（FR-7，见 llm.cite）、沉淀技能（FR-8）。

    from engine.runner import run_skill, run_skill_sync
    for event, data in run_skill("net-unreachable"):   # start / collect / rules / ai / report / done
        ...

详细说明见 engine/README.md。
"""
