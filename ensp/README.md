# eNSP 连接模块：给前端和 RAG 的接入口

本模块负责**本机控制台连接 → 只读采集 → 确定性判定 → 修复建议 → 重新采集验证**。没有 Ollama、RAG、UI 依赖，只用 Python 3.10+ 标准库。与现有 `llm/` 独立，可先并行开发。

当前只实现一个完整场景：**S5700 的指定业务网口被 `shutdown`**。它不是通用交换机管理平台，也不包含完整产品 UI / 通用 Skill 引擎。

## 1. 队友现在怎么接

在仓库根目录启动（Windows）：

```powershell
# 前端开发用：明确标注 fixture，不需要 eNSP
.\.venv\Scripts\python.exe -X utf8 -m ensp --fixture admin-down serve

# 实际设备采集：先按 ../labs/ensp-port-down/README.md 启动实验
.\.venv\Scripts\python.exe -X utf8 -m ensp serve
```

两个命令任选一个，同一时间只运行一个采集服务。默认地址 `http://127.0.0.1:8766/api/ensp/v1`。接口只绑定本机，默认允许 Vite 的 `http://localhost:5173` 和 `http://127.0.0.1:5173`；其他本机 UI 端口通过 `serve --allow-origin http://localhost:3000` 添加。前端用本地 HTTP 打开；`file://` 的 `null` Origin 不允许。

连接不成功时会返回真实错误，**不会偷偷切换到 fixture**。界面始终展示响应的 `mode`，fixture 要标为“开发样例数据”。支持的固定样例：`admin-down`、`healthy`、`link-down`、`error-down`、`ping-failed`、`unavailable`。

| HTTP 接口 | 请求 | 返回 |
|---|---|---|
| `GET /config` | 无 | 模式、配置，不访问设备 |
| `GET /health` | 无 | 两台设备的 VRP 版本采集，`ready` 表示控制台可用 |
| `POST /diagnose` | `{}` | 完整诊断报告 |
| `POST /verify` | `{"before_run_id":"上一次诊断的 run_id"}` | 重新采集并对比，增加 `recovery` |
| `POST /diagnose/stream` | `{}` | SSE 事件，最后包含完整报告 |
| `POST /verify/stream` | 同 `/verify` | SSE 复检事件 |

POST 必须发 `Content-Type: application/json`。无任意命令执行、修改配置或修复接口；前端无需也不能传命令/主机地址。

```js
const base = "http://127.0.0.1:8766/api/ensp/v1";
const response = await fetch(`${base}/diagnose`, {
  method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"
});
const report = await response.json();
if (!response.ok) throw new Error(report.error.message);
// 显示 report.mode、diagnosis、commands、repair_plan、references。
// 用户在 eNSP 手动修复后：
const checked = await fetch(`${base}/verify`, {
  method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify({before_run_id: report.run_id})
}).then(r => r.json());
```

## 2. 实时事件和报告契约（v1.0）

SSE 使用 **POST + fetch 的响应流**，不是只支持 GET 的原生 `EventSource`。每条格式如下，UTF-8 编码，两次换行分隔；读取端需累积跨网络分块的半条事件，`TextDecoder.decode(chunk, {stream: true})` 可处理分段中文。

```text
event: command_started
data: {"event":"command_started","run_id":"…","sequence":2,"mode":"live","timestamp":"…","device":"OPS-SW1","command":"display version"}

```

| 事件 | 额外字段 | UI 用法 |
|---|---|---|
| `run_started` | `operation` | 开始新一轮诊断/复检 |
| `command_started` | `device`, `command` | 命令显示“执行中” |
| `command_output` | `device`, `command`, `chunk` | 展示过程文本；终端转义可能跨分块，最终以完整输出为准 |
| `command_finished` | `result` | 展示状态、完整 `raw_output`、耗时与错误 |
| `report` | `report` | 渲染完整结论 |
| `done` | 无 | 本轮结束 |
| `error` | `error.code`, `error.message` | 流已经开始后的异常，可能没有 run_id |

健康检查只做连接检测，不等于业务正常。请求正常完成但设备故障/断开时 HTTP 仍为 200，必须检查 `ready` 或 `verification.passed`。参数错误为 400、基线不存在 404、采集中再次请求 409。SSE 建立之前的这些错误也是 JSON；建立之后才以 `error` 事件结束。

诊断报告关键字段：

```json
{
  "schema_version": "1.0",
  "run_id": "每次采集的新 UUID",
  "mode": "live",
  "target": {"device": "OPS-SW1", "interface": "GigabitEthernet0/0/1"},
  "diagnosis": {
    "code": "administratively_down", "severity": "critical",
    "summary": "应启用的业务网口被配置为关闭。", "source": "rule"
  },
  "observations": {
    "interface": {"state": "admin_down", "physical": "Administratively DOWN", "protocol": "DOWN"},
    "ping": {"state": "fail", "sent": 3, "received": 0, "loss_percent": 100}
  },
  "verification": {"passed": false, "scope": "configured_virtual_business_path"},
  "repair_plan": {"execution": "manual_only", "commands": ["system-view", "interface GigabitEthernet0/0/1", "undo shutdown", "return"]}
}
```

上例是精简示意；实际还返回 `commands`（原始输出）、`references`（人工核对的手册依据）、`rag_context`、时间、配置指纹。`repair_plan`、`references` 只在匹配的故障上提供。

- `commands[].status`：`ok` / `error` / `timeout` / `skipped`。命令执行完不代表网络正常。
- `verification.passed`：`true` / `false` / `null`，`null` 是证据不足，不能渲染为绿色成功。
- `diagnosis.code`：`administratively_down`、`intentionally_disabled`、`error_down`、`link_down`、`path_unreachable`、`insufficient_evidence`、`healthy`。
- `recovery.status`：`recovered`、`not_recovered`、`unknown`、`healthy_without_failed_baseline`。只有**同一配置和模式下，之前失败、本次端口物理及协议 UP 且独立业务源地址 ping 3/3 成功**，才返回 `recovered`。
- `intentionally_disabled` 表示配置没有声明端口应启用，不是系统已经知道管理员的真实意图；不给启用建议。
- 同一进程保留最近 20 份报告。服务重启后应重新诊断；跨进程 CLI 通过 `--before` 读取先前报告。

前端输出原始日志请使用文本节点/`textContent`，不要将设备输出拼成 HTML。低层控制台错误与诊断错误分别呈现，避免把“连接不到 eNSP”显示成“交换机坏了”。

## 3. Python / RAG 对接

```python
from ensp import EnspService, LabConfig

service = EnspService(LabConfig.load("labs/ensp-port-down/config.json"))
report = service.diagnose(on_event=lambda event: print(event))
# 在已有后端中复用这个 service 实例，统一管理基线和采集锁。
# 用户完成修复后：service.verify(report["run_id"])

# RAG 同学可选接入；不是 ensp 的运行依赖：
from llm import retrieve
sources = retrieve(report["rag_context"]["query"], k=3)
```

RAG 可以用 `commands[].raw_output` 解释证据、补充手册检索。`references` 的页码已经人工核对；**不要让模型改写原始观测值、伪造页码，或把未知复检状态改成“已恢复”**。目前这里只给出一个场景的确定性判定，不会接管其他同学的技能路由、知识库和 UI。

## 4. CLI 和测试

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ensp health
.\.venv\Scripts\python.exe -X utf8 -m ensp diagnose --output ensp-runtime\before.json
.\.venv\Scripts\python.exe -X utf8 -m ensp verify --before ensp-runtime\before.json --output ensp-runtime\after.json
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_ensp -v
```

全局参数 `--config 路径`、`--fixture 场景` 放在子命令前。默认配置相对于模块位置定位，不写死 D 盘。CLI 退出码：0=检查通过；2=发现问题或证据不足（报告仍成功生成）；1=参数/运行错误。

测试覆盖真实 TCP 套接字上的**自建 VRP 协议测试服务**、Telnet 分片协商、分页、超时/断线/输出上限、初始提示符竞态、故障注入到复检闭环、HTTP/SSE 和错误分支。它证明代码与协议处理按测试预期运行，**不能代替厂商 eNSP 的兼容性验收**。

当前实际验证记录见 [../labs/ensp-port-down/VALIDATION.md](../labs/ensp-port-down/VALIDATION.md)。
