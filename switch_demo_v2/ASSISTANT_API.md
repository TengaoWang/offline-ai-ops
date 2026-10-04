# 单机助手接口

模拟器与离线助手运行在同一台 Windows 电脑，通过本机回环地址通信：

```text
http://127.0.0.1:8878/api/v1
```

该通信不会访问互联网。建议由助手的 Python 后端调用接口，不要让浏览器页面直接跨端口调用。

## 使用顺序

1. `GET /health` 检查模拟器并取得设备列表。
2. `GET /observation` 取得实验编号、业务现象和公开拓扑。
3. `POST /context` 建立指定设备的独立 CLI 会话。
4. `POST /command` 执行查询或配置命令。
5. 修改后通过 `POST /probe` 复检。

展示版还提供两个受控动作：

- `POST /api/v1/diagnose`，请求体为 `{ "epoch": "..." }`，返回 A–E 场景的不同诊断。
- `POST /api/v1/repair`，请求体为 `{ "epoch": "...", "session": "...", "expected": "C" }`。只有所选修复技能与当前 C/D 场景一致时才执行配置；A、B 只诊断，E 转现场处理。

`repair` 不调用宿主机 Shell，也不连接真实交换机。
6. `GET /logs` 可用于展示完整操作轨迹。

助手必须保存 `observation.epoch` 并在执行命令和复检时原样传回。用户切换故障场景后，旧实验编号会收到 HTTP 409，助手应重新读取 `/observation`。

## 请求示例

建立 SW2 会话：

```json
POST /api/v1/context
{
  "session": "offline-assistant",
  "device": "SW2"
}
```

执行命令：

```json
POST /api/v1/command
{
  "session": "offline-assistant",
  "device": "SW2",
  "epoch": "从 observation 取得的实验编号",
  "command": "display ip routing-table"
}
```

同一 `session` 在 SW1、SW2、SW3 上分别保存命令行视图，等价于工程师从一台运维工作站打开多个设备会话。多行命令按顺序执行，某行失败后暂停剩余命令。

复检：

```json
POST /api/v1/probe
{
  "epoch": "从 observation 取得的实验编号"
}
```

## 可信度边界

助手专用接口不会返回 A～E 场景编号、预设根因、内部配置对象、手册场景摘要或规则向导答案。助手只能根据业务现象和设备命令输出完成判断。`/api/scene`、`/api/state` 和 `/api/assistant` 是演示界面的内部接口，不应由正式助手调用。
