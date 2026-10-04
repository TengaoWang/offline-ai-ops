# 展示实验：网口被关闭 → 引导恢复 → 独立验证

本目录是连接模块的配套实验。使用两台 eNSP **S5700 虚拟交换机**，第二台承担业务探测，不冒充真实 PC。只模拟一个明确故障，方便演示前后对比。

```text
Python / UI -- 本机控制台 2000 --> OPS-SW1
            -- 本机控制台 2001 --> OPS-PROBE

OPS-SW1 GE0/0/1 -------- GE0/0/1 OPS-PROBE
VLANIF10: 192.168.10.1   VLANIF10: 192.168.10.2
              access VLAN 10
```

控制台与业务链路分开，所以业务网口 shutdown 后，助手仍能连上设备查原因；探测从另一台虚拟交换机发起，实际经过被关闭的链路，不用电脑自身 localhost 的 ping 冒充业务恢复。

## 准备一次

1. 在已安装 eNSP 的 Windows 展示电脑上，复制本目录到仓库的 `ensp-runtime/lab/`（被 Git 忽略）。在 eNSP 打开复制出的 `port-down.topo`。原文件作为模板保留。若 eNSP 不接受此拓扑，手动创建两个 S5700，并用铜缆连接双方 **GE0/0/1**，设置 Console 端口 2000、2001。
2. 启动两台设备，等待控制台出现 `<Huawei>`。拓扑图上的设备名称与 VRP 内的 `sysname` 不是一回事，下一步会设置后者。不要同时在 eNSP 控制台敲命令和运行采集器。
3. 核对 **2000=本实验目标交换机、2001=本实验探测交换机**。如端口占用，修改 eNSP 设备的 Console 端口和 `config.json`；也能从 `.topo` 的 `com_port` 字段核对。
4. 初始化仅用于这个新实验的配置：

```powershell
# 在 offline-ai-ops 仓库根目录执行
.\.venv\Scripts\python.exe -X utf8 -m ensp.lab --confirm-lab prepare
.\.venv\Scripts\python.exe -X utf8 -m ensp diagnose --output ensp-runtime\healthy.json
```

`prepare` 写入 sysname、access VLAN10、Vlanif10 的 /24 地址并开启目标网口。**仅对这个可丢弃的新实验使用**；它不是读取原配置再恢复的工具，不适用于已有业务拓扑。写入前检查 S5700/VRP 标识和设备名。参数 `--confirm-lab` 是操作员显式声明目标是本实验，不会弹交互确认。

新启动或刚恢复时，生成树/ARP/接口协议可能还未收敛；等片刻后重新采集，以报告的**物理/协议 UP + 3/3 ping 成功**为准。第一次丢包不要剪掉或伪造为成功。

手工初始化备选：

```text
# OPS-SW1 控制台；注释行不要粘贴到设备
system-view
sysname OPS-SW1
vlan 10
quit
interface GigabitEthernet0/0/1
port link-type access
port default vlan 10
undo shutdown
quit
interface Vlanif10
ip address 192.168.10.1 255.255.255.0
return
```

另一台同样配置，将 sysname 改成 `OPS-PROBE`、地址改成 `192.168.10.2`。

## 展示顺序

1. **确认正常基线**：采集报告显示网口 UP，探测 3/3 成功。
2. **在演示准备工具中注入故障**（关闭目标网口）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ensp.lab --confirm-lab fault
.\.venv\Scripts\python.exe -X utf8 -m ensp diagnose --output ensp-runtime\before.json
```

3. **助手找原因**：UI 展示 `Administratively DOWN`、相关配置原文，以及手册 PDF 第 **209 页** / 印刷页 **131**、§8.2.1 的依据。不要只靠拓扑线颜色判断，具体颜色行为可能因 eNSP 版本不同。
4. **用户按引导修复**：在 OPS-SW1 控制台确认不是有意停用，再输入以下指令：

```text
system-view
interface GigabitEthernet0/0/1
undo shutdown
return
```

5. **点复检或运行 CLI**：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ensp verify --before ensp-runtime\before.json --output ensp-runtime\after.json
```

只有复检返回 `recovery.status = recovered`，才展示“**该实验业务路径已恢复连通**”。它不证明 DNS、应用系统、所有 VLAN 均已恢复。关掉探测设备、拔掉虚拟网线或只让端口 UP 而 ping 仍失败，都不能显示恢复。

排练中快速重置可用 `python -m ensp.lab --confirm-lab restore`，但它是独立实验工具；产品 API 仍遵循设计文档的“自动只读采集，修复指令手动执行”。所有写操作都**不自动 save**，重启设备可能丢失配置；演示前重新 prepare、采集验证。

## 常见问题

| 现象 | 处理 |
|---|---|
| `connection_failed` / WinError 10061 | 设备未启动、Console 端口不对，或端口尚未监听；不是故障排查结果 |
| `timeout` | 等设备完全启动；检查输出是否停在首次启动/登录交互；可适度增大 config timeout（1–60 秒） |
| `wrong_view` | 先在该 eNSP 控制台输入 `return`，停在 `<设备名>` 再运行 |
| `authentication_required` | 实验 Console 配了登录认证；本版本不处理凭据，请用预配置的本机实验控制台 |
| `command_failed` | 查看原始错误，命令语法可能与镜像版本不一致，不要将它当成正常 |
| 普通 `DOWN` / `ERROR DOWN` | 与人为关闭不同；模块不会套用 `undo shutdown` 修复建议 |
| 网口 UP，但 ping 不通 | 检查双方 VLAN10、Vlanif10 地址、虚拟连线与收敛；不要只看网口就报修复成功 |
| `busy` | 同一进程只允许一轮采集；还应避免多个 CLI/服务进程或 GUI Console 同时操作同一设备 |

## 离线和 U 盘

演示时可关闭 Wi-Fi / 拔掉外网网线，**保留本机回环、VirtualBox 虚拟网卡和所需服务**。模块不访问公网，不调用云模型，不下载依赖。

U 盘可携带项目、模型和知识库，但**eNSP / VirtualBox / 驱动要事先在展示电脑安装好**。当前 Python `.venv` 也不能保证复制到任意电脑后可用；本次模块交付不等于完成免安装可执行包。优先用这台已准备的电脑展示，未来再封装 Python 运行时。慢 U 盘可先将运行缓存放本机 SSD，路径无需固定为 D 盘。
