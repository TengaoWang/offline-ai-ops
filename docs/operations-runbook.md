# 启动、目标选择与错误恢复

## 开发机启动

1. 准备本地 Ollama 或两个 OpenAI 兼容的 llama.cpp server。
2. 运行 `.venv/bin/python -m llm health`，确认 `rag_ready=true`、`engine_ready` 会在 UI 健康接口中显示。
3. 运行 `.venv/bin/python -m ui.server --host 127.0.0.1 --port 8765`。
4. 浏览器打开 `http://127.0.0.1:8765`。

P0 仅支持 `target.kind=local`。UI 中“本机只读执行”会运行真实白名单命令；“模拟器固定输出”只读取技能固件。普通诊断失败不会自动切换 simulation。

## 常见错误

| HTTP/状态 | 含义 | 处理 |
| --- | --- | --- |
| 409 `busy` | 当前已有问答、诊断或建库操作 | 等当前操作结束后由用户重新提交；服务不会排队或重试 |
| 502 `model_protocol_error` | 本地模型返回不符合 JSON 契约 | 检查模型/后端兼容性和日志，修复后重启服务 |
| 503 `model_unavailable` / `not_ready` | 后端、模型或索引未就绪 | 运行 `python -m llm health` 并按 errors 修复 |
| 504 `model_timeout` | 模型调用超过硬超时，后台状态未知 | 确认模型进程结束或重启模型后端，再重启 UI 服务 |
| 422 `no_skill` | 自动路由没有匹配技能 | 改写故障描述或明确选择一个有效技能 |
| `invalid_skill` | 技能 Schema、白名单或出处校验失败 | 修正四个技能文件；无效包不会执行 |

知识库上传先进入 `kb/staging/`，建库和向量完整性校验全部成功后才原子切换 `current.json`。失败文件进入隔离目录，当前发布版本保持不变。服务重启后进程内运行记录会消失，因此只有当前进程中状态为 `succeeded` 的 `run_id` 可以“存为技能”。

便携包的构建、校验与四组实机验收见 [`../packaging/README.md`](../packaging/README.md)。
