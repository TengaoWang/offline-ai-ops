# eval：技能路由评测

评测 `llm.route()` 能否根据用户对故障的描述选对技能包。

| 用户说 | 输出 |
|---|---|
| MES 连不上数据库了，网关能 ping 通 | `{"skill": "net-unreachable"}` |
| df -h 看到 /var 用了 98% | `{"skill": "disk-full"}` |
| nginx 起不来 | `{"skill": "service-down"}` |
| 帮我看看最近有没有异常登录 | `{"skill": "log-audit"}` |
| 打印机卡纸了 | `{"skill": null}` |

## 结果

| 模型 | 准确率（87 条） | JSON 合法率 | 平均耗时 |
|---|---|---|---|
| Qwen3-8B 基座 + 提示词（Ollama） | **97.7%** | 100% | 0.70 秒 |

在 MacBook Air M4 16GB 上测得。准确率已超过事先定的 90% 门槛，因此**不做微调**，只用提示词。
错的 2 条是同一句话（「应用日志一直报连接数据库失败，mysql 进程不见了」被选成 `log-audit`），这句话本身也有歧义。

## 运行

需要本机 Ollama 已运行并下载 `qwen3:8b`（见项目根目录 README）。

```bash
.venv/bin/python eval/gen_data.py      # 生成测试数据到 eval/data/
.venv/bin/python eval/eval_route.py    # 评测，结果写入 eval/results/qwen3-8b.json
```

换模型对比：`.venv/bin/python eval/eval_route.py --model qwen3:4b --tag qwen3-4b`。

## 测试数据

- 每个技能 26 到 30 个「基础说法」（普通话、粤语、英文、中英混杂），替换 IP、服务名、分区等槽位，再加上「急！」「点算」之类的前后缀。
- 按基础说法划分数据集：测试集里的说法不会出现在其他数据中，测出来的准确率代表对新说法的泛化能力。
- 测试题由模板生成，比真实用户的说法规整，样本量也小，实际准确率可能更低。

补充说法或技能：编辑 `gen_data.py` 的 `TEMPLATES`；技能列表和提示词的唯一来源是 `llm/router.py` 的 `SKILLS` 和 `SYSTEM_PROMPT`。改完后重新生成数据并评测。
