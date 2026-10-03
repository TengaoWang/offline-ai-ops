# finetune：技能路由的评测与（可选）微调

评测 `llm.route()` 能否根据用户对故障的描述选对技能包，并保留一套 LoRA 微调流程，需要时直接使用。

| 用户说 | 输出 |
|---|---|
| MES 连不上数据库了，网关能 ping 通 | `{"skill": "net-unreachable"}` |
| df -h 看到 /var 用了 98% | `{"skill": "disk-full"}` |
| nginx 起不来 | `{"skill": "service-down"}` |
| 帮我看看最近有没有异常登录 | `{"skill": "log-audit"}` |
| 打印机卡纸了 | `{"skill": null}` |

## 结论：目前不微调

| 版本 | 准确率（87 条） | JSON 合法率 | 平均耗时 |
|---|---|---|---|
| **Qwen3-8B 基座 + 提示词，Ollama（交付版）** | **97.7%** | 100% | 0.70 秒 |
| Qwen3-8B 4-bit 基座 + 提示词，MLX | 96.6% | 100% | 1.83 秒 |

均在 MacBook Air M4 16GB 上测得。基线已超过事先定的 90% 门槛，所以交付版只用提示词。
错的 2 条都是同一句话（「应用日志一直报连接数据库失败，mysql 进程不见了」被选成 `log-audit`），这句话本身也有歧义。

## 评测

```bash
python finetune/gen_data.py                                    # 生成 train / valid / test 数据
python finetune/eval.py --backend ollama --tag ollama-base     # 交付版（需要 Ollama + qwen3:8b）
```

结果写入 `finetune/results/<tag>.json`（不进 git）。

数据按「基础说法模板」划分：测试集里的说法在训练集中从未出现，测出来的准确率代表对新说法的泛化能力。
补充说法或技能：编辑 `gen_data.py` 的 `TEMPLATES`；技能列表和提示词的唯一来源是 `llm/router.py` 的 `SKILLS` 和 `SYSTEM_PROMPT`。

## 微调（需要时再用，Apple Silicon）

```bash
uv venv finetune/.venv --python 3.12
uv pip install --python finetune/.venv/bin/python -r finetune/requirements.txt
source finetune/.venv/bin/activate

python finetune/eval.py --tag base                                          # MLX 基线
mlx_lm.lora -c finetune/lora_config.yaml                                    # QLoRA，16GB 内存可跑
python finetune/eval.py --adapter finetune/adapters/qwen3-8b-t1 --tag lora  # 微调后评测
```

- 训练、评测、线上调用必须使用同一份系统提示词，并且都关闭思考模式（`enable_thinking=False`）。
- 模型权重、adapter、生成的数据不进 git（见 `finetune/.gitignore`）。
- 完整步骤（含导出 GGUF、导入 Ollama、Windows 独显电脑的 LLaMA-Factory 配置）见团队的「模型微调操作手册」文档。
