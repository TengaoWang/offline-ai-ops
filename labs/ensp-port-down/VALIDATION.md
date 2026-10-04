# 验证记录

日期：2026-10-03。此文件明确区分代码测试与厂商仿真器验证。

## 已验证

- 自动测试 **35 项通过**：新增连接模块 26 项，原有 LLM 模块 9 项。运行命令：`.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v`。
- 本地 Python 3.12 环境可以独立运行 `python -m ensp`；无需 Ollama、RAG、UI 或新增依赖。
- 明确标注 `fixture` 的命令行：保存故障报告 → 用健康样例重新采集 → 读取基线 → 生成 `recovered` 结果。
- TCP 协议测试服务上的完整过程：配置两个端点 → 正常采集 → shutdown → 故障判断 → undo shutdown → 新采集复检通过。该服务是测试程序，**不是 eNSP**。
- 单元/接口测试涵盖超时、断线、分页、Telnet 分片、提示符竞态、原始输出边界、错误设备、白名单、HTTP/SSE、模式区分、基线校验。
- 手册依据经本地 PDF 原文核对：PDF 209 页（印刷 131 页）确实区分 Administratively down、DOWN、ERROR DOWN，并给出人为 shutdown 对应的 undo shutdown 操作。

## 尚未通过的真实联调

- 检查时 eNSP Client 和 eNSP VBoxServer 进程存在；目标 Console **127.0.0.1:2000、2001 均连接被拒绝**（WinError 10061），没有正在监听的这两台实验设备。
- 自动恢复 GUI 窗口和抓图没有取得可用的实验画面，不能据此确认拓扑已加载、设备已启动。
- 因此，新 `.topo` 的实际导入、GE0/0/1 连线映射、该镜像的命令格式和真实故障恢复闭环，**仍需在 eNSP 启动实验后验收**。没有用样例数据冒充真实设备输出。
- 当次 CLI 原始检查结果保存在被 Git 忽略的 `ensp-runtime/live-health.json`。

## 最小真实验收清单

按本目录 README 打开并启动两台设备，然后依次完成：

1. `python -m ensp health`：两台 VRP 版本采集成功。
2. `python -m ensp.lab --confirm-lab prepare` 后 `diagnose`：端口 UP、3/3 ping 成功。
3. `fault` 后 `diagnose --output ensp-runtime/before.json`：原始输出出现 Administratively DOWN。
4. 在目标控制台手动 `undo shutdown`，运行 `verify --before ensp-runtime/before.json`：新报告显示 UP、3/3 成功、`recovered`。
5. 断开外网，保留虚拟网卡，重复 2–4；再停止探测设备检查不会误报恢复。

未完成以上步骤前，不应对评委或队友声称真实 eNSP 集成已经验收。
