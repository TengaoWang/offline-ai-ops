const state = {
  skills: [],
  selectedSkill: null,
  manualSkill: false,
  lastRun: null,
  health: null,
  busy: false,
  currentRunEl: null,
  sources: [],
  activeView: "chat",
  conversations: [],
  activeConversationId: null,
  skillReplays: {},
  skillQuery: "",
  renameConversationId: null,
  locale: "zh-CN",
  welcomeHtml: "",
  progressStep: 0,
  progressLabel: "等待开始",
  pendingUploads: [],
  memories: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const CONVERSATION_STORAGE_KEY = "offline-ai-ops.conversations.v1";
const EVIDENCE_STORAGE_KEY = "offline-ai-ops.evidence.v1";
const SKILL_REPLAY_STORAGE_KEY = "offline-ai-ops.skill-replays.v1";
const LANGUAGE_STORAGE_KEY = "offline-ai-ops.language.v1";

const EN_TRANSLATIONS = {
  "离线 AI 运维助手": "Offline AI Ops Assistant", "离线运维助手": "Offline Ops Assistant", "本地工作区": "Local workspace", "数据仅保存在此设备": "Data stays on this device",
  "新建排障会话": "New troubleshooting chat", "诊断对话": "Diagnostics", "知识问答": "Knowledge Q&A", "手册与索引": "Manuals & index", "长期记忆": "Long-term memory", "Evidence 对比": "Evidence comparison", "最近对话": "Recent chats", "演示场景": "Demo scenarios", "生产网中断": "Production network outage", "磁盘空间告警": "Disk space alert", "服务启动失败": "Service startup failure", "系统状态": "System status",
  "正在检查本机状态": "Checking local status", "仅连接 127.0.0.1": "Local connection only", "离线优先 · 不向外部发送数据": "Offline first · no data sent externally", "工作区": "Workspace", "本地运行": "Running locally", "刷新系统状态": "Refresh system status", "打开对话列表": "Open chat list", "对话列表": "Chat list", "本地 Agent 工作台": "Local Agent workspace", "新的排障会话": "New troubleshooting chat", "私有会话": "Private chat",
  "离线运维 Agent": "Offline Ops Agent", "本机知识库与技能库": "Local knowledge base and skills", "你好，我可以根据现场描述选择排查技能，逐条执行只读检查，并把判定路径和手册出处一起整理出来。": "Describe an issue and I can select a skill, run read-only checks, and show the decision path with manual references.", "所有诊断都在本机完成。写操作只会作为建议展示，不会自动执行。": "Diagnostics run locally. Write operations are shown as suggestions and are never executed automatically.", "试试这些现场问题": "Choose an example, edit it if needed, then start troubleshooting", "点击示例填入描述，可修改后开始排查": "Choose an example, edit it if needed, then start troubleshooting", "MES 业务网不通，管理口正常": "MES business network unreachable; management interface responds", "服务器磁盘空间告警": "Server disk space alert", "nginx 服务返回 502": "nginx returns HTTP 502",
  "排查技能": "Troubleshooting skill", "排查技能（可选）": "Skill (optional)", "自动匹配（不指定技能）": "Auto-match (no skill selected)", "自动匹配": "Auto-match", "不选技能时将自动匹配": "Leave the skill blank to auto-match", "描述现场故障，例如：MES 服务器业务网不通，管理口还能 ping 通": "Describe the issue, or leave the skill blank for automatic matching", "描述现场故障；不选技能时将自动匹配": "Describe the issue; leave the skill blank for automatic matching", "Enter 发送 · Shift + Enter 换行": "Enter to send · Shift + Enter for a new line", "一键体检": "Run selected skill", "开始排查": "Troubleshoot", "只读白名单命令自动采集 · 修复指令需由现场人员确认": "Read-only allowlisted checks · a person must approve repair commands", "一键体检运行已选技能；开始排查按描述匹配，也可手动指定技能。": "Run selected skill executes it directly; Troubleshoot routes the issue unless you choose a skill.",
  "排查流程": "Workflow", "等待开始": "Ready", "选择技能": "Choose a skill", "匹配排查场景": "Match the issue", "只读采集": "Read-only collection", "命令与原始输出": "Commands and raw output", "分析判定": "Analyze", "规则树与 AI 补充": "Rules and AI reasoning", "整理报告": "Prepare report", "依据、建议与未决项": "Evidence, actions, and open items", "技能库": "Skill library", "刷新": "Refresh", "技能是可选的。输入关键词查找，或保持自动匹配。": "Skills are optional. Search by keyword or keep automatic matching.", "选择技能后，也可直接描述问题自动路由。": "Choose a skill or describe an issue for automatic routing.", "搜索技能名称或描述": "Search skill name or description", "搜索技能名称或描述…": "Search skills…", "发送故障描述即可由后端本地路由选择技能。": "Send an issue description and the local backend will route it.", "会话出处": "Conversation references", "问答后显示经核验的手册出处。": "Verified manual references appear here after each answer.", "安全边界": "Safety boundary", "写操作仅建议，不自动执行": "Write operations are suggestions only",
  "手册检索": "Manual search", "从已建索引的本地手册检索答案，并展示真实出处。": "Search indexed local manuals and show source references.", "你想查询什么？": "What would you like to know?", "例如：S5700 上怎么把 GE0/0/1 配成 trunk 口？": "For example: How do I configure GE0/0/1 as a trunk on an S5700?", "无检索依据时会明确告知，不会生成出处。": "If no evidence is found, the assistant will say so without inventing a citation.", "查询本地手册": "Search local manuals", "等待查询": "Waiting for a query", "答案会附带手册文件名、章节、页码和原文片段。": "Answers include the manual, section, page, and source excerpt.", "本地知识库": "Local knowledge base", "导入设备手册并重建本地索引，文件不会离开这台设备。": "Import device manuals and build a local index. Files stay on this device.", "拖入设备手册，或从本机选择": "Drop a device manual here or choose a local file", "支持 PDF、Markdown、TXT。文件保存到本地 kb/docs/ 目录。": "PDF, Markdown, and TXT are supported. Files are saved under local kb/docs/.", "选择文件": "Choose file", "重建索引": "Rebuild index", "解析文件并展示片段样例，便于核对页码与章节。": "Parse files and show excerpts to help verify page and section metadata.", "重建本地索引": "Rebuild local index", "解析样例": "Parsed samples", "抽样展示文件、章节、页码和原文片段": "Sample file, section, page, and source excerpt", "0 条": "0 items",
  "答辩数据": "Evaluation data", "记录同一场景下的手动排障与 AI 排障数据。": "Compare manual troubleshooting with AI for the same scenario.", "手动排障记录": "Manual troubleshooting", "根据需求文档的现场演示基线，可按实际情况调整。": "Starts with the requirement baseline; edit these values to match field measurements.", "现场记录": "Field notes", "耗时（分钟）": "Time (minutes)", "步骤数": "Steps", "翻手册次数": "Manual lookups", "备注": "Notes", "AI 排障记录": "AI troubleshooting", "从最近一次诊断结果自动读取。": "Read from the latest diagnostic run.", "自动填充": "Auto-filled", "耗时": "Time", "采集命令": "Collected commands", "报告条目": "Findings", "手册出处": "Manual references", "对比表": "Comparison table", "报告数据来自当前浏览器中的本地诊断会话。": "Report data comes from local chats in this browser.", "复制 Markdown": "Copy Markdown", "生成对比表": "Generate comparison", "导出为 Markdown 文件 ↓": "Export Markdown file ↓",
  "检查本地模型服务、模型文件、手册索引和技能库。": "Check the local model service, model files, manual index, and skills.", "交换机测试模拟器": "Switch test simulator", "本机 Mock 命令台，仅返回固定样例，不连接真实设备，也不会执行系统命令。": "Local mock console with fixed outputs. It does not connect to a device or run system commands.", "P00 · 本地模拟": "P00 · Local simulation", "输入模拟命令": "Enter a simulated command", "运行模拟": "Run simulation", "注入拦截示例": "Injection block example", "等待输入": "Waiting for input", "运行模拟命令后，结果会显示在此区域。": "Results appear here after a simulated command runs.", "便携启动状态 · FR-10": "Portable startup · FR-10", "当前原型由本地服务托管。U 盘免安装启动脚本及 Ollama / llama.cpp 双方案打包属于发布交付项，尚未由前端页面实现。": "This prototype is served locally. A zero-install USB launcher with Ollama and llama.cpp packages is a release deliverable and is not implemented in this UI.", "后端接口": "Backend API", "页面通过本机 REST 与 SSE 接口读取健康状态、技能、手册索引和诊断流；接入实现可在本地服务层替换。": "The UI uses local REST and SSE endpoints for health, skills, manuals, and diagnostic streams. The local service layer can be replaced during integration.", "离线运行说明": "Offline operation", "前端静态资源由本地 Python 服务托管。模型、知识库、诊断结果和 Evidence 数据均留在本机，不加载 CDN 或外部资源。": "Static UI assets are served locally. Models, manuals, diagnostic results, and Evidence stay on this device; no CDN or external resources are loaded.", "服务地址：127.0.0.1": "Service address: 127.0.0.1",
  "系统返回的溯源片段": "Source excerpt returned by the service", "出处片段": "Source excerpt", "出处由索引元数据映射": "References are rendered from index metadata", "关闭": "Close", "本机保存": "Saved locally", "最近对话": "Recent chats", "会话只保存在此浏览器的本机存储中。": "Chats are stored locally in this browser.", "排障技能库": "Troubleshooting skills", "选择排查技能": "Choose a troubleshooting skill", "选择后可直接一键体检，也可输入故障描述让 Agent 自动路由。": "Choose a skill to run it directly, or describe an issue for automatic routing.", "技能选择是可选的。不指定技能时，开始排查会根据问题自动匹配；一键体检需要明确选择一个技能。": "Skill selection is optional. Troubleshoot will auto-route when no skill is selected. Run selected skill requires an explicit choice.", "知识沉淀": "Knowledge capture", "存为可复用技能": "Save as a reusable skill", "根据本次采集与判定生成技能草稿。保存后会写入本机 skills/ 目录。": "Create a skill draft from this run. Saving writes it to the local skills/ directory.", "新技能名称": "New skill name", "稍后再说": "Not now", "确认保存": "Save skill", "重命名会话": "Rename chat", "对话管理": "Chat settings", "会话标题": "Chat title", "标题仅保存在本机。": "The title is stored locally.", "取消": "Cancel", "保存标题": "Save title",
  "已保存回放可运行": "Saved replay ready", "待配置模拟回放": "Replay not configured", "本地模拟可运行": "Local demo ready", "本地技能包": "Local skill package", "未选择技能": "No skill selected", "待诊断后自动填充": "Auto-filled after a diagnostic", "本地处理": "Processed locally", "今天 ": "Today ", "命中规则 ": "Matched rule ", "未命中规则 ": "Unmatched rule ", "走向分支：": "Branch: ", "未提供": "Not provided", "命中条件": "Condition matched", "条件命中": "Condition matched", "条件未命中": "Condition not matched", "规则树判定": "Rule-tree result", "AI 补充推理": "AI reasoning", "严重": "Critical", "警告": "Warning", "正常": "OK", "现象：": "Symptom: ", "根因：": "Root cause: ", "判定来源：": "Source: ", "建议处理方式": "Suggested action", "建议步骤": "Suggested steps", "手册中未找到依据": "No supporting evidence found in the manuals", "没有可引用的手册片段": "No citable manual excerpt", "无依据": "No evidence", "依据、建议与未决项": "Evidence, actions, and open items", "一键体检：": "Run selected skill: ", "自动匹配技能": "Auto-match skill", "技能已选择": "Skill selected", " · 已选择": " · selected", " · 本机处理": " · local", "本机技能库": "Local skills", "本机处理": "Local processing", "现场描述": "Issue", "诊断执行过程": "Diagnostic run", "正在连接本地诊断流": "Connecting to local diagnostic stream", "执行期间只采集状态，不会运行修复写操作。": "Only status is collected; no repair command runs automatically.", "采集过程": "Collection", "等待命令回显": "Waiting for command output", "正在等待第一条命令…": "Waiting for the first command…", "规则树判定": "Rule-tree evaluation", "路径可展开核对": "Expand to inspect the path", "等待采集结果。": "Waiting for collection results.", "AI 补充推理区域": "AI reasoning", "与规则树结论区分展示": "Shown separately from rule-tree results", "诊断报告": "Diagnostic report", "等待报告": "Waiting for report", "等待报告生成。": "Waiting for the report.", "诊断完成": "Diagnostic complete", "存为技能": "Save as skill", "成功": "Success", "失败": "Failed", "超时": "Timed out", "已拒绝": "Rejected", "完成": "Done", "未能获取输出": "Output unavailable", "条命令已回显": "commands returned", "未命名条件": "Unnamed condition", "规则树判定 · ": "Rule-tree evaluation · ", " · 分支：": " · Branch: ", "未返回规则判定路径。": "No rule path was returned.", "查看手册出处": "View manual citation", "以下为建议步骤，不会自动执行。操作前请备份配置。": "These are suggestions only; no changes will run automatically. Back up the configuration first.", "手册依据": "Manual evidence", "未返回诊断条目。": "No findings were returned.", "条分级结论": "severity-ranked findings", "仍需人工确认：": "Requires manual confirmation: ", "上次执行未完成": "Previous run did not finish", "已恢复本机保存的对话。上次排查未完成，保留已回显内容，可重新发起排查。": "Restored this locally saved chat. The previous run did not finish; returned output is preserved and you can run it again.", "本地演示数据": "Local demo data", "当前为本地演示流，展示完整采集与报告交互。真实模式会显示实际执行结果。": "This is a fixed local demo stream. Live mode will show actual command results.", "本机执行中": "Running locally", "该技能没有模拟回放": "No skill replay", "技能已识别，当前模拟器无法执行": "Skill recognized; simulator cannot run it", "技能已识别，当前模拟器未配置回放": "Skill recognized; no simulator replay is configured", "已发现该技能目录，但没有对应的本地模拟数据。为避免伪造采集结果，本次没有执行命令。": "The skill directory was found, but no local demo data is configured. No commands were run.", "此技能没有本地演示回放；没有执行命令。": "This skill has no local demo replay; no commands were run.", "未返回补充说明。": "No additional reasoning was returned.", "诊断完成 · ": "Complete · ", "本地连接中断": "Local connection interrupted", "诊断流中断": "Diagnostic stream interrupted", "请检查本地服务状态。已回显的数据仍可查看；未完成部分不会补造。": "Check the local service. Returned data is preserved; missing results will not be fabricated.", "连接中断": "Connection interrupted", "模拟回放": "Demo replay", "本地技能回放 · Mock": "Local skill replay · Mock", "正在回放保存此技能时的本地演示数据，不连接真实设备。": "Replaying the demo saved with this skill. No real device is connected.", "AI 补充推理：": "AI reasoning: ", "本地演示回放完成": "Local demo replay complete", "正在写入本机技能库…": "Saving to the local skill library…", "已保存到本地技能库：": "Saved to the local skill library: ", "当前为 Mock 演示模式。下方答案与引用是固定样例，不代表已从真实手册核验；请切换到真实模式后再用于现场判断。": "Mock demo mode: the answer and citations below are fixed examples and have not been verified against a real manual.", "演示回答 · Mock": "Demo answer · Mock", "回答": "Answer", "手册中未找到依据。": "No supporting evidence found in the manuals.", "索引未就绪或未检索到依据，请先检查手册索引。": "The index is not ready or no evidence was found. Check the manual index.", "正在检索本地手册": "Searching local manuals", "只查询本机已建索引。": "Searching the local index only.", "查询失败": "Search failed", "暂无索引片段": "No indexed excerpts", "导入手册并重建索引后，会在这里展示抽样结果。": "Sample results will appear here after importing a manual and rebuilding the index.", "正在将文件保存到本地知识库…": "Saving file to the local knowledge base…", "正在重建本地索引，请稍候…": "Rebuilding the local index…", "离线 API 暂不可用": "Local API unavailable", "请求失败：": "Request failed: ", "本机服务不可用": "Local service unavailable", "请确认本地服务正在运行": "Check that the local service is running", "技能库暂不可用：": "Skill library unavailable: ", "暂无对话": "No chats yet", "点击上方按钮新建": "Select the button above to start one", "删除对话：": "Delete chat: ", "删除此对话": "Delete this chat", "重命名对话：": "Rename chat: ", "重命名此对话": "Rename this chat", "确定删除对话“": "Delete chat \"", "”吗？删除后无法恢复。": "\"? This cannot be undone.", "本机存储空间不足，当前会话尚未保存": "Local storage is full; this chat was not saved", "技能回放未能保存在本机浏览器": "The skill replay could not be saved in this browser", "命令": "Command", "技能已选: ": "Selected skill: ", "技能数量": "skills", "显示前": "Showing first ", "项，输入关键词筛选其余技能（共 ": "; search to filter the rest (", "个）": " total)", "没有找到匹配的技能。": "No matching skills found.", "已选择该技能。": "Skill selected.", "保持自动匹配，发送问题后由本机技能路由判断。": "Automatic matching is on. The local skill router chooses a skill after you send an issue.", "选择一个技能后才可一键体检。": "Choose a skill before running it directly.", "刷新中…": "Refreshing…", "已更新 · ": "Updated · ", "刷新失败：": "Refresh failed: ", "正在检查本机状态…": "Checking local status…", "技能路由暂不可用": "Skill routing unavailable", "。请刷新本地服务状态后重试。": ". Refresh local service status and try again.", "暂未匹配到排查技能": "No troubleshooting skill matched", "这个描述不属于当前技能库。请检查故障描述，或选择一个技能包后再发送；不确定的情况建议转交现场运维人员。": "This issue does not match a skill. Review it or refer it to an operator.", "技能已识别，当前模拟器无法执行": "Skill recognized; the simulator cannot run it", "本地演示模式已就绪": "Local demo mode ready", "本地模型服务已连接": "Local model service connected", "模型服务尚未就绪": "Model service is not ready", "使用本地演示数据": "Using local demo data", "仅连接本机服务": "Local service only", "本地固定样例，不连接真实设备": "Fixed local samples; no real device connection", "当前原型未包含免安装启动脚本与双方案打包": "Prototype does not include an installer-free launcher or dual-engine package", "运行模式": "Runtime mode", "连接本地模型": "Connected to local model", "已连接": "Connected", "未连接；请启动 Ollama": "Not connected; start Ollama", "知识索引": "Knowledge index", "技能包": "Skill packages", "已导入手册": "Imported manuals", "手册目录": "Manual directory", "索引文件": "Index file", "模型加载": "Model loading", "加载中时请等待，模型 + 服务目标 ≤ 3 分钟": "Model and service startup target: under 3 minutes", "本地 Mock 演示可用": "Local mock demo available", "本机服务可用": "Local service available", "本机服务未完全就绪": "Local service is not fully ready", "未导入手册": "No manual imported", "已导入 ": "Imported ", " 份手册 · 索引 ": " manuals · index ", "已就绪，共 ": "Ready, ", " 个片段": " chunks", "尚未建立": "Not built", "已选择": "Selected", "条只读检查": "read-only checks", "一键体检：": "Run selected skill: ", " · 已选择": " · selected", " · 本地模拟": " · local demo", "已匹配 ": "Matched ", "。现在开始逐条运行白名单只读检查，并整理规则判定与手册出处。": ". Running read-only checks and preparing the decision path and manual references.", "本机技能库 · ": "Local skill · ", "命令输出": "Command output", "AI 采集命令": "AI commands", "数据来源": "Data source", "手动方法": "Manual method", "离线 AI 运维助手": "Offline AI Ops Assistant", "现场记录 / 本次诊断": "Field notes / this diagnostic", "双路径现场计时 / 本次诊断": "Timed field comparison / this diagnostic", "最近一次诊断记录": "Latest diagnostic run", "由索引检索并展示出处": "Retrieved from the index with citations", "现场记录 / 报告出处栏": "Field notes / report citations", "依赖个人经验，易漏判": "Depends on operator experience; easy to miss details", "规则树确定性判定，路径可展开复核": "Deterministic rule-tree results with an expandable path", "手动查找，依据分散": "Manually located references", "系统返回出处 ": "Service returned ", "排查结果可存为本地技能包": "Save this run as a local skill package", "依赖联网搜索或资深工程师到场": "Relies on web search or an experienced engineer", "本地运行，无外部服务订阅": "Runs locally without an external subscription", "由人工说明未知项": "Operator explains unknowns", "无依据时显示未找到依据，未决项显式列出": "Missing evidence and unresolved items are shown explicitly", "FR-11 验收基线（非实测）": "FR-11 acceptance baseline (not measured)", "需求文档 §4.1": "Requirements §4.1",
};

Object.assign(EN_TRANSLATIONS, {
  "主导航": "Main navigation",
  "对话内容": "Conversation",
  "你好，我可以查询本机设备手册，也可以运行经过校验的只读排障技能。": "I can search local device manuals and run validated read-only troubleshooting skills.",
  "所有处理都在本机完成。修复指令只展示，绝不会自动执行。": "All processing stays on this device. Repair commands are shown only and are never run automatically.",
  "点击示例填入问题，可修改后查询": "Choose an example, edit it if needed, then submit",
  "请选择“手册问答”或“故障诊断”。诊断模式会执行所选模式对应的白名单只读采集。": "Choose Manual Q&A or Diagnostics. Diagnostic mode runs only allowlisted read-only collection for the selected execution mode.",
  "处理方式": "Mode",
  "手册问答": "Manual Q&A",
  "故障诊断": "Diagnostics",
  "诊断执行": "Execution",
  "本机只读执行": "Local read-only run",
  "模拟器固定输出": "Fixed simulator output",
  "正在加载技能库…": "Loading skills…",
  "询问本地手册": "Ask the local manuals",
  "询问设备配置、状态检查或排障步骤；可继续追问上文": "Ask about device configuration, status checks, or troubleshooting; follow-up questions are supported",
  "手册问答使用本地 RAG；故障诊断只执行技能包内通过白名单的只读命令。": "Manual Q&A uses local RAG. Diagnostics runs only allowlisted read-only commands from a skill package.",
  "直接运行当前选中的真实技能，不需要输入故障描述": "Run the selected skill directly without entering an issue description",
  "查询本地手册并核验出处": "Search local manuals and verify citations",
  "查询手册": "Search manuals",
  "答案逐条核验手册出处 · 无足够依据时明确拒答": "Every answer is checked against manual citations · insufficient evidence produces an explicit refusal",
  "排查上下文": "Troubleshooting context",
  "问答流程": "Q&A workflow",
  "理解问题": "Understand the question",
  "补全必要的追问对象": "Identify any required context",
  "检索手册": "Search manuals",
  "本机关键词与向量检索": "Local keyword and vector search",
  "核验结论": "Verify conclusions",
  "逐条绑定原文证据": "Bind every claim to source text",
  "展示回答": "Present the answer",
  "答案、章节与页码": "Answer, section, and page",
  "合法技能可进行本机只读执行或明确标识的模拟运行；无效技能不可执行。": "Valid skills can run locally in read-only mode or as clearly labeled simulations. Invalid skills cannot run.",
  "诊断模式下可由后端匹配技能，也可手动选择。": "In diagnostic mode, let the backend match a skill or choose one manually.",
  "支持 PDF、Markdown、TXT。文件先进入暂存区，索引验证成功后与手册清单一起发布。": "PDF, Markdown, and TXT are supported. Files are staged first and published with the manual list only after index validation succeeds.",
  "构建并发布知识库": "Build and publish the knowledge base",
  "构建期间暂停问答；失败时保留当前可用版本。": "Q&A pauses during the build; the current working version is retained if the build fails.",
  "构建并发布": "Build and publish",
  "请填写真实现场记录": "Enter actual field notes",
  "运行环境": "Runtime environment",
  "模拟命令示例": "Simulated command examples",
  "发布脚本会核对本地运行时、模型、索引和校验清单；实际 Windows/macOS 无网验收状态以发布报告为准。": "The release scripts verify the local runtime, models, index, and checksums. See the release report for actual offline Windows and macOS acceptance status.",
  "前端只通过本机 API 读取模型、知识库和真实诊断结果。": "The frontend reads models, the knowledge base, and real diagnostic results only through local APIs.",
  "现场沉淀技能": "Field-derived skill",
  "磁盘空间现场复用检查": "Reusable field disk-space check",
  "问答未就绪：请检查 Ollama、问答模型和有效索引。": "Q&A is not ready. Check Ollama, the Q&A model, and the active index.",
  "正在处理": "Processing",
  "准备诊断": "Preparing diagnostics",
  "准备体检": "Preparing checkup",
  "已匹配": "Matched",
  "当前运行经过真实技能引擎与规则树，但采集输出来自明确标识的 simulation 固件。": "This run uses the real skill engine and rule tree, but collection output comes from a clearly labeled simulation fixture.",
  "模拟诊断完成": "Simulation complete",
  "真实诊断完成": "Live diagnostic complete",
  "文件系统最高使用率达到 90%": "Maximum filesystem usage reached 90%",
  "临时目录占用已采集": "Temporary-directory usage collected",
  "主机信息已采集": "Host information collected",
  "文件系统容量达到告警阈值": "Filesystem usage reached the alert threshold",
  "当前只确认容量告警，具体占用来源仍需人工核对": "Only the capacity alert is confirmed; the source of usage still requires manual verification",
  "由现场人员确认可清理文件或扩容方案": "Have an on-site operator confirm which files can be cleaned up or whether to expand capacity",
  "清理前备份并核对业务影响": "Back up data and verify service impact before cleanup",
  "已读取临时目录占用": "Temporary-directory usage read successfully",
  "/tmp 目录大小采集成功": "/tmp directory size collected successfully",
  "该结果仅作为容量定位上下文": "This result is context for capacity analysis only",
  "核对临时文件归属后再决定是否处理": "Verify ownership of temporary files before taking action",
  "已记录诊断主机上下文": "Diagnostic host context recorded",
  "主机系统信息采集成功": "Host system information collected successfully",
  "用于标识本次容量检查环境，不单独构成故障根因": "Identifies the environment for this capacity check and is not a root cause on its own",
  "将主机信息与容量记录一并交接": "Include host information with the capacity record during handoff",
  "磁盘容量只读检查": "Read-only disk-capacity check",
  "内置离线运维诊断基线": "Built-in offline operations diagnostic baseline",
  "系统没有返回原文片段。": "The service did not return a source excerpt.",
  "将从服务端已完成运行 ": "The completed server run ",
  " 复制并重新校验以下内容：": " will be copied and the following content revalidated:",
  "已执行且通过白名单的 collect.yaml": "Executed allowlisted collect.yaml",
  "原技能的受限 rules.yaml": "Restricted rules.yaml from the source skill",
  "可解析的 refs.yaml": "Validated refs.yaml",
  "不会接受浏览器提交的任意命令或出处。": "Arbitrary commands or citations submitted by the browser are not accepted.",
  "已暂存：": "Staged: ",
  "。尚未影响当前知识库，请点击构建并发布。": ". The active knowledge base is unchanged; select Build and publish.",
  "正在创建手册快照并建立索引；期间暂停问答…": "Creating a manual snapshot and building the index; Q&A is paused…",
  "存在同名已发布手册。确认用暂存文件替换并重新构建吗？": "A published manual with the same name exists. Replace it with the staged file and rebuild?",
  "正在建立索引…": "Building the index…",
  "索引构建失败": "Index build failed",
  "已发布知识库版本：": "Published knowledge-base revision: ",
  "。可检查文件格式，或继续使用预置手册演示。": ". Check the file format or continue with the bundled manual demo.",
  "本次耗时 · ": "Elapsed · ",
  "该命令不在白名单，已拒绝": "Command rejected because it is not allowlisted",
  "模拟器未执行任何命令。": "The simulator did not run any command.",
  "模拟成功 · 固定样例输出": "Simulation succeeded · fixed sample output",
  "如何查看交换机接口当前状态？": "How do I check the current switch interface status?",
  "离线手册助手": "Offline Manual Assistant",
  "已通过出处与命令核对": "Citations and commands verified",
  "手册整理回答": "Manual-based answer",
  "手册原文摘录": "Manual excerpt",
  "需要补充信息": "More information required",
  "离线助手": "Offline assistant",
  "超出手册范围": "Outside manual scope",
  "手册依据不足": "Insufficient manual evidence",
  "模型整理未通过 · 展示原文": "Model summary not verified · showing source text",
  "等待补充信息": "Waiting for more information",
  "本机回答": "Local answer",
  "范围分流": "Scope routing",
  "未找到依据": "No evidence found",
  "未发布无依据结论": "Unsupported conclusion not published",
  "读取文件系统容量和临时目录占用，用规则树判断容量告警；全程不删除文件。": "Read filesystem capacity and temporary-directory usage, then evaluate capacity alerts with a rule tree. No files are deleted.",
  "读取最近登录、当前会话和系统运行摘要，适用于基础日志审计与交接。": "Read recent logins, current sessions, and a system summary for basic log auditing and handoff.",
  "检查目标连通性、本机回环、路由表和主机信息，适用于网络不可达的初步只读定位。": "Check target connectivity, loopback, routes, and host information for an initial read-only network diagnosis.",
  "只读采集进程、端口、系统负载和 nginx 服务状态，适用于服务不可用的初步定位。": "Collect processes, ports, system load, and nginx status in read-only mode for an initial service-availability diagnosis.",
  "适用于本次诊断中沉淀出的现场排查流程。": "A field troubleshooting workflow captured from this diagnostic run.",
  "服务就绪后可在本机运行诊断与手册问答。": "When ready, the service can run diagnostics and manual Q&A locally.",
  "模型后端": "Model backend",
  "模型": "Model",
  "索引": "Index",
  "检索方式": "Retrieval mode",
  "关键词 + 向量混合检索": "Hybrid keyword and vector retrieval",
  "仅关键词检索；请补齐 embedding 与向量": "Keyword-only retrieval; add embeddings and vectors to enable hybrid retrieval",
  "问答能力": "Q&A capability",
  "真实本地问答已就绪": "Live local Q&A is ready",
  "当前操作": "Current operation",
  "处理中": "Processing",
  "模型状态未知，需要重启服务": "Model state is unknown; restart the service",
  "空闲": "Idle",
  "本机 REST + SSE /api/*": "Local REST + SSE /api/*",
  "U 盘便携启动": "Portable USB startup",
  "演示模式未验证实际连接状态": "Demo mode does not verify a live connection",
  "演示模式未加载真实模型": "Demo mode does not load a live model",
  "未就绪；请导入手册并重建索引": "Not ready; import manuals and rebuild the index",
  "未就绪": "Not ready",
  "当前没有已导入的设备手册。索引未就绪时，问答和诊断不会显示虚构出处。": "No device manuals are imported. Q&A and diagnostics will not show fabricated citations while the index is unavailable.",
  "Evidence Markdown 对比表": "Evidence comparison in Markdown",
  "UI 路径面板": "UI path panel",
  "报告出处栏": "Report citations",
  "经验保留在个人记录中": "Experience remains in personal notes",
  "答辩陈述": "Presentation statement",
  "报告未决栏": "Report unresolved-items section",
  "三个现场问题是预设场景；当前诊断 SSE 返回固定演示数据，采集、判定和报告不是模型即时生成。": "The three incident prompts are predefined. The current diagnostic SSE returns fixed demo data; collection, decisions, and reports are not generated live by a model.",
  "前端通过独立本机 API 与后端交互；当前服务可直接联调，后续替换本地服务层时保留这些请求契约。": "The UI talks to the backend through local APIs. The current service is ready for integration, and these request contracts can be retained when the local service layer is replaced.",
  "直接运行当前选中的技能，不需要输入故障描述": "Run the selected skill directly without entering an issue description",
  "提交故障描述并自动匹配技能，也可使用已选技能": "Submit an issue to auto-match a skill, or use the selected skill",
  "标题不能为空。": "A title is required.",
  "自动匹配（最近：": "Auto-match (recent: ",
  "选择技能后才可一键体检。": "Choose a skill before running a checkup.",
  "已选择该技能；开始排查将使用此技能。": "This skill is selected; Troubleshoot will use it.",
  "保持自动匹配，发送问题后由本机技能路由判断。": "Automatic matching is on. The local skill router chooses a skill after you send an issue.",
  "当前诊断接口返回固定演示流；采集、判定和报告尚未连接真实诊断引擎。": "The diagnostic API currently returns a fixed demo stream; collection, decisions, and reports are not yet connected to a live diagnostic engine.",
  "工作台": "Workspace",
  "离线 AI 运维助手首页": "Offline AI Ops Assistant home",
  "Ollama：": "Ollama: ",
  "模型：": "Model: ",
  "索引：": "Index: ",
  "就绪": "Ready",
  "描述故障现象": "Describe the issue",
  "已完成": "Complete",
  "网络连通排查": "Network connectivity troubleshooting",
  "磁盘存储排查": "Disk and storage troubleshooting",
  "服务进程排查": "Service process troubleshooting",
  "日志审计排查": "Log audit troubleshooting",
  "网关、服务器、交换机端口、VLAN 方向的一键排查。": "Troubleshoot gateways, servers, switch ports, and VLANs.",
  "分区空间、inode、日志目录和大文件定位。": "Inspect disk space, inodes, log directories, and large files.",
  "服务状态、端口监听、进程崩溃和重启原因排查。": "Inspect service state, listening ports, process crashes, and restart causes.",
  "异常登录、配置变更、错误日志和白名单拦截演示。": "Review unusual logins, configuration changes, error logs, and allowlist blocks.",
  "目标 IP 100% 丢包": "100% packet loss to target IP",
  "网关可达": "Gateway reachable",
  "本机链路正常": "Local link is healthy",
  "本机 IP 正常获取": "Local IP acquired",
  "非 DHCP 问题": "Not a DHCP issue",
  "管理口可达、业务口不可达": "Management interface reachable; business interface unreachable",
  "端口/VLAN 层故障": "Port/VLAN layer issue",
  "网络不可达": "Network unreachable",
  "MES 服务器业务网卡不可达": "MES server business NIC unreachable",
  "ping 192.168.10.20 100% 丢包；网关和服务器管理口均可达。": "100% packet loss to 192.168.10.20; the gateway and server management interface are reachable.",
  "交换机 GE0/0/8 端口 VLAN 配置异常，应属 VLAN 10。": "Switch port GE0/0/8 has an unexpected VLAN configuration; it should belong to VLAN 10.",
  "管理口可达但业务口不可达，服务器硬件未宕机；结合手册出处，优先怀疑交换机端口 VLAN 配置异常或端口 err-down 后未恢复。": "The management interface is reachable while the business interface is not, so the server is still online. Check the switch port VLAN configuration and whether the port entered err-down.",
  "本机到网关链路正常": "Local link to gateway is healthy",
  "网关 192.168.10.1 响应正常。": "Gateway 192.168.10.1 responds normally.",
  "未发现本机链路层异常。": "No local link-layer issue was found.",
  "需要现场确认端口灯与配置一致": "Confirm port LEDs match the configuration",
  "规则树已定位到端口/VLAN 分支，但无法在当前主机直接读取交换机配置。": "The rule tree points to the port/VLAN branch, but this host cannot read the switch configuration directly.",
  "缺少交换机侧 display 输出。": "Switch-side display output is missing.",
  "空间耗尽集中在日志目录，inode 正常，最可能是日志轮转失效或异常日志增长。": "Disk usage is concentrated in the log directory while inode usage is normal. Log rotation may have failed or logs may be growing unusually.",
  "/var/log 分区空间耗尽": "The /var/log partition is full",
  "/var 使用率 100%，日志目录占 89G。": "/var is 100% full; the log directory uses 89 GB.",
  "日志轮转失效，syslog.1 单文件 42G。": "Log rotation failed; syslog.1 alone is 42 GB.",
  "inode 未耗尽": "Inodes are not exhausted",
  "inode 使用率 12%。": "Inode usage is 12%.",
  "不是小文件数量过多导致。": "Too many small files are not the cause.",
  "服务失败且端口未监听，日志提示 bind 失败，应先确认端口占用和配置文件语法。": "The service failed and the port is not listening. Logs show a bind failure; check port ownership and configuration syntax.",
  "nginx 服务未启动": "nginx did not start",
  "systemctl 显示 failed，80 端口未监听。": "systemctl reports failed and port 80 is not listening.",
  "配置或端口绑定失败导致服务退出。": "A configuration or port binding failure caused the service to exit.",
  "需要确认端口占用来源": "Identify what is using the port",
  "日志提示 bind failed。": "Logs report a bind failure.",
  "可能是旧进程、其他 Web 服务或配置重复监听。": "A stale process, another web service, or duplicate listener configuration may be responsible.",
  "存在失败登录记录": "Failed login attempts found",
  "命令包含注入分隔符": "Command contains an injection separator",
  "白名单拦截": "Allowlist blocked the command",
  "登录异常": "Unusual login",
  "发现失败登录尝试": "Failed login attempt found",
  "auth.log 中出现 root 登录失败记录。": "auth.log contains a failed root login.",
  "可能是误输密码，也可能是未授权访问尝试。": "This may be a mistyped password or an unauthorized access attempt.",
  "危险命令已被拦截": "Unsafe command blocked",
  "包含分号和删除操作的命令未执行。": "A command containing a semicolon and a delete operation was not executed.",
  "白名单执行器按安全策略拒绝。": "The allowlist executor rejected it under the safety policy.",
  "存在配置变更痕迹": "Configuration change evidence found",
  "sudo 日志显示 admin 编辑 /etc/hosts。": "sudo logs show admin edited /etc/hosts.",
  "需要与变更单或现场操作人员确认。": "Confirm this against the change request or with the on-site operator.",
  "分区使用率 100% > 90%": "Partition usage 100% > 90%",
  "磁盘告警": "Disk alert",
  "inode 使用率正常": "Inode usage is normal",
  "排除小文件堆积": "Rule out inode exhaustion",
  "/var/log 占比最大": "/var/log has the largest share",
  "日志目录分支": "Log directory branch",
  "inode 使用率 12%。": "Inode usage is 12%.",
  "不是小文件数量过多导致。": "Too many small files are not the cause.",
  "无需处理 inode。": "No inode action is needed.",
  "需要验证日志增长源": "Verify the source of log growth",
  "syslog.1 体积异常。": "syslog.1 is unusually large.",
  "可能存在持续刷屏的服务或内核错误。": "A service may be flooding the logs, or a kernel error may be repeating.",
  "tail -n 100 /var/log/syslog": "Review the latest 100 lines in /var/log/syslog",
  "重启相关日志服务前先确认进程句柄": "Check open file handles before restarting the log service",
  "日志增长源需结合最新 syslog 内容继续确认。": "Confirm the source of log growth by reviewing the latest syslog entries.",
  "服务状态 failed": "Service state: failed",
  "服务异常": "Service failure",
  "80 端口未监听": "Port 80 is not listening",
  "业务不可用": "Service unavailable",
  "日志含 bind failed": "Logs contain a bind failure",
  "端口冲突或配置异常": "Port conflict or configuration issue",
  "日志提示 bind failed。": "Logs report a bind failure.",
  "需要确认端口占用来源": "Identify what is using the port",
  "规则树命中服务失败": "Rule tree detected a service failure",
  "AI 补充端口占用排查": "AI port-ownership follow-up",
  "AI 补充端口占用排查": "AI port-ownership follow-up",
  "进程残留未发现": "No leftover process found",
  "ps 未发现 nginx master process。": "ps found no nginx master process.",
  "当前无 nginx 主进程残留。": "No nginx master process remains.",
  "无需清理 nginx 残留进程。": "No leftover nginx process needs to be cleaned up.",
  "ps 输出未发现主进程": "No master process found in ps output",
  "Failed with result 'exit-code'": "Failed with result 'exit-code'",
  "未发现 80 端口监听": "No listener found on port 80",
  "nginx master process 未运行": "nginx master process is not running",
  "存在失败登录记录": "Failed login attempts found",
  "登录异常": "Unusual login",
  "命令包含注入分隔符": "Command contains an injection separator",
  "白名单拦截": "Allowlist block",
  "sudo 修改配置痕迹": "sudo configuration change evidence",
  "配置变更审计": "Configuration change audit",
  "存在配置变更痕迹": "Configuration change evidence found",
  "sudo 日志显示 admin 编辑 /etc/hosts。": "sudo logs show admin edited /etc/hosts.",
  "记录 sudo 日志": "Record the sudo logs",
  "diff /etc/hosts 与备份文件": "Compare /etc/hosts with its backup",
  "AI 补充审计建议": "AI audit follow-up",
  "admin 的操作是否授权需人工确认。": "Confirm manually whether admin's action was authorized.",
  "Failed password for root from 10.0.0.9": "Failed password for root from 10.0.0.9",
  "该命令不在白名单，已拒绝": "Command is not on the allowlist and was rejected",
  "业务网不可达": "Business network unreachable",
  "console 线连接 S5700": "Connect to the S5700 using the console cable",
  "检查 /etc/logrotate.d/ 策略": "Review the /etc/logrotate.d/ policy",
  "检查 /etc/hosts": "Inspect /etc/hosts",
  "保存 auth.log 片段": "Save an excerpt of auth.log",
  "核对来源 IP 10.0.0.9": "Verify source IP 10.0.0.9",
  "确认是否需要临时封禁来源": "Decide whether to temporarily block the source",
  "检查是否需要临时封禁来源": "Decide whether to temporarily block the source",
  "/var inode 使用率 12%": "/var inode usage: 12%",
});
const EN_TRANSLATION_ENTRIES = Object.entries(EN_TRANSLATIONS).sort((a, b) => b[0].length - a[0].length);
const ZH_TRANSLATIONS = new Map();
EN_TRANSLATION_ENTRIES.forEach(([source, target]) => {
  if (!ZH_TRANSLATIONS.has(target)) ZH_TRANSLATIONS.set(target, source);
});
const ZH_TRANSLATION_ENTRIES = Array.from(ZH_TRANSLATIONS.entries()).sort((a, b) => b[0].length - a[0].length);

const originalTextNodes = new WeakMap();
const originalAttributes = new WeakMap();

const EN_DYNAMIC_TRANSLATIONS = [
  [/^(\d+) 条$/, (_, count) => `${count} items`],
  [/^(\d+) 个$/, (_, count) => `${count}`],
  [/^(\d+) 条命令已回显$/, (_, count) => `${count} commands returned`],
  [/^(\d+) 条分级结论$/, (_, count) => `${count} severity-ranked findings`],
  [/^(\d+) 条只读检查 · (.+)$/, (_, count, readiness) => `${count} read-only checks · ${translateUiText(readiness)}`],
  [/^显示前 (\d+) 项，输入关键词筛选其余技能（共 (\d+) 个）$/, (_, shown, total) => `Showing ${shown}; search to filter all ${total} skills`],
  [/^自动匹配（最近：(.+)）$/, (_, name) => `Auto-match (recent: ${translateUiText(name)})`],
  [/^(.+) · 已选择$/, (_, name) => `${translateUiText(name)} · selected`],
  [/^本机技能库 · (.+)$/, (_, name) => `Local skills · ${translateUiText(name)}`],
  [/^(命中规则|未命中规则) (.+) · (.+)$/, (_, stateText, rule, label) => `${stateText === "命中规则" ? "Matched rule" : "Unmatched rule"} ${rule} · ${translateUiText(label)}`],
  [/^走向分支：(.+)$/, (_, branch) => `Branch: ${branch}`],
  [/^重命名对话：(.+)$/, (_, title) => `Rename chat: ${translateUiText(title)}`],
  [/^删除对话：(.+)$/, (_, title) => `Delete chat: ${translateUiText(title)}`],
  [/^已导入 (\d+) 份手册 · 索引 已就绪，共 (\d+) 个片段$/, (_, files, chunks) => `${files} manual(s) imported · index ready with ${chunks} chunks`],
  [/^已导入 (\d+) 份手册 · 索引 尚未建立$/, (_, files) => `${files} manual(s) imported · index not built`],
  [/^已找到 (.+)$/, (_, model) => `Found ${model}`],
  [/^未找到 (.+)$/, (_, model) => `Not found: ${model}`],
  [/^已连接 (.+)$/, (_, backend) => `Connected to ${backend}`],
  [/^未连接；请启动 (.+)$/, (_, backend) => `Not connected; start ${backend}`],
  [/^已就绪，包含 (\d+) 个片段(.*)$/, (_, chunks, revision) => `Ready with ${chunks} chunks${revision}`],
  [/^(.+) 使用率为 (\d+)%$/, (_, mount, usage) => `${mount} usage is ${usage}%`],
  [/^最高使用率为 (\d+)%$/, (_, usage) => `Maximum usage is ${usage}%`],
  [/^读取到 (\d+) 条非空记录$/, (_, count) => `Read ${count} non-empty records`],
  [/^读取到 (\d+) 个当前会话$/, (_, count) => `Read ${count} current sessions`],
  [/^本次耗时 · (.+)$/, (_, mode) => `Elapsed · ${mode}`],
  [/^(Ollama|模型|索引)：(.+)$/, (_, label, status) => `${translateUiText(label)}: ${translateUiText(status)}`],
  [/^由运行 (`[^`]+`) 从 (`[^`]+`) 的已验证流程沉淀。$/, (_, run, source) => `Captured from the validated ${source} workflow in run ${run}.`],
  [/^(.+) · ([0-9.]+) 秒$/, (_, mode, seconds) => `${translateUiText(mode)} · ${seconds} s`],
  [/^(.+) · ([0-9.]+)s$/, (_, mode, seconds) => `${translateUiText(mode)} · ${seconds}s`],
];

function translateUiText(value) {
  if (state.locale !== "en") return value;
  if (Object.hasOwn(EN_TRANSLATIONS, value)) return EN_TRANSLATIONS[value];
  const match = String(value).match(/^(\s*)(.*?)(\s*)$/s);
  const [, leading, core, trailing] = match || ["", "", String(value), ""];
  if (Object.hasOwn(EN_TRANSLATIONS, core)) return leading + EN_TRANSLATIONS[core] + trailing;
  for (const [pattern, replacement] of EN_DYNAMIC_TRANSLATIONS) {
    if (pattern.test(core)) return leading + core.replace(pattern, replacement) + trailing;
  }
  return value;
}

function isUserContent(node) {
  const commandOutput = node.parentElement?.closest(".command-output");
  if (commandOutput && commandOutput.closest(".agent-run")?.dataset.demo !== "true") return true;
  return Boolean(node.parentElement?.closest(".user-bubble, .manual-answer-text, .command-main code, .source-button, .source-shelf-item, .source-text, .sample-item p, input, textarea"));
}

function localizePage() {
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walk.nextNode())) {
    if (isUserContent(node)) continue;
    const current = node.nodeValue;
    if (state.locale === "en") {
      let original = originalTextNodes.get(node);
      if (original == null || current !== translateUiText(original)) {
        original = current;
        originalTextNodes.set(node, original);
      }
      const translated = translateUiText(original);
      if (current !== translated) node.nodeValue = translated;
    } else if (originalTextNodes.has(node)) {
      node.nodeValue = originalTextNodes.get(node);
      originalTextNodes.delete(node);
    }
  }
  document.querySelectorAll("[placeholder], [aria-label], [title]").forEach((element) => {
    ["placeholder", "aria-label", "title"].forEach((attribute) => {
      if (!element.hasAttribute(attribute)) return;
      let originals = originalAttributes.get(element);
      if (!originals) { originals = {}; originalAttributes.set(element, originals); }
      const current = element.getAttribute(attribute);
      if (state.locale === "en") {
        let original = originals[attribute];
        if (original == null || current !== translateUiText(original)) {
          original = current;
          originals[attribute] = original;
        }
        const translated = translateUiText(original);
        if (current !== translated) element.setAttribute(attribute, translated);
      } else if (originals[attribute] != null) {
        element.setAttribute(attribute, originals[attribute]);
        delete originals[attribute];
      }
    });
  });
  document.documentElement.lang = state.locale;
  document.title = state.locale === "en" ? "Offline AI Ops Assistant" : "离线 AI 运维助手";
  document.querySelectorAll("[data-i18n-value-zh][data-i18n-value-en]").forEach((element) => {
    const zh = element.dataset.i18nValueZh;
    const en = element.dataset.i18nValueEn;
    if (element.value === zh || element.value === en) element.value = state.locale === "en" ? en : zh;
  });
  const toggle = $("#languageToggle");
  if (toggle) {
    const toggleText = state.locale === "zh-CN" ? "EN" : "中文";
    if (toggle.textContent !== toggleText) toggle.textContent = toggleText;
    toggle.setAttribute("aria-pressed", String(state.locale === "en"));
    toggle.setAttribute("aria-label", state.locale === "zh-CN" ? "Switch to English" : "Switch to Chinese");
    toggle.title = state.locale === "zh-CN" ? "Switch to English" : "Switch to Chinese";
  }
}

function setLocale(locale) {
  state.locale = locale === "en" ? "en" : "zh-CN";
  try { localStorage.setItem(LANGUAGE_STORAGE_KEY, state.locale); } catch (error) { /* Page still switches for this session. */ }
  renderSkills();
  generateEvidence();
  localizePage();
  localizeAutomaticConversationTitles(state.locale);
}

async function localizeAutomaticConversationTitles(locale) {
  const pending = state.conversations.filter((conversation) => conversation.titleManual !== true && conversation.titleText);
  await Promise.all(pending.map(async (conversation) => {
    const conversationId = conversation.id;
    const sourceText = conversation.titleText;
    conversation.titleLocale = locale;
    const fallback = fallbackConversationTitle(sourceText, conversation.skillId);
    setConversationTitle(conversationId, fallback);
    try {
      const result = await api("/api/title", { method: "POST", body: JSON.stringify({ text: sourceText, skill: conversation.skillId, locale }) });
      const latest = state.conversations.find((item) => item.id === conversationId);
      if (latest && latest.titleManual !== true && latest.titleLocale === locale && state.locale === locale && result.title) {
        setConversationTitle(conversationId, result.title, fallback);
      }
    } catch (error) {
      // Keep the localized deterministic fallback if the local model is unavailable.
    }
  }));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const response = await fetch(path, {
    ...options,
    headers: isForm ? options.headers : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error || ("请求失败：" + response.status));
    error.code = payload.code;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function skillName(id) {
  const skill = state.skills.find((item) => item.id === id);
  return skill ? skill.name : id || "未选择技能";
}

function statusChip(label, ready, stateText) {
  return '<span class="status-chip ' + (ready ? "ready" : "warn") + '">' + escapeHtml(label) + "：" + escapeHtml(stateText || (ready ? "就绪" : "未就绪")) + "</span>";
}

function renderHealth(health) {
  state.health = health;
  const modelReady = health.model || health.mock;
  $("#statusStrip").innerHTML = health.mock ? [
    statusChip("运行", true, "演示"),
    statusChip("模型", true, "Mock"),
    statusChip("索引", health.index, health.index ? "已建" : "未建"),
  ].join("") : [
    statusChip("Ollama", health.ollama),
    statusChip("模型", modelReady),
    statusChip("索引", health.index),
  ].join("");
  const allReady = Boolean(health.rag_ready || health.mock);
  $("#navStatusDot").classList.toggle("ready", Boolean(allReady));
  $("#sidebarHealth").innerHTML = '<span class="health-dot ' + (allReady ? "ready" : "") + '"></span><span><strong>' + (health.mock ? "本地演示模式已就绪" : allReady ? "本地模型服务已连接" : "模型服务尚未就绪") + '</strong><small>' + (health.mock ? "使用本地演示数据" : "仅连接本机服务") + "</small></span>";
  renderStatus(health);
  renderManualSummary(health);
}

function renderStatus(health) {
  const manualFiles = (health.manual_files || []).map((file) => file.name + "（" + Math.ceil(file.size / 1024) + " KB）").join("、") || "未导入手册";
  const rows = [
    ["运行模式", health.mock ? "本地 Mock 演示" : "连接本地模型"],
    ["模型后端", health.mock ? "演示模式未验证实际连接状态" : health.backend_ready ? "已连接 " + (health.backend || "ollama") : "未连接；请启动 " + (health.backend || "ollama")],
    ["模型", health.mock ? "演示模式未加载真实模型" : health.model ? "已找到 " + health.model_name : "未找到 " + health.model_name],
    ["知识索引", health.index ? "已就绪，包含 " + health.chunks + " 个片段" + (health.index_revision ? " · " + health.index_revision : "（旧版路径）") : "未就绪；请导入手册并重建索引"],
    ["检索方式", health.retrieval_mode === "hybrid" ? "关键词 + 向量混合检索" : "仅关键词检索；请补齐 embedding 与向量"],
    ["问答能力", health.rag_ready ? "真实本地问答已就绪" : "未就绪"],
    ["当前操作", health.busy ? (health.operation || "处理中") : health.recovering ? "模型状态未知，需要重启服务" : "空闲"],
    ["技能包", (health.skills_count || state.skills.length) + " 个"],
    ["后端接口", "本机 REST + SSE /api/*"],
    ["长期记忆", "已接入本机 SQLite 与 Markdown 记忆库"],
    ["交换机测试模拟器", "后端白名单校验 + 本地固定样例，不连接真实设备"],
    ["U 盘便携启动", "已提供构建与校验脚本；目标机验收状态以发布报告为准"],
    ["已导入手册", manualFiles],
    ["手册目录", health.docs_dir || "本地 kb/docs/"],
    ["索引文件", health.index_path || "本地 kb/index.db"],
    ["模型加载", "加载中时请等待，模型 + 服务目标 ≤ 3 分钟"],
  ];
  $("#statusTable").innerHTML = rows.map((row) => '<div class="status-row"><strong>' + escapeHtml(row[0]) + '</strong><span>' + escapeHtml(row[1]) + "</span></div>").join("");
  const ready = Boolean(health.rag_ready || health.mock);
  $("#statusSummaryCard").innerHTML = '<span class="status-summary-icon ' + (ready ? "" : "warn") + '">' + (ready ? "✓" : "!") + '</span><div><strong>' + (health.mock ? "本地 Mock 演示可用" : ready ? "本机服务可用" : "本机服务未完全就绪") + '</strong><span>' + (health.mock ? "当前使用固定演示数据；真实模式会连接 Ollama 与本地模型。" : "服务就绪后可在本机运行诊断与手册问答。") + "</span></div>";
}

function renderManualSummary(health) {
  const count = (health.manual_files || []).length;
  $("#manualSummary").textContent = count ? "已导入 " + count + " 份手册 · 索引 " + (health.index ? "已就绪，共 " + health.chunks + " 个片段" : "尚未建立") : "当前没有已导入的设备手册。索引未就绪时，问答和诊断不会显示虚构出处。";
}

async function loadHealth(options = {}) {
  const interactive = Boolean(options.interactive);
  const button = $("#refreshStatusBtn");
  const feedback = $("#refreshFeedback");
  if (interactive) {
    button.disabled = true;
    button.classList.add("refreshing");
    button.setAttribute("aria-busy", "true");
    feedback.classList.remove("error");
    feedback.textContent = "正在检查本机状态…";
  }
  try {
    renderHealth(await api("/api/health"));
    if (interactive) feedback.textContent = "已更新 · " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    localizePage();
    return true;
  } catch (error) {
    $("#statusStrip").innerHTML = '<span class="status-chip warn">本机服务不可用</span>';
    $("#sidebarHealth").innerHTML = '<span class="health-dot"></span><span><strong>' + escapeHtml(error.message) + '</strong><small>请确认本地服务正在运行</small></span>';
    if (interactive) {
      feedback.classList.add("error");
      feedback.textContent = "刷新失败：" + error.message;
    }
    localizePage();
    return false;
  } finally {
    if (interactive) {
      button.disabled = false;
      button.classList.remove("refreshing");
      button.removeAttribute("aria-busy");
    }
  }
}

async function loadSkills() {
  try {
    const payload = await api("/api/skills");
    state.skills = (payload.skills || []).map((skill) => ({
      ...skill,
      demo_ready: Boolean(state.skillReplays[skill.id]) || (skill.demo_ready == null ? skill.source === "demo" : Boolean(skill.demo_ready)),
    }));
    renderSkills();
  } catch (error) {
    const message = '<p class="skill-empty">技能库暂不可用：' + escapeHtml(error.message) + "</p>";
    $("#skillGrid").innerHTML = message;
    $("#skillPickerGrid").innerHTML = message;
  }
}

function renderSkills() {
  const glyphs = { "net-unreachable": "N", "disk-full": "D", "service-down": "S", "log-audit": "L" };
  const query = state.skillQuery.trim().toLowerCase();
  const localizedText = (value) => state.locale === "en" ? (EN_TRANSLATIONS[value] || value) : value;
  const matches = state.skills.filter((skill) => [skill.name, skill.description, skill.id, localizedText(skill.name), localizedText(skill.description)].join(" ").toLowerCase().includes(query));
  const createCards = (items) => items.map((skill) => {
    const selected = state.selectedSkill === skill.id;
    const readiness = state.skillReplays[skill.id] ? "已保存回放可运行" : skill.demo_ready === false ? "待配置模拟回放" : skill.source === "demo" ? "本地模拟可运行" : "本地技能包";
    return '<button class="skill-card ' + (selected ? "selected" : "") + '" type="button" data-skill="' + escapeHtml(skill.id) + '" aria-pressed="' + selected + '"' + (state.busy ? " disabled" : "") + '><span class="skill-icon">' + (glyphs[skill.id] || "+") + '</span><span class="skill-card-copy"><strong>' + escapeHtml(localizedText(skill.name)) + '</strong><span>' + escapeHtml(localizedText(skill.description)) + '</span></span><span class="skill-card-count">' + escapeHtml(skill.command_count) + " 条只读检查 · " + escapeHtml(readiness) + "</span></button>";
  });
  const listEmpty = state.skills.length ? '<p class="skill-empty">没有找到匹配的技能。</p>' : '<p class="skill-empty">尚未发现技能包。请检查本地 skills/ 目录。</p>';
  const railItems = query ? matches.slice(0, 20) : matches.slice(0, 3);
  $("#skillGrid").innerHTML = railItems.length ? createCards(railItems).join("") + (!query && matches.length > railItems.length ? '<p class="skill-list-note">显示前 ' + railItems.length + " 项，输入关键词筛选其余技能（共 " + matches.length + " 个）</p>" : "") : listEmpty;
  $("#skillPickerGrid").innerHTML = matches.length ? createCards(matches).join("") : listEmpty;
  if ($("#skillSearchInput").value !== state.skillQuery) $("#skillSearchInput").value = state.skillQuery;
  if ($("#skillPickerSearch").value !== state.skillQuery) $("#skillPickerSearch").value = state.skillQuery;
  const selectedSkill = state.skills.find((skill) => skill.id === state.selectedSkill);
  const activeLabel = state.manualSkill && selectedSkill ? localizedText(selectedSkill.name) + " · 已选择" : selectedSkill ? "自动匹配（最近：" + localizedText(selectedSkill.name) + "）" : "自动匹配（不指定技能）";
  $("#activeSkillLabel").textContent = activeLabel;
  $("#autoSkillSelect").classList.toggle("active", !state.manualSkill);
  $("#autoSkillPicker").classList.toggle("active", !state.manualSkill);
  $("#quickCheckupBtn").disabled = state.busy || !selectedSkill || !state.manualSkill || selectedSkill.demo_ready === false;
  $("#skillPickerBtn").disabled = state.busy || !state.skills.length;
  $("#skillSelectionNote").textContent = state.manualSkill ? "已选择该技能；开始排查将使用此技能。" : "保持自动匹配，发送问题后由本机技能路由判断。";
}

function selectSkill(skillId) {
  if (state.busy) return;
  state.selectedSkill = skillId || null;
  state.manualSkill = Boolean(skillId);
  const conversation = activeConversation();
  if (conversation) {
    conversation.skillId = state.selectedSkill;
    conversation.manualSkill = state.manualSkill;
  }
  renderSkills();
  if ($("#skillPickerDialog").open) $("#skillPickerDialog").close();
  storeConversations();
  localizePage();
}

function handleSkillListClick(event) {
  const button = event.target.closest("[data-skill]");
  if (button) selectSkill(button.dataset.skill);
}

function setView(name) {
  state.activeView = name;
  const labels = { chat: "诊断对话", qa: "知识问答", manuals: "手册与索引", memory: "长期记忆", evidence: "Evidence 对比", status: "系统状态" };
  $$(".page-view").forEach((view) => {
    const active = view.id === name + "View";
    view.hidden = !active;
    view.classList.toggle("active", active);
  });
  $$(".nav-item[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $("#topbarPageTitle").textContent = labels[name] || "工作区";
}

function activeConversation() {
  return state.conversations.find((conversation) => conversation.id === state.activeConversationId) || null;
}

function storeConversations() {
  try {
    localStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify({
      activeConversationId: state.activeConversationId,
      conversations: state.conversations,
    }));
  } catch (error) {
    const note = $("#sidebarFootnote");
    if (note) note.textContent = "本机存储空间不足，当前会话尚未保存";
  }
}

function sourceLocaleConversationHtml() {
  if (state.locale !== "en") return $("#chatFeed").innerHTML;
  const root = document.createElement("div");
  root.innerHTML = $("#chatFeed").innerHTML;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walk.nextNode())) {
    if (isUserContent(node)) continue;
    let restored = node.nodeValue;
    ZH_TRANSLATION_ENTRIES.forEach(([english, chinese]) => { restored = restored.replaceAll(english, chinese); });
    node.nodeValue = restored;
  }
  return root.innerHTML;
}

function loadEvidenceInputs() {
  try {
    const saved = JSON.parse(localStorage.getItem(EVIDENCE_STORAGE_KEY) || "null");
    if (!saved || typeof saved !== "object") return;
    if (saved.manualMinutes != null) $("#manualMinutes").value = saved.manualMinutes;
    if (saved.manualSteps != null) $("#manualSteps").value = saved.manualSteps;
    if (saved.manualLookups != null) $("#manualLookups").value = saved.manualLookups;
    if (saved.manualNotes != null) $("#manualNotes").value = saved.manualNotes;
  } catch (error) {
    // The form falls back to its documented comparison baseline.
  }
}

function storeEvidenceInputs() {
  try {
    localStorage.setItem(EVIDENCE_STORAGE_KEY, JSON.stringify({
      manualMinutes: $("#manualMinutes").value,
      manualSteps: $("#manualSteps").value,
      manualLookups: $("#manualLookups").value,
      manualNotes: $("#manualNotes").value,
    }));
  } catch (error) {
    // Evidence remains usable for the current page even if local storage is unavailable.
  }
}

function loadSkillReplays() {
  try {
    const saved = JSON.parse(localStorage.getItem(SKILL_REPLAY_STORAGE_KEY) || "{}");
    state.skillReplays = saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch (error) {
    state.skillReplays = {};
  }
}

function storeSkillReplays() {
  try {
    localStorage.setItem(SKILL_REPLAY_STORAGE_KEY, JSON.stringify(state.skillReplays));
  } catch (error) {
    const note = $("#sidebarFootnote");
    if (note) note.textContent = "技能回放未能保存在本机浏览器";
  }
}

function conversationTime(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    const prefix = state.locale === "en" ? "Today " : "今天 ";
    const locale = state.locale === "en" ? "en" : "zh-CN";
    return prefix + date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  }
  if (state.locale === "en") return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
  return (date.getMonth() + 1) + "月" + date.getDate() + "日";
}

function conversationItemsHtml() {
  if (!state.conversations.length) return '<div class="conversation-empty">暂无对话<br>点击上方按钮新建</div>';
  return state.conversations.slice().sort((a, b) => b.updatedAt - a.updatedAt).map((conversation) => {
    const title = conversation.title || "新的排障会话";
    const active = conversation.id === state.activeConversationId;
    const disabled = state.busy ? " disabled" : "";
    return '<div class="conversation-row ' + (active ? "active" : "") + '"><button class="conversation-select" type="button" data-open-conversation="' + escapeHtml(conversation.id) + '"' + disabled + '><span class="conversation-title">' + escapeHtml(title) + '</span><span class="conversation-time">' + escapeHtml(conversationTime(conversation.updatedAt)) + '</span></button><button class="conversation-rename" type="button" data-rename-conversation="' + escapeHtml(conversation.id) + '" aria-label="重命名对话：' + escapeHtml(title) + '" title="重命名此对话"' + disabled + '>✎</button><button class="conversation-delete" type="button" data-delete-conversation="' + escapeHtml(conversation.id) + '" aria-label="删除对话：' + escapeHtml(title) + '" title="删除此对话"' + disabled + '>×</button></div>';
  }).join("");
}

function renderConversationLists() {
  const html = conversationItemsHtml();
  $("#conversationList").innerHTML = html;
  $("#conversationDialogList").innerHTML = html;
  $("#conversationCount").textContent = String(state.conversations.length);
}

function persistActiveConversation() {
  const conversation = activeConversation();
  if (conversation) {
    if (!Array.isArray(conversation.messages)) conversation.messages = [];
    conversation.html = sourceLocaleConversationHtml();
    conversation.sources = state.sources;
    conversation.lastRun = state.lastRun;
    conversation.progressStep = state.progressStep;
    conversation.progressLabel = state.progressLabel;
    conversation.skillId = state.selectedSkill;
    conversation.manualSkill = state.manualSkill;
    conversation.updatedAt = Date.now();
  }
  storeConversations();
  renderConversationLists();
}

function makeConversation() {
  const now = Date.now();
  return {
    id: now.toString(36) + "-" + Math.random().toString(36).slice(2, 8),
    title: "新的排障会话",
    titleText: "",
    titleLocale: state.locale,
    titleManual: false,
    createdAt: now,
    updatedAt: now,
    html: "",
    sources: [],
    lastRun: null,
    progressStep: 0,
    progressLabel: "等待开始",
    skillId: null,
    manualSkill: false,
    messages: [],
  };
}

function restoreConversationHtml(conversation) {
  const host = document.createElement("div");
  host.innerHTML = conversation.html || state.welcomeHtml;
  host.querySelectorAll(".agent-run").forEach((run) => {
    const intro = run.querySelector(".run-intro");
    if (intro && (intro.textContent.includes("当前为本地演示流") || intro.textContent.includes("尚未连接真实诊断引擎"))) {
      run.dataset.demo = "true";
      intro.textContent = "这是浏览器保存的旧版演示记录；新发起的诊断已接入本机技能引擎。";
    }
  });
  host.querySelectorAll("[data-run-badge]").forEach((badge) => {
    const run = badge.closest(".agent-run");
    const completion = run && run.querySelector("[data-run-complete]");
    if (completion && completion.hasAttribute("hidden")) {
      badge.textContent = "上次执行未完成";
      badge.classList.add("demo");
      const intro = run.querySelector(".run-intro");
      if (intro) intro.textContent = "已恢复本机保存的对话。上次排查未完成，保留已回显内容，可重新发起排查。";
    }
  });
  return host.innerHTML;
}

function renderActiveConversation() {
  const conversation = activeConversation();
  if (!conversation) return;
  $("#threadTitle").textContent = conversation.title || "新的排障会话";
  $("#chatFeed").innerHTML = restoreConversationHtml(conversation);
  state.sources = Array.isArray(conversation.sources) ? conversation.sources : [];
  state.lastRun = conversation.lastRun || null;
  state.selectedSkill = conversation.skillId || null;
  state.manualSkill = Boolean(conversation.manualSkill && state.selectedSkill);
  state.currentRunEl = null;
  renderSourceShelf();
  setProgress(conversation.progressStep || 0, conversation.progressLabel || "等待开始");
  if (state.lastRun) updateEvidenceMetrics();
  else $("#aiMetrics").innerHTML = '<div><strong>—</strong><span>耗时</span></div><div><strong>—</strong><span>采集命令</span></div><div><strong>—</strong><span>报告条目</span></div><div><strong>—</strong><span>手册出处</span></div>';
  generateEvidence();
  renderSkills();
  renderConversationLists();
  scrollChatToBottom();
}

function createNewConversation() {
  if (state.busy) return;
  persistActiveConversation();
  const conversation = makeConversation();
  state.conversations.unshift(conversation);
  state.activeConversationId = conversation.id;
  state.selectedSkill = null;
  state.manualSkill = false;
  state.sources = [];
  state.lastRun = null;
  state.currentRunEl = null;
  renderActiveConversation();
  setView("chat");
  setProgress(0, "等待开始");
  storeConversations();
  $("#conversationDialog").close();
  $("#faultText").focus();
}

function switchConversation(id) {
  if (state.busy) {
    $("#conversationDialog").close();
    return;
  }
  if (id === state.activeConversationId) {
    setView("chat");
    $("#conversationDialog").close();
    return;
  }
  persistActiveConversation();
  if (!state.conversations.some((conversation) => conversation.id === id)) return;
  state.activeConversationId = id;
  renderActiveConversation();
  setView("chat");
  storeConversations();
  $("#conversationDialog").close();
}

function deleteConversation(id) {
  if (state.busy) return;
  const conversation = state.conversations.find((item) => item.id === id);
  if (!conversation) return;
  if (!window.confirm('确定删除对话“' + (conversation.title || "新的排障会话") + '”吗？删除后无法恢复。')) return;
  persistActiveConversation();
  state.conversations = state.conversations.filter((item) => item.id !== id);
  if (state.activeConversationId === id) {
    if (!state.conversations.length) state.conversations.push(makeConversation());
    state.activeConversationId = state.conversations.slice().sort((a, b) => b.updatedAt - a.updatedAt)[0].id;
    renderActiveConversation();
    setView("chat");
  } else {
    renderConversationLists();
  }
  storeConversations();
}

function handleConversationListClick(event) {
  const renameButton = event.target.closest("[data-rename-conversation]");
  if (renameButton) {
    beginConversationRename(renameButton.dataset.renameConversation);
    return;
  }
  const deleteButton = event.target.closest("[data-delete-conversation]");
  if (deleteButton) {
    deleteConversation(deleteButton.dataset.deleteConversation);
    return;
  }
  const openButton = event.target.closest("[data-open-conversation]");
  if (openButton) switchConversation(openButton.dataset.openConversation);
}

function beginConversationRename(id) {
  const conversation = state.conversations.find((item) => item.id === id);
  if (!conversation) return;
  state.renameConversationId = id;
  $("#conversationRenameInput").value = conversation.title || "新的排障会话";
  $("#renameFeedback").textContent = "";
  if ($("#conversationDialog").open) $("#conversationDialog").close();
  $("#conversationRenameDialog").showModal();
  $("#conversationRenameInput").focus();
  $("#conversationRenameInput").select();
}

function saveConversationRename(event) {
  event.preventDefault();
  const conversation = state.conversations.find((item) => item.id === state.renameConversationId);
  const title = $("#conversationRenameInput").value.trim();
  if (!conversation || !title) {
    $("#renameFeedback").textContent = "标题不能为空。";
    return;
  }
  conversation.title = title;
  conversation.titleManual = true;
  conversation.titleText = "";
    conversation.updatedAt = Date.now();
    if (!Array.isArray(conversation.messages)) conversation.messages = [];
  if (conversation.id === state.activeConversationId) $("#threadTitle").textContent = title;
  state.renameConversationId = null;
  storeConversations();
  renderConversationLists();
  $("#conversationRenameDialog").close();
}

function loadConversations() {
  state.welcomeHtml = $("#chatFeed").innerHTML;
  try {
    const saved = JSON.parse(localStorage.getItem(CONVERSATION_STORAGE_KEY) || "null");
    if (saved && Array.isArray(saved.conversations)) {
      state.conversations = saved.conversations.filter((item) => item && typeof item.id === "string" && typeof item.title === "string");
      state.activeConversationId = saved.activeConversationId;
    }
  } catch (error) {
    state.conversations = [];
  }
  if (!state.conversations.length) state.conversations.push(makeConversation());
  if (!state.conversations.some((item) => item.id === state.activeConversationId)) {
    state.activeConversationId = state.conversations.slice().sort((a, b) => b.updatedAt - a.updatedAt)[0].id;
  }
  renderActiveConversation();
  storeConversations();
}

function scrollChatToBottom() {
  const feed = $("#chatFeed");
  feed.scrollTop = feed.scrollHeight;
}

function fallbackConversationTitle(text, skillId) {
  const english = state.locale === "en";
  const source = String(text || "").trim();
  const isMes = /mes/i.test(source);
  const titles = {
    "net-unreachable": english ? (isMes ? "MES network · service unreachable" : "Network connectivity issue") : (isMes ? "MES 业务网 · 连通异常" : "网络连通问题"),
    "disk-full": english ? "Switch storage alert" : "交换机存储空间告警",
    "service-down": english ? "Switch login failure" : "交换机登录故障",
    "log-audit": english ? "Log audit · suspicious activity" : "日志审计 · 异常活动",
  };
  if (skillId && titles[skillId]) return titles[skillId];
  const cleaned = source.replace(/^(一键体检[:：]|run selected skill[:：])/i, "").replace(/\s+/g, " ");
  return cleaned.slice(0, english ? 48 : 22) + (cleaned.length > (english ? 48 : 22) ? "…" : "");
}

function setConversationTitle(conversationId, title, expectedTitle) {
  const conversation = state.conversations.find((item) => item.id === conversationId);
  if (!conversation || !title || (expectedTitle && conversation.title !== expectedTitle)) return;
  conversation.title = title.trim().slice(0, 64);
  conversation.updatedAt = Date.now();
  if (conversation.id === state.activeConversationId) $("#threadTitle").textContent = conversation.title;
  storeConversations();
  renderConversationLists();
}

async function requestConversationTitle(text, skillId, conversationId) {
  const locale = state.locale;
  const conversation = state.conversations.find((item) => item.id === conversationId);
  if (conversation) {
    conversation.titleText = text;
    conversation.titleLocale = locale;
    conversation.titleManual = false;
  }
  const fallback = fallbackConversationTitle(text, skillId);
  setConversationTitle(conversationId, fallback);
  try {
    const result = await api("/api/title", { method: "POST", body: JSON.stringify({ text, skill: skillId, locale }) });
    const latest = state.conversations.find((item) => item.id === conversationId);
    if (latest && latest.titleManual !== true && latest.titleLocale === locale && state.locale === locale && result.title) {
      setConversationTitle(conversationId, result.title, fallback);
    }
  } catch (error) {
    // The deterministic local summary remains available if title generation is unavailable.
  }
}

function appendUserMessage(text) {
  const message = document.createElement("article");
  message.className = "message user-message";
  message.innerHTML = '<div class="message-avatar user-avatar" aria-hidden="true">我</div><div class="message-body"><div class="message-meta"><strong>现场描述</strong></div><div class="user-bubble">' + escapeHtml(text) + "</div></div>";
  $("#chatFeed").appendChild(message);
  persistActiveConversation();
  scrollChatToBottom();
}

function appendNotice(title, body, kind) {
  const message = document.createElement("article");
  message.className = "message assistant-message";
  message.innerHTML = '<div class="message-avatar assistant-avatar" aria-hidden="true">AI</div><div class="message-body"><div class="message-meta"><strong>离线运维 Agent</strong><span>本机处理</span></div><div class="answer-box ' + (kind === "error" ? "no-source" : "") + '"><strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(body) + "</p></div></div>";
  $("#chatFeed").appendChild(message);
  persistActiveConversation();
  scrollChatToBottom();
  return message;
}

function appendManualAnswer(result) {
  const citations = result.citations || [];
  const sourceButtons = citations.map((citation) => {
    const index = state.sources.push(citation) - 1;
    return '<button class="source-button" type="button" data-source-index="' + index + '">' + escapeHtml(citation.label || "手册出处") + '</button>';
  }).join("");
  const message = document.createElement("article");
  message.className = "message assistant-message manual-answer-message";
  const titles = { generated: "手册整理回答", extracted: "手册原文摘录", clarify: "需要补充信息", intro: "离线助手", out_of_scope: "超出手册范围", not_found: "手册依据不足", remembered: "已写入长期记忆", diagnosed: "现场排障总结" };
  const badges = { generated: "已通过出处与命令核对", extracted: "模型整理未通过 · 展示原文", clarify: "等待补充信息", intro: "本机回答", out_of_scope: "范围分流", not_found: "未找到依据", remembered: "仅保存在本机", diagnosed: "已执行白名单诊断" };
  const title = titles[result.answer_type] || (result.found ? "手册回答" : "手册依据不足");
  const badge = badges[result.answer_type] || (result.found ? "手册回答" : "未发布无依据结论");
  const warnings = (result.warnings || []).map((warning) => '<div class="demo-note">' + escapeHtml(warning) + '</div>').join("");
  const body = result.answer_type === "diagnosed" ? String(result.answer || "").split("\n\n诊断报告：", 1)[0] : (result.answer || "手册中未找到依据。");
  const suggestion = result.suggestion ? '<div class="demo-note agent-suggestion">' + escapeHtml(result.suggestion) + '</div>' : "";
  const positive = result.found || ["intro", "clarify", "remembered", "diagnosed"].includes(result.answer_type);
  message.innerHTML = '<div class="message-avatar assistant-avatar" aria-hidden="true">AI</div><div class="message-body"><div class="message-meta"><strong>离线运维 Agent</strong><span>' + escapeHtml(badge) + '</span></div>' + warnings + '<div class="answer-box ' + (positive ? "" : "no-source") + '"><strong>' + escapeHtml(title) + '</strong><p class="manual-answer-text">' + escapeHtml(body) + '</p>' + suggestion + '<div class="answer-meta">' + escapeHtml((result.retrieval_mode || "本地分流") + " · " + Number(result.latency_s || 0).toFixed(1) + " 秒") + '</div>' + (sourceButtons ? '<div class="source-list">' + sourceButtons + '</div>' : "") + "</div></div>";
  $("#chatFeed").appendChild(message);
  renderSourceShelf();
  persistActiveConversation();
  scrollChatToBottom();
}

function renderCompletedRun(run, skillId) {
  if (!run) return;
  const runEl = appendRunShell(skillId || run.skill || "自动匹配技能");
  runEl.dataset.runId = run.run_id || "";
  updateRunSkill(runEl, run.skill || skillId);
  (run.collected || run.commands || []).forEach(appendCommand);
  renderRules(run.rule_path || run.rules || []);
  if (run.ai_reasoning) {
    const section = $("[data-ai-section]", runEl);
    section.hidden = false;
    $("[data-ai]", runEl).textContent = "AI 补充推理：" + run.ai_reasoning;
  }
  renderReport(run);
  state.lastRun = run;
  $("[data-run-complete]", runEl).hidden = false;
  const simulated = run.execution_mode === "simulation";
  const badge = $("[data-run-badge]", runEl);
  badge.classList.toggle("demo", simulated);
  badge.textContent = (simulated ? "模拟诊断完成" : "真实诊断完成") + " · " + Number(run.elapsed || 0).toFixed(1) + "s";
  if (simulated) {
    $(".run-intro", runEl).textContent = "当前运行经过真实技能引擎与规则树，但采集输出来自明确标识的 simulation 固件。";
  }
  updateEvidenceMetrics();
  generateEvidence();
  persistActiveConversation();
}

function setProgress(active, stateText) {
  state.progressStep = active;
  state.progressLabel = stateText;
  const conversation = activeConversation();
  if (conversation) {
    conversation.progressStep = active;
    conversation.progressLabel = stateText;
    storeConversations();
  }
  $$(".step-item").forEach((item) => {
    const step = Number(item.dataset.step);
    item.classList.toggle("complete", step < active || stateText === "已完成");
    item.classList.toggle("active", step === active && stateText !== "已完成");
  });
  $("#runState").textContent = stateText;
}

function appendRunShell(skillId) {
  const message = document.createElement("article");
  message.className = "message assistant-message";
  message.innerHTML = '<div class="message-avatar assistant-avatar" aria-hidden="true">AI</div><div class="message-body"><div class="message-meta"><strong>离线运维 Agent</strong><span data-run-skill-meta>本机技能库 · ' + escapeHtml(skillName(skillId)) + '</span></div><div class="message-content"><p class="run-intro-text">已匹配 <strong data-run-skill-name>' + escapeHtml(skillName(skillId)) + '</strong>。现在开始逐条运行白名单只读检查，并整理规则判定与手册出处。</p><div class="agent-run"><div class="agent-run-head"><strong>诊断执行过程</strong><span class="run-badge" data-run-badge>正在连接本地诊断流</span></div><div class="run-intro">执行期间只采集状态，不会运行修复写操作。</div><section class="run-section"><div class="run-section-title">采集过程 <span data-command-count>等待命令回显</span></div><div class="command-list" data-command-list><div class="run-empty">正在等待第一条命令…</div></div></section><section class="run-section"><div class="run-section-title">规则树判定 <span>路径可展开核对</span></div><div class="inline-rules" data-rules><div class="run-empty">等待采集结果。</div></div></section><section class="run-section" data-ai-section hidden><div class="run-section-title">AI 补充推理 <span>与规则树结论区分展示</span></div><div class="ai-reasoning" data-ai></div></section><section class="run-section"><div class="run-section-title">诊断报告 <span data-report-count>等待报告</span></div><div class="findings-list" data-findings><div class="run-empty">等待报告生成。</div></div><div data-unresolved></div></section><div class="run-complete" data-run-complete hidden>✓ <span>诊断完成</span><button class="save-skill-inline" type="button" data-save-skill>存为技能</button></div></div></div></div>';
  $("#chatFeed").appendChild(message);
  state.currentRunEl = message;
  persistActiveConversation();
  scrollChatToBottom();
  return message;
}

function updateRunSkill(runEl, skillId) {
  if (!runEl || !skillId) return;
  const name = skillName(skillId);
  const meta = $("[data-run-skill-meta]", runEl);
  const title = $("[data-run-skill-name]", runEl);
  if (meta) meta.textContent = "本机技能库 · " + name;
  if (title) title.textContent = name;
}

function statusText(status) {
  return { success: "成功", failed: "失败", timeout: "超时", rejected: "已拒绝" }[status] || status || "完成";
}

function appendCommand(command) {
  const list = $("[data-command-list]", state.currentRunEl);
  if (!list) return;
  const empty = $(".run-empty", list);
  if (empty) empty.remove();
  const row = document.createElement("article");
  row.className = "command-card " + escapeHtml(command.status);
  row.innerHTML = '<div class="command-main"><code>' + escapeHtml(command.display || command.cmd) + '</code><pre class="command-output">' + escapeHtml(command.output || "未能获取输出") + '</pre></div><div class="command-meta"><span class="command-state">' + escapeHtml(statusText(command.status)) + '</span><span>' + escapeHtml(command.duration_s ?? command.duration ?? 0) + "s</span></div>";
  list.appendChild(row);
  const count = $$(".command-card", list).length;
  $("[data-command-count]", state.currentRunEl).textContent = count + " 条命令已回显";
  persistActiveConversation();
  scrollChatToBottom();
}

function renderRules(rules) {
  const target = $("[data-rules]", state.currentRunEl);
  if (!target) return;
  target.innerHTML = (rules || []).length ? rules.map((rule, index) => {
    const hit = rule.state === "hit";
    const ruleId = rule.id || rule.rule_id || ("r" + (index + 1));
    return '<details class="inline-rule ' + (hit ? "" : "miss") + '"><summary><span class="rule-check">' + (hit ? "✓" : "–") + '</span><span class="inline-rule-copy"><strong>' + (hit ? "命中规则 " : "未命中规则 ") + escapeHtml(ruleId) + " · " + escapeHtml(rule.label || "未命名条件") + '</strong><span class="inline-rule-branch">走向分支：' + escapeHtml(rule.branch || "未提供") + '</span></span></summary><div class="inline-rule-detail">规则树判定 · ' + (hit ? "条件命中" : "条件未命中") + " · 分支：" + escapeHtml(rule.branch || "未提供") + "</div></details>";
  }).join("") : '<div class="run-empty">未返回规则判定路径。</div>';
  persistActiveConversation();
}

function severityLabel(severity) {
  return { critical: "严重", warning: "警告", ok: "正常" }[severity] || severity;
}

function renderReport(report) {
  const target = $("[data-findings]", state.currentRunEl);
  const findings = report.findings || [];
  if (!target) return;
  target.innerHTML = findings.map((finding, findingIndex) => {
    const sources = finding.sources || [];
    const sourceHtml = sources.length ? '<div class="source-list">' + sources.map((source) => {
      const index = state.sources.push(source) - 1;
      return '<button class="source-button" type="button" data-source-index="' + index + '">' + escapeHtml(source.label || "查看手册出处") + "</button>";
    }).join("") + '</div>' : '<span class="source-missing">手册中未找到依据</span>';
    const fixes = (finding.fix_commands || []).map((command) => "<li>" + escapeHtml(command) + "</li>").join("");
    return '<details class="finding-card" data-severity="' + escapeHtml(finding.severity) + '" ' + (findingIndex === 0 ? "open" : "") + '><summary><span class="severity-tag ' + escapeHtml(finding.severity) + '">' + escapeHtml(severityLabel(finding.severity)) + '</span><span>' + escapeHtml(finding.title) + '</span></summary><div class="finding-detail"><p><strong>现象：</strong>' + escapeHtml(finding.symptom) + '</p><p><strong>根因：</strong>' + escapeHtml(finding.root_cause) + '</p><p><strong>判定来源：</strong>' + escapeHtml(finding.judged_by === "rule" ? "规则树判定" : "AI 补充推理") + '</p>' + (fixes ? '<div class="fix-warning">以下为建议步骤，不会自动执行。操作前请备份配置。</div><strong>建议处理方式</strong><ol class="fix-list">' + fixes + '</ol>' : "") + '<div><strong>手册依据</strong>' + sourceHtml + '</div></div></details>';
  }).join("") || '<div class="run-empty">未返回诊断条目。</div>';
  $("[data-report-count]", state.currentRunEl).textContent = findings.length + " 条分级结论";
  const unresolved = report.unresolved || [];
  $("[data-unresolved]", state.currentRunEl).innerHTML = unresolved.length ? '<div class="unresolved-note"><strong>仍需人工确认：</strong>' + escapeHtml(unresolved.join("；")) + "</div>" : "";
  renderSourceShelf();
  persistActiveConversation();
}

function renderSourceShelf() {
  $("#sourceCount").textContent = String(state.sources.length);
  $("#sourceShelf").innerHTML = state.sources.length ? state.sources.map((source, index) => '<div class="source-shelf-item"><button type="button" data-source-index="' + index + '">' + escapeHtml(source.label || "手册出处") + '</button><p>' + escapeHtml(source.text || "") + "</p></div>").join("") : '<p class="rail-empty">诊断完成后显示系统返回的手册出处。</p>';
}

function openSource(index) {
  const source = state.sources[Number(index)];
  if (!source) return;
  $("#sourceTitle").textContent = source.label || "手册出处";
  $("#sourceText").textContent = source.text || "系统没有返回原文片段。";
  $("#sourceDialog").showModal();
}

function setBusy(busy) {
  state.busy = busy;
  $("#sendBtn").disabled = busy;
  $("#faultText").disabled = busy;
  $("#newChatBtn").disabled = busy;
  $("#dialogNewChatBtn").disabled = busy;
  $("#quickCheckupBtn").disabled = busy || !state.selectedSkill || !state.manualSkill;
  $("#skillPickerBtn").disabled = busy || !state.skills.length;
  $("#interactionMode").disabled = busy;
  $("#executionMode").disabled = busy;
  const diagnostic = $("#interactionMode").value === "diagnose";
  $("#sendBtn").querySelector("span:first-child").textContent = busy ? "正在处理" : diagnostic ? "开始排查" : "查询手册";
  renderSkills();
  renderConversationLists();
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.busy) return;
  const text = $("#faultText").value.trim();
  if (!text) return;
  const conversationId = state.activeConversationId;
  const diagnostic = $("#interactionMode").value === "diagnose";
  const shouldGenerateTitle = ["新的排障会话", "New troubleshooting chat"].includes(activeConversation()?.title || "");
  const conversation = activeConversation();
  const history = Array.isArray(conversation?.messages) ? conversation.messages.filter((item) => item.status === "complete").map(({ role, content, action, query, suggest_skill }) => ({ role, content, action, query, suggest_skill })) : [];
  appendUserMessage(text);
  if (conversation && !diagnostic) {
    if (!Array.isArray(conversation.messages)) conversation.messages = [];
    conversation.messages.push({ role: "user", content: text, status: "complete" });
  }
  const provisionalTitle = fallbackConversationTitle(text, state.manualSkill ? state.selectedSkill : null);
  if (shouldGenerateTitle) {
    const conversation = activeConversation();
    if (conversation) {
      conversation.titleText = text;
      conversation.titleLocale = state.locale;
      conversation.titleManual = false;
    }
    setConversationTitle(conversationId, provisionalTitle);
  }
  $("#faultText").value = "";
  if (diagnostic) {
    setBusy(true);
    setProgress(1, "准备诊断");
    if (shouldGenerateTitle) requestConversationTitle(text, state.manualSkill ? state.selectedSkill : null, conversationId);
    runDiagnostic(state.manualSkill ? state.selectedSkill : null, text, $("#executionMode").value);
    return;
  }
  setBusy(true);
  setProgress(1, "检索手册");
  const requestId = self.crypto?.randomUUID ? self.crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2);
  const started = Date.now();
  const waiting = appendNotice("正在查询本地手册", "正在检索、生成并逐条核验依据 · 0 秒", "");
  const timer = window.setInterval(() => {
    const paragraph = waiting.querySelector(".answer-box p");
    if (paragraph) paragraph.textContent = "正在检索、生成并逐条核验依据 · " + Math.floor((Date.now() - started) / 1000) + " 秒";
  }, 1000);
  try {
    const result = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: text, history, conversation_id: conversationId, request_id: requestId, locale: state.locale, agent_mode: true, execution_mode: $("#executionMode").value }) });
    waiting.remove();
    appendManualAnswer(result);
    if (result.run) renderCompletedRun(result.run, result.skill);
    if (result.remembered?.length || result.run) await loadMemories();
    if (conversation) conversation.messages.push({ role: "assistant", content: result.answer || "手册中未找到依据。", status: "complete", requestId, citations: result.citations || [], found: Boolean(result.found), action: result.action, answerType: result.answer_type, query: result.query, suggest_skill: result.suggest_skill });
    if (shouldGenerateTitle) requestConversationTitle(text, null, conversationId);
    setProgress(4, "已完成");
  } catch (error) {
    waiting.remove();
    appendNotice("问答失败", error.message + (error.code === "busy" ? "。请等待当前问答或建库结束后明确重试；系统不会自动重复提交。" : ""), "error");
    if (conversation) conversation.messages.push({ role: "assistant", content: error.message, status: "failed", requestId });
    setProgress(0, "问答失败");
  } finally {
    window.clearInterval(timer);
    setBusy(false);
    persistActiveConversation();
  }
}

async function runDiagnostic(skillId, issue = "", executionMode = "real") {
  const skill = state.skills.find((item) => item.id === skillId);
  if (skill && skill.valid === false) {
    appendNotice("技能不可执行", (skill.errors || []).join("；") || "技能包未通过校验。", "error");
    setBusy(false);
    setProgress(0, "等待开始");
    return;
  }
  let created;
  try {
    created = await api("/api/diagnose/runs", { method: "POST", body: JSON.stringify({ skill_id: skillId, issue, execution_mode: executionMode, target: { kind: "local", display_name: "localhost" } }) });
  } catch (error) {
    appendNotice("无法启动诊断", error.message, "error");
    setBusy(false);
    setProgress(0, "启动失败");
    return;
  }
  const runEl = appendRunShell(skillId || "自动匹配技能");
  runEl.dataset.runId = created.run_id;
  state.sources = [];
  renderSourceShelf();
  setProgress(2, "采集数据");
  const source = new EventSource("/api/diagnose/runs/" + encodeURIComponent(created.run_id) + "/events");
  let serverErrorHandled = false;
  source.addEventListener("start", (event) => {
    const payload = JSON.parse(event.data);
    updateRunSkill(runEl, payload.skill);
    runEl.dataset.demo = String(payload.execution_mode !== "real");
    const badge = $("[data-run-badge]", runEl);
    if (payload.execution_mode === "simulation") {
      badge.classList.add("demo");
      badge.textContent = "模拟器固定输出";
      $(".run-intro", runEl).textContent = "当前运行经过真实技能引擎与规则树，但采集输出来自明确标识的 simulation 固件。";
    } else {
      badge.textContent = "本机白名单只读执行中";
    }
    persistActiveConversation();
  });
  source.addEventListener("error", (event) => {
    if (!event.data) return;
    const payload = JSON.parse(event.data);
    serverErrorHandled = true;
    const badge = $("[data-run-badge]", runEl);
    badge.textContent = "诊断失败";
    appendNotice("诊断失败", payload.message || "诊断未完成。", "error");
    source.close();
    setBusy(false);
    setProgress(0, "等待开始");
    persistActiveConversation();
  });
  source.addEventListener("collect", (event) => appendCommand(JSON.parse(event.data)));
  source.addEventListener("rules", (event) => {
    setProgress(3, "分析判定");
    const payload = JSON.parse(event.data);
    renderRules(payload.rule_path || payload.rules || []);
  });
  source.addEventListener("ai", (event) => {
    const payload = JSON.parse(event.data);
    const section = $("[data-ai-section]", runEl);
    section.hidden = false;
    $("[data-ai]", runEl).textContent = (payload.source || "AI 补充推理") + "：" + (payload.text || "未返回补充说明。");
    persistActiveConversation();
  });
  source.addEventListener("report", (event) => {
    setProgress(4, "整理报告");
    renderReport(JSON.parse(event.data));
  });
  source.addEventListener("done", (event) => {
    state.lastRun = JSON.parse(event.data);
    $("[data-run-complete]", runEl).hidden = false;
    $("[data-run-badge]", runEl).textContent = (state.lastRun.execution_mode === "simulation" ? "模拟诊断完成" : "真实诊断完成") + " · " + state.lastRun.elapsed + "s";
    setProgress(4, "已完成");
    setBusy(false);
    updateEvidenceMetrics();
    generateEvidence();
    persistActiveConversation();
    source.close();
    scrollChatToBottom();
  });
  source.onerror = () => {
    if (serverErrorHandled) return;
    const badge = $("[data-run-badge]", runEl);
    if ($("[data-run-complete]", runEl).hasAttribute("hidden")) {
      badge.classList.add("demo");
      badge.textContent = "本地连接中断";
      appendNotice("诊断流中断", "请检查本地服务状态。已回显的数据仍可查看；未完成部分不会补造。", "error");
    }
    source.close();
    setBusy(false);
    setProgress(0, "连接中断");
    persistActiveConversation();
  };
}

async function runSavedSkillReplay(skillId, replay) {
  const runEl = appendRunShell(skillId);
  state.sources = [];
  renderSourceShelf();
  setProgress(2, "模拟回放");
  const badge = $("[data-run-badge]", runEl);
  badge.classList.add("demo");
  badge.textContent = "本地技能回放 · Mock";
  $(".run-intro", runEl).textContent = "正在回放保存此技能时的本地演示数据，不连接真实设备。";
  for (const command of replay.commands || []) {
    await new Promise((resolve) => window.setTimeout(resolve, 180));
    appendCommand(command);
  }
  setProgress(3, "分析判定");
  renderRules(replay.rules || []);
  if (replay.ai_reasoning) {
    const section = $("[data-ai-section]", runEl);
    section.hidden = false;
    $("[data-ai]", runEl).textContent = "AI 补充推理：" + replay.ai_reasoning;
  }
  setProgress(4, "整理报告");
  renderReport(replay);
  state.lastRun = replay;
  $("[data-run-complete]", runEl).hidden = false;
  badge.textContent = "本地演示回放完成";
  setProgress(4, "已完成");
  setBusy(false);
  updateEvidenceMetrics();
  generateEvidence();
  persistActiveConversation();
  scrollChatToBottom();
}

function openSkillDialog() {
  if (!state.lastRun) return;
  $("#saveSkillResult").textContent = "";
  $("#draftPreview").textContent = "将从服务端已完成运行 " + state.lastRun.run_id + " 复制并重新校验以下内容：\n- 已执行且通过白名单的 collect.yaml\n- 原技能的受限 rules.yaml\n- 可解析的 refs.yaml\n\n不会接受浏览器提交的任意命令或出处。";
  $("#skillDialog").showModal();
}

async function saveSkill() {
  if (!state.lastRun) return;
  $("#saveSkillResult").textContent = "正在写入本机技能库…";
  try {
    const result = await api("/api/skills/save", { method: "POST", body: JSON.stringify({ name: $("#skillName").value, run_id: state.lastRun.run_id }) });
    state.skills = (result.skills || state.skills).map((skill) => ({
      ...skill,
      demo_ready: Boolean(skill.valid),
    }));
    state.selectedSkill = result.skill_id;
    state.manualSkill = true;
    renderSkills();
    persistActiveConversation();
    $("#saveSkillResult").textContent = "已保存到本地技能库：" + result.skill_id;
    $("#saveSkillResult").classList.remove("error");
  } catch (error) {
    $("#saveSkillResult").textContent = error.message;
    $("#saveSkillResult").classList.add("error");
  }
}

async function askManual(event) {
  event.preventDefault();
  const question = $("#qaQuestion").value.trim();
  if (!question) return;
  $("#askBtn").disabled = true;
  $("#qaResult").innerHTML = '<div class="empty-card"><strong>正在检索本地手册</strong><p>只查询本机已建索引。</p></div>';
  try {
    const result = await api("/api/ask", { method: "POST", body: JSON.stringify({ question, locale: state.locale, agent_mode: false }) });
    const citations = result.citations || [];
    const demoNote = state.health && state.health.mock ? '<div class="demo-note">当前为 Mock 演示模式。下方答案与引用是固定样例，不代表已从真实手册核验；请切换到真实模式后再用于现场判断。</div>' : "";
    const answerTitle = result.found ? (state.health && state.health.mock ? "演示回答 · Mock" : "回答") : "手册中未找到依据";
    $("#qaResult").innerHTML = demoNote + '<article class="answer-box ' + (result.found ? "" : "no-source") + '"><strong>' + answerTitle + '</strong><p>' + escapeHtml(result.answer || "手册中未找到依据。") + "</p></article>" + (citations.length ? citations.map((citation) => '<article class="sample-item"><strong>' + escapeHtml(citation.label || "手册出处") + '</strong><p>' + escapeHtml(citation.text || "") + "</p></article>").join("") : '<div class="empty-card"><strong>没有可引用的手册片段</strong><p>索引未就绪或未检索到依据，请先检查手册索引。</p></div>');
  } catch (error) {
    $("#qaResult").innerHTML = '<div class="empty-card"><strong>查询失败</strong><p>' + escapeHtml(error.message) + "</p></div>";
  } finally {
    $("#askBtn").disabled = false;
  }
}

function renderSamples(samples) {
  $("#sampleCount").textContent = (samples || []).length + " 条";
  $("#sampleList").innerHTML = (samples || []).length ? samples.map((sample) => '<article class="sample-item"><strong>' + escapeHtml(sample.file) + (sample.section ? " · " + escapeHtml(sample.section) : "") + (sample.page ? " · P" + escapeHtml(sample.page) : "") + '</strong><p>' + escapeHtml(sample.text) + "</p></article>").join("") : '<div class="empty-card"><strong>暂无索引片段</strong><p>导入手册并重建索引后，会在这里展示抽样结果。</p></div>';
}

function renderMemories(payload) {
  state.memories = payload.memories || [];
  $("#memorySummary").textContent = "现场信息 " + Number(payload.facts_count || 0) + " 条 · 历史排障 " + Number(payload.episodes_count || 0) + " 条";
  $("#memoryList").innerHTML = state.memories.length ? state.memories.map((item) => {
    const kind = item.kind === "episode" ? "排障记录" : "现场信息";
    const when = new Date(Number(item.updated || item.created) * 1000).toLocaleString();
    return '<article class="memory-card" data-kind="' + escapeHtml(item.kind) + '"><div class="memory-card-copy"><div class="memory-card-head"><span class="memory-kind">' + kind + '</span><time>' + escapeHtml(when) + '</time>' + (item.skill ? '<span class="memory-card-skill">' + escapeHtml(skillName(item.skill)) + '</span>' : "") + '</div><p>' + escapeHtml(item.text) + '</p></div><button class="memory-delete" type="button" data-memory-delete="' + escapeHtml(item.id) + '">删除</button></article>';
  }).join("") : '<div class="empty-card"><strong>尚无长期记忆</strong><p>在主对话中说“记一下……”可保存现场信息；完成对话式排障后会自动保存排障记录。</p></div>';
}

async function loadMemories() {
  try {
    renderMemories(await api("/api/memory"));
  } catch (error) {
    $("#memorySummary").textContent = "长期记忆暂不可用";
    $("#memoryList").innerHTML = '<div class="empty-card"><strong>读取失败</strong><p>' + escapeHtml(error.message) + '</p></div>';
  }
}

async function deleteMemory(memoryId) {
  const item = state.memories.find((memory) => String(memory.id) === String(memoryId));
  if (!item || !window.confirm("确定删除这条本机记忆吗？删除后无法恢复。")) return;
  try {
    await api("/api/memory/" + encodeURIComponent(memoryId), { method: "DELETE" });
    await loadMemories();
  } catch (error) {
    $("#memorySummary").textContent = "删除失败：" + error.message;
  }
}

async function loadSamples() {
  try {
    const result = await api("/api/manuals/samples");
    renderSamples(result.samples || []);
  } catch (error) {
    renderSamples([]);
  }
}

async function uploadManual(file) {
  if (!file) return;
  const form = new FormData();
  form.append("manual", file);
  $("#manualResult").textContent = "正在将文件保存到本地知识库…";
  $("#manualResult").classList.remove("error");
  try {
    const result = await api("/api/manuals/upload", { method: "POST", body: form });
    state.pendingUploads.push(...result.saved);
    $("#manualResult").textContent = "已暂存：" + result.saved.map((item) => item.name).join("、") + "。尚未影响当前知识库，请点击构建并发布。";
    await loadHealth();
  } catch (error) {
    $("#manualResult").textContent = error.message;
    $("#manualResult").classList.add("error");
  }
}

async function rebuildIndex() {
  $("#rebuildIndexBtn").disabled = true;
  $("#manualResult").textContent = "正在创建手册快照并建立索引；期间暂停问答…";
  $("#manualResult").classList.remove("error");
  try {
    const payload = { upload_ids: state.pendingUploads.map((item) => item.upload_id), base_revision: state.health?.index_revision ?? null, replace_names: [] };
    let result;
    try {
      result = await api("/api/manuals/ingest", { method: "POST", body: JSON.stringify(payload) });
    } catch (error) {
      if (error.code !== "replacement_required" || !window.confirm("存在同名已发布手册。确认用暂存文件替换并重新构建吗？")) throw error;
      payload.replace_names = state.pendingUploads.map((item) => item.name);
      result = await api("/api/manuals/ingest", { method: "POST", body: JSON.stringify(payload) });
    }
    let job;
    do {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      job = await api("/api/manuals/jobs/" + encodeURIComponent(result.job_id));
      $("#manualResult").textContent = job.phase || "正在建立索引…";
    } while (job.state === "running");
    if (job.state !== "succeeded") throw new Error(job.error || "索引构建失败");
    state.pendingUploads = [];
    $("#manualResult").textContent = "已发布知识库版本：" + job.result.revision + "。";
    await loadHealth();
    await loadSamples();
  } catch (error) {
    $("#manualResult").textContent = error.message + "。可检查文件格式，或继续使用预置手册演示。";
    $("#manualResult").classList.add("error");
  } finally {
    $("#rebuildIndexBtn").disabled = false;
  }
}

function updateEvidenceMetrics() {
  const run = state.lastRun;
  if (!run) return;
  const commands = (run.collected || run.commands || []).length;
  const findings = (run.findings || []).length;
  const sources = (run.findings || []).reduce((sum, finding) => sum + ((finding.sources || []).length), 0);
  $("#aiMetrics").innerHTML = '<div><strong>' + escapeHtml(run.elapsed) + 's</strong><span>本次耗时 · ' + escapeHtml(run.execution_mode || "unknown") + '</span></div><div><strong>' + commands + '</strong><span>采集命令</span></div><div><strong>' + findings + '</strong><span>报告条目</span></div><div><strong>' + sources + '</strong><span>手册出处</span></div>';
}

function generateEvidence() {
  const run = state.lastRun || { elapsed: null, commands: [], findings: [] };
  const commandCount = (run.collected || run.commands || []).length;
  const reportCount = (run.findings || []).length;
  const sourceCount = (run.findings || []).reduce((sum, finding) => sum + ((finding.sources || []).length), 0);
  const notesInput = $("#manualNotes");
  let notes = notesInput.value;
  if (notes === notesInput.dataset.i18nValueZh || notes === notesInput.dataset.i18nValueEn) {
    notes = state.locale === "en" ? notesInput.dataset.i18nValueEn : notesInput.dataset.i18nValueZh;
  }
  const md = state.locale === "en" ? [
    "| Dimension | Manual method | Offline AI Ops Assistant | Data source |",
    "| --- | --- | --- | --- |",
    `| Troubleshooting steps | ${$("#manualSteps").value} steps, ${notes} | 1 click + ${commandCount} automated read-only commands | Field notes / this diagnostic |`,
    `| Time | ${$("#manualMinutes").value} minutes | ${run.elapsed == null ? "Auto-filled after a diagnostic" : run.elapsed + " seconds"} | Timed field comparison / this diagnostic |`,
    `| AI collection | Commands entered manually | ${commandCount} read-only commands | Latest diagnostic run |`,
    "| FR-11 acceptance baseline (not measured) | 25 minutes / 14 steps / 3 manual lookups | 3 minutes / 1 click / 6 automated commands | Requirements §4.1 |",
    `| Manual lookups | ${$("#manualLookups").value} | Retrieved from the index with citations | Field notes / report citations |`,
    "| Interpretation reliability | Depends on operator experience; easy to miss details | Deterministic rule-tree results with an expandable path | UI path panel |",
    `| Knowledge reliability | Manually located references | ${reportCount} findings with ${sourceCount} service-provided citations | Report citations |`,
    "| Knowledge capture | Experience remains in personal notes | Save this run as a local skill package | Skill library |",
    "| Cost | Relies on web search or an experienced engineer | Runs locally without an external subscription | Presentation statement |",
    "| Honesty boundary | Operator explains unknowns | Missing evidence and unresolved items are shown explicitly | Report unresolved-items section |",
  ].join("\n") : [
    "| 维度 | 手动方法 | 离线 AI 运维助手 | 数据来源 |",
    "| --- | --- | --- | --- |",
    "| 排障步骤 | " + $("#manualSteps").value + " 步，" + notes + " | 1 次点击 + " + commandCount + " 条自动采集命令 | 现场记录 / 本次诊断 |",
    "| 耗时 | " + $("#manualMinutes").value + " 分钟 | " + (run.elapsed == null ? "待诊断后自动填充" : run.elapsed + " 秒") + " | 双路径现场计时 / 本次诊断 |",
    "| AI 采集命令 | 手动逐条输入 | " + commandCount + " 条只读命令 | 最近一次诊断记录 |",
    "| FR-11 验收基线（非实测） | 25 分钟 / 14 步 / 翻手册 3 次 | 3 分钟 / 1 次点击 / 自动执行 6 条命令 | 需求文档 §4.1 |",
    "| 翻手册次数 | " + $("#manualLookups").value + " 次 | 由索引检索并展示出处 | 现场记录 / 报告出处栏 |",
    "| 判读可靠性 | 依赖个人经验，易漏判 | 规则树确定性判定，路径可展开复核 | UI 路径面板 |",
    "| 知识可信度 | 手动查找，依据分散 | 报告 " + reportCount + " 条，系统返回出处 " + sourceCount + " 条 | 报告出处栏 |",
    "| 知识沉淀 | 经验保留在个人记录中 | 排查结果可存为本地技能包 | 技能库 |",
    "| 成本 | 依赖联网搜索或资深工程师到场 | 本地运行，无外部服务订阅 | 答辩陈述 |",
    "| 诚实边界 | 由人工说明未知项 | 无依据时显示未找到依据，未决项显式列出 | 报告未决栏 |",
  ].join("\n");
  $("#evidenceOutput").value = md;
}

async function copyEvidence() {
  if (!$("#evidenceOutput").value) generateEvidence();
  try {
    await navigator.clipboard.writeText($("#evidenceOutput").value);
    $("#copyEvidenceBtn").textContent = "已复制";
  } catch (error) {
    $("#evidenceOutput").focus();
    $("#evidenceOutput").select();
    document.execCommand("copy");
    $("#copyEvidenceBtn").textContent = "已复制";
  }
  window.setTimeout(() => { $("#copyEvidenceBtn").textContent = "复制 Markdown"; }, 1600);
}

function downloadEvidence() {
  if (!$("#evidenceOutput").value) generateEvidence();
  const blob = new Blob([$("#evidenceOutput").value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "offline-ai-ops-evidence.md";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function setPrompt(prompt) {
  setView("chat");
  state.selectedSkill = null;
  state.manualSkill = false;
  const conversation = activeConversation();
  if (conversation) {
    conversation.skillId = null;
    conversation.manualSkill = false;
    storeConversations();
  }
  renderSkills();
  const faultText = $("#faultText");
  faultText.value = prompt;
  faultText.focus();
  faultText.setSelectionRange(prompt.length, prompt.length);
}

function startSelectedSkillCheckup() {
  if (state.busy || !state.selectedSkill || !state.manualSkill) return;
  const skill = state.skills.find((item) => item.id === state.selectedSkill);
  if (!skill || skill.demo_ready === false) return;
  const conversationId = state.activeConversationId;
  const shouldGenerateTitle = ["新的排障会话", "New troubleshooting chat"].includes(activeConversation()?.title || "");
  const displayedSkillName = state.locale === "en" ? (EN_TRANSLATIONS[skill.name] || skill.name) : skill.name;
  const checkupLabel = state.locale === "en" ? "Run selected skill: " : "一键体检：";
  appendUserMessage(checkupLabel + displayedSkillName);
  if (shouldGenerateTitle) requestConversationTitle(checkupLabel + displayedSkillName, skill.id, conversationId);
  $("#faultText").value = "";
  state.sources = [];
  renderSourceShelf();
  setBusy(true);
  setProgress(1, "准备体检");
  runDiagnostic(skill.id, "一键体检：" + displayedSkillName, $("#executionMode").value);
}

async function simulateSwitchCommand(command) {
  const value = String(command || "").trim().replace(/\s+/g, " ");
  if (!value) return;
  const output = $("#simulatorOutput");
  output.className = "simulator-output";
  output.innerHTML = '<strong>正在调用后端白名单校验…</strong><pre>$ ' + escapeHtml(value) + "</pre>";
  try {
    const result = await api("/api/simulator/check", { method: "POST", body: JSON.stringify({ command: value }) });
    if (!result.allowed) {
      output.className = "simulator-output rejected";
      output.innerHTML = '<strong>后端白名单已拒绝</strong><p>' + escapeHtml(result.reason || "命令不允许") + '</p><pre>$ ' + escapeHtml(value) + "</pre>";
      return;
    }
    output.className = "simulator-output";
    output.innerHTML = '<strong>后端白名单校验通过 · 固定样例输出</strong>' + (result.output ? '<pre>$ ' + escapeHtml(result.command) + "\n" + escapeHtml(result.output) + "</pre>" : '<p>命令已通过后端白名单，但当前没有对应的模拟输出；没有执行真实命令。</p>');
  } catch (error) {
    output.className = "simulator-output rejected";
    output.innerHTML = '<strong>后端校验失败</strong><p>' + escapeHtml(error.message) + '</p>';
  }
}

function bindEvents() {
  $$(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $("#newChatBtn").addEventListener("click", createNewConversation);
  $("#dialogNewChatBtn").addEventListener("click", createNewConversation);
  $("#skillPickerBtn").addEventListener("click", () => $("#skillPickerDialog").showModal());
  $("#closeSkillPicker").addEventListener("click", () => $("#skillPickerDialog").close());
  $("#skillGrid").addEventListener("click", handleSkillListClick);
  $("#skillPickerGrid").addEventListener("click", handleSkillListClick);
  $("#skillSearchInput").addEventListener("input", (event) => {
    state.skillQuery = event.target.value;
    renderSkills();
  });
  $("#skillPickerSearch").addEventListener("input", (event) => {
    state.skillQuery = event.target.value;
    renderSkills();
  });
  $("#autoSkillSelect").addEventListener("click", () => selectSkill(null));
  $("#autoSkillPicker").addEventListener("click", () => selectSkill(null));
  $("#quickCheckupBtn").addEventListener("click", startSelectedSkillCheckup);
  $("#languageToggle").addEventListener("click", () => setLocale(state.locale === "zh-CN" ? "en" : "zh-CN"));
  $("#mobileConversationsBtn").addEventListener("click", () => $("#conversationDialog").showModal());
  $("#conversationList").addEventListener("click", handleConversationListClick);
  $("#conversationDialogList").addEventListener("click", handleConversationListClick);
  $("#refreshStatusBtn").addEventListener("click", () => loadHealth({ interactive: true }));
  $("#refreshSkillsBtn").addEventListener("click", loadSkills);
  $("#composerForm").addEventListener("submit", sendMessage);
  $("#interactionMode").addEventListener("change", () => setBusy(false));
  $("#faultText").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#composerForm").requestSubmit();
    }
  });
  document.body.addEventListener("click", (event) => {
    const promptButton = event.target.closest("[data-prompt]");
    if (!promptButton || state.busy) return;
    const prompt = state.locale === "en" ? (promptButton.dataset.promptEn || promptButton.dataset.prompt) : promptButton.dataset.prompt;
    setPrompt(prompt);
  });
  $("#chatFeed").addEventListener("click", (event) => {
    const sourceButton = event.target.closest("[data-source-index]");
    if (sourceButton) openSource(sourceButton.dataset.sourceIndex);
    if (event.target.closest("[data-save-skill]")) openSkillDialog();
  });
  $("#sourceShelf").addEventListener("click", (event) => {
    const button = event.target.closest("[data-source-index]");
    if (button) openSource(button.dataset.sourceIndex);
  });
  $("#qaForm").addEventListener("submit", askManual);
  $("#selectManualBtn").addEventListener("click", () => $("#manualFile").click());
  $("#manualFile").addEventListener("change", (event) => uploadManual(event.target.files[0]));
  $("#rebuildIndexBtn").addEventListener("click", rebuildIndex);
  $("#memoryList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-memory-delete]");
    if (button) deleteMemory(button.dataset.memoryDelete);
  });
  const dropZone = $("#dropZone");
  dropZone.addEventListener("dragover", (event) => { event.preventDefault(); dropZone.classList.add("dragging"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
  dropZone.addEventListener("drop", (event) => { event.preventDefault(); dropZone.classList.remove("dragging"); uploadManual(event.dataTransfer.files[0]); });
  $("#manualMinutes").addEventListener("input", generateEvidence);
  $("#manualSteps").addEventListener("input", generateEvidence);
  $("#manualLookups").addEventListener("input", generateEvidence);
  $("#manualNotes").addEventListener("input", generateEvidence);
  ["#manualMinutes", "#manualSteps", "#manualLookups", "#manualNotes"].forEach((selector) => $(selector).addEventListener("input", storeEvidenceInputs));
  $("#generateEvidenceBtn").addEventListener("click", generateEvidence);
  $("#copyEvidenceBtn").addEventListener("click", copyEvidence);
  $("#downloadEvidenceBtn").addEventListener("click", downloadEvidence);
  $("#simulatorForm").addEventListener("submit", (event) => {
    event.preventDefault();
    simulateSwitchCommand($("#simulatorCommand").value);
  });
  $$("[data-sim-command]").forEach((button) => button.addEventListener("click", () => {
    $("#simulatorCommand").value = button.dataset.simCommand;
    simulateSwitchCommand(button.dataset.simCommand);
  }));
  $("#saveSkillBtn").addEventListener("click", saveSkill);
  $("#closeSkillDialog").addEventListener("click", () => $("#skillDialog").close());
  $("#cancelSkillSave").addEventListener("click", () => $("#skillDialog").close());
  $("#conversationRenameForm").addEventListener("submit", saveConversationRename);
  $("#closeRenameDialog").addEventListener("click", () => $("#conversationRenameDialog").close());
  $("#cancelRename").addEventListener("click", () => $("#conversationRenameDialog").close());
  $("#conversationRenameDialog").addEventListener("close", () => { state.renameConversationId = null; });
  $("#conversationRenameInput").addEventListener("input", () => $("#renameFeedback").textContent = "");
  window.addEventListener("beforeunload", () => {
    const conversation = activeConversation();
    if (conversation) {
      conversation.html = sourceLocaleConversationHtml();
      conversation.sources = state.sources;
      conversation.lastRun = state.lastRun;
      conversation.updatedAt = Date.now();
    }
    storeConversations();
  });
}

async function init() {
  if (window.location.protocol === "file:") {
    const notice = $("#directOpenNotice");
    if (notice) notice.hidden = false;
    $(".app-shell")?.setAttribute("inert", "");
    return;
  }
  try { state.locale = localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "zh-CN"; } catch (error) { state.locale = "zh-CN"; }
  bindEvents();
  loadConversations();
  loadEvidenceInputs();
  loadSkillReplays();
  generateEvidence();
  renderSamples([]);
  localizePage();
  const localizationObserver = new MutationObserver(() => localizePage());
  localizationObserver.observe(document.body, { childList: true, characterData: true, subtree: true });
  await Promise.all([loadHealth(), loadSkills(), loadSamples(), loadMemories()]);
}

document.addEventListener("DOMContentLoaded", init);
