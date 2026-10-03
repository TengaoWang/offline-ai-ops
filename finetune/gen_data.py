"""生成 T1「技能路由」微调数据：用户对故障的描述 -> 应调用的技能包。

输出 messages 格式的 jsonl（mlx-lm / LLaMA-Factory 通用）到 finetune/data/：
  train.jsonl / valid.jsonl / test.jsonl

防止数据泄漏：按「基础说法模板」划分数据集，测试集里的说法在训练集中从未出现过，
只有这样测出来的准确率才能代表模型对新说法的泛化能力。

用法：python finetune/gen_data.py [--seed 42]
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 训练、评测与线上调用必须使用同一份系统提示词，唯一来源是 router/router.py
from llm.router import SKILLS, SYSTEM_PROMPT  # noqa: E402

# ---------------------------------------------------------------------------
# 槽位：让同一个说法模板生成多个不同的具体样本
# ---------------------------------------------------------------------------
SLOTS = {
    "ip": ["192.168.10.20", "10.1.20.5", "172.16.3.8", "192.168.1.100", "10.0.0.12", "192.168.50.3"],
    "gw": ["192.168.10.1", "10.1.20.1", "172.16.3.1", "192.168.1.1"],
    "host": ["MES 服务器", "数据库服务器", "财务服务器", "ERP 服务器", "文件服务器", "OA 服务器", "监控主机"],
    "sys": ["MES", "ERP", "OA", "财务系统", "仓库系统", "考勤系统"],
    "svc": ["nginx", "mysql", "redis", "tomcat", "docker", "sshd", "postgresql", "httpd"],
    "port": ["GE0/0/8", "GE0/0/1", "GigabitEthernet0/0/12", "Eth0/0/3"],
    "mount": ["/var", "/", "/home", "/data", "/var/log"],
    "drive": ["C 盘", "D 盘", "系统盘", "数据盘"],
    "pct": ["95%", "98%", "99%", "100%"],
    "user": ["root", "admin", "test", "oracle"],
}

# ---------------------------------------------------------------------------
# 基础说法模板：普通话 / 粤语 / 英文 / 中英混杂，口语化，故意包含不规范表达
# ---------------------------------------------------------------------------
TEMPLATES = {
    "net-unreachable": [
        "{sys} 连不上数据库了，网关 {gw} 能 ping 通",
        "ping {ip} 一直超时，100% 丢包",
        "{host} 突然连不上了，其他机器好像正常",
        "车间的电脑全都上不了内网",
        "交换机上 {port} 那个口的灯不亮了",
        "新划了 VLAN 之后两个网段互相访问不了",
        "{host} 能 ping 通管理口，业务口 ping 不通",
        "网线插上了但是电脑显示网络电缆被拔出",
        "工控机访问不了 {ip}，但能访问网关",
        "服务器之间偶尔丢包，延迟忽高忽低",
        "{sys} 连唔到 {host}，网关 ping 得通",
        "部机 ping 唔通 {ip}，成日 timeout",
        "成个车间都上唔到网，係咪交换机出事",
        "{port} 个口好似冇反应，灯都唔着",
        "can't reach {ip}, ping times out but gateway {gw} is fine",
        "the {host} is unreachable from the office network",
        "packet loss to {ip} is like 80%, connection keeps dropping",
        "{host} ping 不通，traceroute 卡在第二跳",
        "换了根网线还是连不上 {ip}",
        "两台服务器在同一个交换机上却互相 ping 不通",
        "生产线终端全部掉线了，提示无法连接服务器",
        "远程桌面连 {host} 一直连接超时",
        "telnet {ip} 的端口不通，ping 也不通",
        "交换机重启以后有几台机器连不上了",
        "IP 地址正常，就是访问不了别的网段",
        "network down 了，{sys} 完全连不上",
        "{host} 网络好像断了，ssh 连不上，ping 也没回应",
        "隔壁办公室能上内网，我们这边不行",
        "同一个 VLAN 里的机器都不通了",
        "ping {gw} 都不通，是不是网关挂了",
    ],
    "disk-full": [
        "{host} 弹窗说 {drive} 空间不足，只剩 200MB",
        "df -h 看到 {mount} 用了 {pct}",
        "服务器硬盘满了，写不进文件",
        "{mount} 分区快满了，告警一直在响",
        "日志把磁盘占满了怎么办",
        "报错 No space left on device",
        "磁盘空间明明还有，但是提示 inode 用完了",
        "{drive} 红了，系统越来越卡",
        "数据库写入失败，说磁盘满了",
        "备份任务失败，提示目标盘空间不足",
        "{host} 个硬盘爆咗，乜都写唔入",
        "{mount} 用咗 {pct}，点算好",
        "部机话 {drive} 冇位喇",
        "disk is full on {host}, {mount} at {pct}",
        "getting 'No space left on device' when writing logs",
        "{mount} usage {pct}, need to free some space",
        "监控报 {host} 磁盘使用率超过 90%",
        "上传文件失败，后台说存储空间不够",
        "/var/log 好大，把根分区撑满了",
        "du 一下发现某个日志文件有几十个 G",
        "{drive} 只剩几百兆了，不敢乱删东西",
        "docker 镜像把 {mount} 占满了",
        "磁盘配额满了，用户存不了文件",
        "系统盘满了导致服务起不来，先帮我看下磁盘",
        "硬盘使用率 {pct}，要清理一下",
        "disk 告警，{mount} 剩余空间不到 1G",
        "临时目录写满了，程序报错 disk full",
        "存储满了，监控录像存不进去",
    ],
    "service-down": [
        "{svc} 起不来，systemctl status 显示 failed",
        "{sys} 网页打不开，但是服务器能 ping 通",
        "{svc} 服务挂了，重启也没用",
        "{svc} 进程一直在反复重启",
        "网站 502 Bad Gateway",
        "端口 3306 没在监听，{svc} 好像没启动",
        "{sys} 登录页面打不开，网络是通的",
        "服务启动几秒后自己退出了",
        "{svc} 崩了，报 core dumped",
        "{host} 上的 {svc} 停了",
        "{svc} 起唔到，status 话 failed",
        "{sys} 个网页开唔到，但部机 ping 得通",
        "{svc} 成日自己死咗",
        "{svc} won't start, status shows failed",
        "{sys} web page returns 503 but the server is reachable",
        "the {svc} service keeps crashing after a few seconds",
        "{svc} restart 之后马上又 exit 了",
        "接口返回 connection refused，服务器本身在线",
        "定时任务没跑，好像 crond 没启动",
        "{sys} 后台服务停了，用户都在投诉",
        "{svc} 占用 CPU 100% 然后卡死了",
        "重启服务器之后 {svc} 没有自动起来",
        "{svc} 报端口被占用，启动失败",
        "应用日志一直报连接数据库失败，mysql 进程不见了",
        "{sys} 打开很慢然后白屏，服务器网络正常",
        "服务状态是 inactive (dead)",
        "{host} 上的 {sys} 进程没了",
        "tomcat 启动报错，页面 404",
    ],
    "log-audit": [
        "帮我看看最近有没有异常登录",
        "有人半夜登录了 {host}，查一下是谁",
        "看下 {user} 账号最近都做了什么操作",
        "查一下有没有暴力破解 ssh 的记录",
        "昨天谁改过交换机配置",
        "分析一下 {host} 的系统日志有没有异常",
        "安全检查要导出最近一周的登录记录",
        "怀疑服务器被入侵了，看看日志",
        "auth.log 里有很多 Failed password",
        "审计一下有没有人用 {user} 登录",
        "睇下最近有冇人登入过 {host}",
        "查下 {user} 个户口做过啲乜",
        "啲日志好似有啲古怪，帮我睇睇",
        "check recent login history on {host}",
        "any suspicious ssh logins in the last 24 hours?",
        "audit who changed the config on the switch yesterday",
        "日志里出现大量登录失败，来自同一个 IP",
        "要做等保检查，整理一下操作日志",
        "看看有没有人在非工作时间登录过",
        "有个陌生账号出现在登录记录里",
        "帮我把 {host} 的 secure 日志过一遍",
        "最近一周 {user} 登录失败了多少次",
        "检查一下 sudo 的使用记录",
        "领导让我查一下上周五谁操作过数据库服务器",
        "日志审计，找出所有 root 登录",
        "有没有人删过 {host} 上的文件，查日志",
    ],
    None: [
        "打印机卡纸了",
        "帮我重置一下 OA 的登录密码",
        "Excel 的 VLOOKUP 怎么用",
        "会议室投影仪连不上笔记本",
        "鼠标没反应了",
        "怎么申请新员工的邮箱账号",
        "显示器闪屏",
        "Word 文档打不开，提示格式错误",
        "今天中午吃什么",
        "帮我写一份周报",
        "公司 Wi-Fi 密码是多少",
        "打印机打唔到嘢",
        "部电脑好慢，係咪要换新",
        "点样改电脑嘅壁纸",
        "how do I install Microsoft Office",
        "my keyboard is not working",
        "can you translate this email to English",
        "笔记本电池鼓包了",
        "怎么在 PPT 里插入视频",
        "帮我订一间下午三点的会议室",
        "U 盘插上没反应",
        "手机怎么连公司的 VPN",
        "电脑开机黑屏，风扇在转",
        "复印机显示缺墨",
        "如何申请软件采购",
        "给我讲个笑话",
        "考勤机打卡没记录",
        "耳机没有声音",
    ],
}

# ---------------------------------------------------------------------------
# 噪声增强：现场用户的真实输入往往带情绪、带前后缀、标点随意
# ---------------------------------------------------------------------------
PREFIXES = ["", "", "", "急！", "老板在催，", "帮忙看下，", "请问", "唔该，", "help, ", "紧急：", "又出问题了，"]
SUFFIXES = ["", "", "", "。", "！！", "，怎么办", "，点算", "?", "，在线等", "，生产线要停了"]


def fill(template: str, rng: random.Random) -> str:
    out = template
    for key, values in SLOTS.items():
        token = "{" + key + "}"
        while token in out:
            out = out.replace(token, rng.choice(values), 1)
    return out


def augment(text: str, rng: random.Random) -> str:
    text = rng.choice(PREFIXES) + text + rng.choice(SUFFIXES)
    if rng.random() < 0.15:  # 偶尔去掉所有空格，模拟随手输入
        text = text.replace(" ", "")
    return text


def to_example(text: str, skill) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
            {"role": "assistant", "content": json.dumps({"skill": skill}, ensure_ascii=False)},
        ]
    }


def build(seed: int, per_template: dict) -> dict:
    rng = random.Random(seed)
    splits = {"train": [], "valid": [], "test": []}
    for skill, templates in TEMPLATES.items():
        ids = list(range(len(templates)))
        rng.shuffle(ids)
        n_test = max(4, round(len(ids) * 0.2))
        n_valid = max(3, round(len(ids) * 0.1))
        assignment = {
            "test": ids[:n_test],
            "valid": ids[n_test:n_test + n_valid],
            "train": ids[n_test + n_valid:],
        }
        for split, tids in assignment.items():
            for tid in tids:
                seen = set()
                for _ in range(per_template[split] * 4):  # 多试几次以凑够不重复的样本
                    if len(seen) >= per_template[split]:
                        break
                    text = augment(fill(templates[tid], rng), rng)
                    if text in seen:
                        continue
                    seen.add(text)
                    splits[split].append(to_example(text, skill))
    for rows in splits.values():
        rng.shuffle(rows)
    return splits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()

    # 训练集每个模板多生成几条（槽位、噪声不同），验证/测试集每个模板 3 条
    splits = build(args.seed, per_template={"train": 6, "valid": 3, "test": 3})

    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        with open(args.out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    for name, rows in splits.items():
        counts = {}
        for row in rows:
            label = json.loads(row["messages"][-1]["content"])["skill"]
            counts[label] = counts.get(label, 0) + 1
        print(f"{name:5s} {len(rows):4d}  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
