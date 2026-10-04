# 网络连通排查

业务地址 ping 不通时，从本机地址、网关、目标地址一路查到交换机端口物理状态和端口 VLAN，定位是哪一层出了问题。

## 适用场景

- 某台服务器（如 MES 服务器）业务地址 ping 不通，但其他设备正常
- 怀疑交换机端口 down 或端口 VLAN 划分错误

## 采集内容

| 命令 | 在哪里执行 | 作用 |
|---|---|---|
| `ipconfig /all` | 本机 | 本机是否拿到地址、默认网关是多少 |
| `ping -n 2 -w 1000 网关` | 本机 | 本机到网关是否正常 |
| `ping -n 2 -w 1000 目标` | 本机 | 目标是否可达 |
| `arp -a` | 本机 | 本机 ARP 表 |
| `display interface brief` | 交换机（回放） | 端口物理状态 |
| `display port vlan` | 交换机（回放） | 端口类型和 PVID |

目标地址、端口和业务 VLAN 写在 `collect.yaml` 的 `vars` 里，也可以用环境变量 `OPS_TARGET`、`OPS_PORT`、`OPS_VLAN` 修改；网关从 `ipconfig` 的输出里自动取。

## 安全边界

只执行白名单内的只读命令。报告里的修复命令（如 `port default vlan`、`undo shutdown`）只作为建议展示，不会自动执行。
