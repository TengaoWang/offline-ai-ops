# 启动、目标选择与错误恢复

## 开发机启动

1. 准备本地 Ollama 或两个 OpenAI 兼容的 llama.cpp server。
2. 运行 `.venv/bin/python -m llm health`，确认 `rag_ready=true`、`engine_ready` 会在 UI 健康接口中显示。
3. 运行 `.venv/bin/python -m ui.server --host 127.0.0.1 --port 8765`。
4. 浏览器打开 `http://127.0.0.1:8765`。

诊断目标支持 `target.kind=local` 和受限的 `target.kind=simulator`。本机目标运行白名单命令或技能固件；模拟器目标只允许 `simulation` 模式，并且只连接 `http://127.0.0.1:<port>/api/v1`。选择“交换机实验连通性诊断”技能时，UI 会自动连接默认端口 `8878`。普通诊断失败不会自动切换目标或执行模式。

使用交换机模拟器前，先启动 `switch-lab.exe --port 8878`，确认 `GET http://127.0.0.1:8878/api/v1/health` 返回 `status=ready`。助手会自动读取实验编号、建立独立设备会话，并执行 `display`、`ping`、`ipconfig` 和复检接口；配置类命令始终由后端拒绝。

## 常见错误

| HTTP/状态 | 含义 | 处理 |
| --- | --- | --- |
| 409 `busy` | 当前已有问答、诊断或建库操作 | 等当前操作结束后由用户重新提交；服务不会排队或重试 |
| 502 `model_protocol_error` | 本地模型返回不符合 JSON 契约 | 检查模型/后端兼容性和日志，修复后重启服务 |
| 503 `model_unavailable` / `not_ready` | 后端、模型或索引未就绪 | 运行 `python -m llm health` 并按 errors 修复 |
| 504 `model_timeout` | 模型调用超过硬超时，后台状态未知 | 确认模型进程结束或重启模型后端，再重启 UI 服务 |
| 422 `no_skill` | 自动路由没有匹配技能 | 改写故障描述或明确选择一个有效技能 |
| `invalid_skill` | 技能 Schema、白名单或出处校验失败 | 修正四个技能文件；无效包不会执行 |
| `simulator_unavailable` | 无法连接本机交换机模拟器 | 启动 `switch-lab.exe --port 8878` 并检查健康接口 |
| `simulator_stale` | 实验场景已切换，原实验编号失效 | 重新发起一次诊断，助手会读取新的实验编号 |

知识库上传先进入 `kb/staging/`，建库和向量完整性校验全部成功后才原子切换 `current.json`。失败文件进入隔离目录，当前发布版本保持不变。服务重启后进程内运行记录会消失，因此只有当前进程中状态为 `succeeded` 的 `run_id` 可以“存为技能”。

便携包的构建、校验与四组实机验收见 [`../packaging/README.md`](../packaging/README.md)。
